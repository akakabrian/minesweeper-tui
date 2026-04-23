"""Pure-Python Minesweeper engine.

Design contract (mirrors what a SWIG-wrapped native engine would expose):

    from minesweeper_tui.engine import new_game, Difficulty
    g = new_game(Difficulty.BEGINNER)
    g.reveal(x, y)           # returns ActionResult
    g.flag(x, y)
    g.chord(x, y)
    g.state_snapshot()       # dict — JSON-safe, fed to the REST API

State machine:
    READY   → board generated, no cells revealed yet. First reveal
              seeds mines if not already seeded (so the first click
              is guaranteed safe along with its 8 neighbours).
    PLAYING → at least one reveal has happened.
    WON     → every non-mine cell is revealed.
    LOST    → a mine cell was revealed.

The engine never touches I/O. Timing lives in the App — `state_snapshot`
returns the game state; the UI owns the wall-clock timer.
"""

from __future__ import annotations

import enum
import random
from dataclasses import dataclass, field
from typing import Iterator


# -------- difficulty presets --------

class Difficulty(enum.Enum):
    BEGINNER = ("Beginner",      9,  9,  10)
    INTERMEDIATE = ("Intermediate", 16, 16, 40)
    EXPERT = ("Expert",       30, 16, 99)
    CUSTOM = ("Custom",       0,  0,  0)

    @property
    def label(self) -> str:
        return self.value[0]

    @property
    def width(self) -> int:
        return self.value[1]

    @property
    def height(self) -> int:
        return self.value[2]

    @property
    def mines(self) -> int:
        return self.value[3]


class GameState(enum.Enum):
    READY = "ready"
    PLAYING = "playing"
    WON = "won"
    LOST = "lost"


class ActionResult(enum.Enum):
    """What happened when an action was applied."""
    OK = "ok"                 # reveal / flag / chord applied
    NO_CHANGE = "no_change"   # action had no effect (already revealed,
                              # flagged-cell can't be revealed, etc.)
    MINE = "mine"             # reveal hit a mine → game LOST
    WIN = "win"               # reveal / chord cleared the last safe cell
    INVALID = "invalid"       # out-of-bounds, or game already over


# -------- cell-state enum --------
# Stored as ints in the board arrays for minimal overhead; exposed as an
# Enum-like constant set.
HIDDEN = 0
REVEALED = 1
FLAGGED = 2
QUESTION = 3  # reserved for a "?" toggle; left-click-cycle not shipped v0.1

MINE = -1  # sentinel adjacency count meaning "this cell is a mine"


