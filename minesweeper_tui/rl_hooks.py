"""RL exposure hooks for minesweeper-tui.

Headless adapter — bypasses Textual entirely. An RL "step" is one
reveal/flag action on a chosen cell (flat index into the board).

State vector layout (flat float32, padded to STATE_DIM=200):
    Beginner board is 9x9=81 cells. Each cell encoded as:
        -1 hidden, 0-8 revealed count, 9 flagged, 10 mine (post-loss)
    Normalize by /10 → [-0.1, 1.0].

    Layout (total = 81 + 6 = 87, padded to 90):
    [0:81]   cell states normalized
    [81]     mines_remaining / mine_count
    [82]     flags_placed / mine_count
    [83]     cells_revealed / safe_cells
    [84]     game_state one-hot-ish: 0 ready, 0.33 playing, 0.66 won, 1 lost
    [85]     cursor_x / W   (always 0 for headless — kept for parity)
    [86]     cursor_y / H
    [87:90]  padding/reserved

Reward shaping:
    +1 per safe tile newly revealed (handles floodfill batches)
    -10 mine hit (terminal)
    +5 on win

Terminal: game_state == WON or LOST.
"""

from __future__ import annotations

import numpy as np

from .engine import (
    Difficulty, Game, GameState, HIDDEN, REVEALED, FLAGGED, MINE, new_game,
)

STATE_DIM = 90


class RLGame:
    """Headless minesweeper driver on BEGINNER (9x9, 10 mines)."""

    def __init__(self, seed: int | None = None,
                 difficulty: Difficulty = Difficulty.BEGINNER):
        self.seed = seed
        self.difficulty = difficulty
        self.game: Game = new_game(difficulty, seed=seed)
        self._prev_revealed = 0
        self._prev_over = False

    def reset(self) -> None:
        self.game = new_game(self.difficulty, seed=self.seed)
        self._prev_revealed = 0
        self._prev_over = False

    def step_reveal(self, x: int, y: int) -> None:
        if self.game.is_over:
            return
        self.game.reveal(x, y)

    def step_flag(self, x: int, y: int) -> None:
        if self.game.is_over:
            return
        self.game.flag(x, y)

    # RL surface ------------------------------------------------------

    def game_state_vector(self) -> np.ndarray:
        g = self.game
        vec = np.zeros(STATE_DIM, dtype=np.float32)
        # Pack up to 81 cells (beginner); if larger, truncate.
        n_cells = min(81, g.width * g.height)
        for i in range(n_cells):
            s = g.state[i]
            adj = g.adjacency[i]
            if s == HIDDEN:
                v = -1.0
            elif s == FLAGGED:
                v = 0.9
            elif s == REVEALED:
                if adj == MINE:
                    v = 1.0
                else:
                    v = adj / 10.0
            else:
                v = -0.5
            vec[i] = v
        mc = max(1, g.mine_count)
        vec[81] = g.mines_remaining / mc
        vec[82] = g.flags_placed / mc
        vec[83] = g.cells_revealed / max(1, g.safe_cells)
        gs = {GameState.READY: 0.0, GameState.PLAYING: 0.33,
              GameState.WON: 0.66, GameState.LOST: 1.0}[g.game_state]
        vec[84] = gs
        vec[85] = 0.0
        vec[86] = 0.0
        return vec

    def game_reward(self) -> float:
        g = self.game
        cur_revealed = g.cells_revealed
        delta = cur_revealed - self._prev_revealed
        reward = float(delta)  # +1 per safe tile newly revealed
        if g.game_state == GameState.LOST and not self._prev_over:
            reward -= 10.0
            self._prev_over = True
        elif g.game_state == GameState.WON and not self._prev_over:
            reward += 5.0
            self._prev_over = True
        self._prev_revealed = cur_revealed
        return reward

    def is_terminal(self) -> bool:
        return bool(self.game.is_over)


def state_vector_len() -> int:
    return STATE_DIM