@dataclass
class Game:
    width: int
    height: int
    mine_count: int
    seed: int | None = None

    # Arrays, row-major. adjacency[y * W + x]:
    #   -1 → mine, 0..8 → neighbour-mine count.
    # state[y * W + x]: HIDDEN / REVEALED / FLAGGED / QUESTION.
    adjacency: list[int] = field(default_factory=list)
    state: list[int] = field(default_factory=list)

    # Lifecycle flags / counters.
    mines_seeded: bool = False
    game_state: GameState = GameState.READY
    flags_placed: int = 0
    cells_revealed: int = 0
    # For loss-state: cell that actually exploded, so the UI can flash it
    # differently from the other mines it reveals.
    exploded_at: tuple[int, int] | None = None

    # RNG kept as an attribute so reproducible seeds → deterministic boards.
    _rng: random.Random = field(default_factory=random.Random)

    # --- geometry helpers ---

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def _idx(self, x: int, y: int) -> int:
        return y * self.width + x

    def neighbours(self, x: int, y: int) -> Iterator[tuple[int, int]]:
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if self.in_bounds(nx, ny):
                    yield nx, ny

    # --- derived state ---

    @property
    def total_cells(self) -> int:
        return self.width * self.height

    @property
    def safe_cells(self) -> int:
        return self.total_cells - self.mine_count

    @property
    def mines_remaining(self) -> int:
        """Classic Minesweeper "mines counter" — mine_count minus flags.
        May go negative if the player over-flags; UI shows it as-is."""
        return self.mine_count - self.flags_placed

    @property
    def is_over(self) -> bool:
        return self.game_state in (GameState.WON, GameState.LOST)

    # --- mine seeding ---

    def _seed_mines(self, first_x: int, first_y: int) -> None:
        """Place `mine_count` mines, avoiding the 3x3 around (first_x, first_y)."""
        forbidden: set[int] = set()
        for nx, ny in self.neighbours(first_x, first_y):
            forbidden.add(self._idx(nx, ny))
        forbidden.add(self._idx(first_x, first_y))

        candidates = [i for i in range(self.total_cells) if i not in forbidden]
        # Edge case: tiny boards where mine_count >= candidates. Clamp.
        n = min(self.mine_count, len(candidates))
        picks = self._rng.sample(candidates, n)
        for i in picks:
            self.adjacency[i] = MINE
        # Update mine_count in case we clamped.
        self.mine_count = n
        # Compute adjacency numbers.
        for y in range(self.height):
            for x in range(self.width):
                if self.adjacency[self._idx(x, y)] == MINE:
                    continue
                count = 0
                for nx, ny in self.neighbours(x, y):
                    if self.adjacency[self._idx(nx, ny)] == MINE:
                        count += 1
                self.adjacency[self._idx(x, y)] = count
        self.mines_seeded = True

    # --- core actions ---

    def reveal(self, x: int, y: int) -> ActionResult:
        if self.is_over or not self.in_bounds(x, y):
            return ActionResult.INVALID
        idx = self._idx(x, y)
        if self.state[idx] == FLAGGED:
            return ActionResult.NO_CHANGE
        if self.state[idx] == REVEALED:
            return ActionResult.NO_CHANGE
        # First click: seed mines now so this cell + neighbours are safe.
        if not self.mines_seeded:
            self._seed_mines(x, y)
            self.game_state = GameState.PLAYING
        # Step on a mine → lose.
        if self.adjacency[idx] == MINE:
            self.state[idx] = REVEALED
            self.game_state = GameState.LOST
            self.exploded_at = (x, y)
            # Reveal every other mine cell so the post-game view shows
            # the full minefield (classic behaviour).
            for i, adj in enumerate(self.adjacency):
                if adj == MINE:
                    self.state[i] = REVEALED
            return ActionResult.MINE
        # Safe cell → reveal, flood-fill if zero neighbours.
        self._flood_reveal(x, y)
        if self.cells_revealed == self.safe_cells:
            self.game_state = GameState.WON
            # Auto-flag all remaining mines for a tidy end-state view.
            for i, adj in enumerate(self.adjacency):
                if adj == MINE and self.state[i] != FLAGGED:
                    self.state[i] = FLAGGED
                    self.flags_placed += 1
            return ActionResult.WIN
        return ActionResult.OK

    def _flood_reveal(self, x: int, y: int) -> None:
        """BFS flood-fill from (x, y). Reveals the target cell and, if its
        adjacency count is 0, recursively its 8 neighbours.

        Uses an explicit stack so very large zero-regions can't blow the
        Python recursion limit. On an Expert board a single flood can
        reveal ~300 cells."""
        stack = [(x, y)]
        while stack:
            cx, cy = stack.pop()
            if not self.in_bounds(cx, cy):
                continue
            i = self._idx(cx, cy)
            if self.state[i] == REVEALED:
                continue
            if self.state[i] == FLAGGED:
                continue
            if self.adjacency[i] == MINE:
                continue  # defensive — caller already short-circuited
            self.state[i] = REVEALED
            self.cells_revealed += 1
            if self.adjacency[i] == 0:
                for nx, ny in self.neighbours(cx, cy):
                    stack.append((nx, ny))

    def flag(self, x: int, y: int) -> ActionResult:
        """Toggle flag on a HIDDEN cell. No-op on revealed cells."""
        if self.is_over or not self.in_bounds(x, y):
            return ActionResult.INVALID
        if not self.mines_seeded:
            # You can flag before the first reveal — just move out of READY.
            self.game_state = GameState.PLAYING
        idx = self._idx(x, y)
        s = self.state[idx]
        if s == REVEALED:
            return ActionResult.NO_CHANGE
        if s == FLAGGED:
            self.state[idx] = HIDDEN
            self.flags_placed -= 1
            return ActionResult.OK
        # HIDDEN or QUESTION → flag.
        self.state[idx] = FLAGGED
        self.flags_placed += 1
        return ActionResult.OK

    def chord(self, x: int, y: int) -> ActionResult:
        """Classic chord. On a REVEALED numbered cell whose flag-count among
        its 8 neighbours equals its adjacency number, reveal all other
        (non-flag) neighbours at once. Any-hidden-mines-in-the-unrevealed-
        set causes a loss."""
        if self.is_over or not self.in_bounds(x, y):
            return ActionResult.INVALID
        idx = self._idx(x, y)
        if self.state[idx] != REVEALED:
            return ActionResult.NO_CHANGE
        num = self.adjacency[idx]
        if num <= 0:
            return ActionResult.NO_CHANGE
        flags = 0
        targets: list[tuple[int, int]] = []
        for nx, ny in self.neighbours(x, y):
            ni = self._idx(nx, ny)
            if self.state[ni] == FLAGGED:
                flags += 1
            elif self.state[ni] == HIDDEN:
                targets.append((nx, ny))
        if flags != num:
            return ActionResult.NO_CHANGE
        # Apply reveals. Any one of them hitting a mine loses; keep
        # revealing the rest so the board view matches the rule. Use a
        # single outcome — the most severe wins (MINE > WIN > OK).
        outcome = ActionResult.NO_CHANGE
        for tx, ty in targets:
            r = self.reveal(tx, ty)
            if r == ActionResult.MINE:
                outcome = ActionResult.MINE
                # reveal() already flipped every mine cell; stop further
                # reveals — they'd be no-ops on a LOST game.
                break
            if r == ActionResult.WIN:
                outcome = ActionResult.WIN
            elif r == ActionResult.OK and outcome == ActionResult.NO_CHANGE:
                outcome = ActionResult.OK
        return outcome

    # --- serialisation ---

    def state_snapshot(self) -> dict:
        """JSON-safe snapshot for the REST API / tests / save-load."""
        return {
            "width": self.width,
            "height": self.height,
            "mine_count": self.mine_count,
            "flags_placed": self.flags_placed,
            "mines_remaining": self.mines_remaining,
            "cells_revealed": self.cells_revealed,
            "safe_cells": self.safe_cells,
            "game_state": self.game_state.value,
            "mines_seeded": self.mines_seeded,
            "exploded_at": list(self.exploded_at) if self.exploded_at else None,
            # Flatten cell view: list[ list[ {state, adj} ] ] row-major.
            # `adj` is -1 for mine, 0..8 otherwise. For covered cells we
            # mask adj to null to avoid leaking solutions over the API.
            "cells": [
                [
                    self._cell_view(x, y)
                    for x in range(self.width)
                ]
                for y in range(self.height)
            ],
        }

    def _cell_view(self, x: int, y: int) -> dict:
        i = self._idx(x, y)
        s = self.state[i]
        adj = self.adjacency[i]
        # Hide adjacency for unrevealed cells unless the game is over.
        reveal_adj = (s == REVEALED) or self.is_over
        return {
            "state": ["hidden", "revealed", "flagged", "question"][s],
            "adj": adj if reveal_adj else None,
        }


# -------- factories --------

def new_game(
    difficulty: Difficulty = Difficulty.BEGINNER,
    *,
    width: int | None = None,
    height: int | None = None,
    mines: int | None = None,
    seed: int | None = None,
) -> Game:
    """Factory. If `difficulty` is CUSTOM, width/height/mines must be given.

    Otherwise they override the preset values (the skill's gotcha catalogue
    says "make overrides possible" — agent scripts love to tune).
    """
    if difficulty is Difficulty.CUSTOM:
        if width is None or height is None or mines is None:
            raise ValueError("Custom difficulty requires width, height, mines")
        w, h, m = width, height, mines
    else:
        w = width or difficulty.width
        h = height or difficulty.height
        m = mines if mines is not None else difficulty.mines
    w = max(4, min(w, 80))
    h = max(4, min(h, 40))
    m = max(1, min(m, w * h - 9))

    g = Game(width=w, height=h, mine_count=m, seed=seed)
    g.adjacency = [0] * (w * h)
    g.state = [HIDDEN] * (w * h)
    if seed is not None:
        g._rng = random.Random(seed)
    return g
