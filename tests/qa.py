"""Headless QA driver for minesweeper-tui.

Runs each scenario in a fresh `MinesweeperApp` via `App.run_test()`, captures
an SVG screenshot on finish, and reports pass/fail. Exit code = # failures.

    python -m tests.qa                 # all scenarios
    python -m tests.qa cursor          # filter by substring
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from minesweeper_tui.app import MinesweeperApp
from minesweeper_tui.engine import (
    Difficulty,
    GameState,
    HIDDEN,
    REVEALED,
    FLAGGED,
    MINE,
)

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)


@dataclass
class Scenario:
    name: str
    fn: Callable[[MinesweeperApp, "object"], Awaitable[None]]


# ---------- helpers ----------

def first_safe_cell(app: MinesweeperApp) -> tuple[int, int]:
    """Pick a cell to click. Before seeding, any cell works — the engine
    guarantees the first click is safe."""
    return (app.game.width // 2, app.game.height // 2)


def first_mine_cell(app: MinesweeperApp) -> tuple[int, int] | None:
    g = app.game
    for y in range(g.height):
        for x in range(g.width):
            if g.adjacency[y * g.width + x] == MINE:
                return x, y
    return None


# ---------- scenarios ----------

async def s_mount_clean(app, pilot):
    """Widgets exist, no exceptions during mount."""
    assert app.board_view is not None
    assert app.status_panel is not None
    assert app.controls_panel is not None
    assert app.legend_panel is not None
    assert app.log_view is not None
    assert app.game is not None


async def s_cursor_starts_centered(app, pilot):
    """Cursor begins at (W/2, H/2) so a first-click flood fills nicely."""
    assert app.board_view.cursor_x == app.game.width // 2
    assert app.board_view.cursor_y == app.game.height // 2


async def s_cursor_moves(app, pilot):
    """Arrow keys move the cursor by 1 cell per press."""
    sx, sy = app.board_view.cursor_x, app.board_view.cursor_y
    await pilot.press("right", "right", "right")
    await pilot.press("down", "down")
    assert app.board_view.cursor_x == sx + 3, app.board_view.cursor_x
    assert app.board_view.cursor_y == sy + 2, app.board_view.cursor_y


async def s_cursor_clamps(app, pilot):
    """Cursor can't move past the board edges."""
    w, h = app.game.width, app.game.height
    for _ in range(w + 5):
        await pilot.press("left")
    assert app.board_view.cursor_x == 0
    for _ in range(h + 5):
        await pilot.press("up")
    assert app.board_view.cursor_y == 0


async def s_first_reveal_safe(app, pilot):
    """First reveal must be safe (3x3 guarantee) and trigger mine seeding."""
    cx, cy = app.board_view.cursor_x, app.board_view.cursor_y
    assert not app.game.mines_seeded
    await pilot.press("space")
    await pilot.pause()
    assert app.game.mines_seeded, "mines should be seeded after first reveal"
    idx = cy * app.game.width + cx
    assert app.game.state[idx] == REVEALED, "first-click cell should be revealed"
    assert app.game.adjacency[idx] != MINE, "first click must not hit a mine"


async def s_flood_fill_expands(app, pilot):
    """A reveal on a zero-adjacency cell flood-fills many cells."""
    await pilot.press("space")
    await pilot.pause()
    # Beginner is 9x9 = 81 cells, 10 mines = 71 safe cells.
    # With 3x3 safe zone guarantee around first click, the flood usually
    # reveals 15+ cells. Be loose — the exact count depends on the RNG.
    assert app.game.cells_revealed >= 9, (
        f"expected >= 9 cells revealed by flood-fill, got "
        f"{app.game.cells_revealed}"
    )


async def s_flag_toggles(app, pilot):
    """`f` places a flag; pressing `f` again removes it."""
    cx, cy = app.board_view.cursor_x, app.board_view.cursor_y
    await pilot.press("f")
    await pilot.pause()
    idx = cy * app.game.width + cx
    assert app.game.state[idx] == FLAGGED
    assert app.game.flags_placed == 1
    await pilot.press("f")
    await pilot.pause()
    assert app.game.state[idx] == HIDDEN
    assert app.game.flags_placed == 0


async def s_flag_blocks_reveal(app, pilot):
    """A flagged cell can't be revealed until unflagged."""
    cx, cy = app.board_view.cursor_x, app.board_view.cursor_y
    await pilot.press("f")  # flag
    await pilot.press("space")  # try to reveal
    await pilot.pause()
    idx = cy * app.game.width + cx
    assert app.game.state[idx] == FLAGGED, "flagged cell should remain flagged"


async def s_mine_click_loses(app, pilot):
    """Revealing a mine cell loses the game. We force-seed first."""
    # Seed mines first by revealing a safe cell.
    await pilot.press("space")
    await pilot.pause()
    mine = first_mine_cell(app)
    assert mine is not None, "no mine found after seeding"
    app.board_view.cursor_x, app.board_view.cursor_y = mine
    await pilot.pause()
    await pilot.press("space")
    await pilot.pause()
    assert app.game.game_state == GameState.LOST
    assert app.game.exploded_at == mine


async def s_win_on_last_safe_cell(app, pilot):
    """Revealing every safe cell wins the game."""
    # Seed mines.
    await pilot.press("space")
    await pilot.pause()
    # Reveal all non-mine cells programmatically (too slow via keystrokes
    # on larger boards). This tests the engine's win-detection path as
    # exercised through the app.
    g = app.game
    for y in range(g.height):
        for x in range(g.width):
            if g.adjacency[y * g.width + x] != MINE:
                g.reveal(x, y)
    assert g.game_state == GameState.WON, g.game_state
    assert g.cells_revealed == g.safe_cells


async def s_chord_reveals_neighbours(app, pilot):
    """Chord on a number with correct flag count reveals other neighbours."""
    await pilot.press("space")
    await pilot.pause()
    g = app.game
    # Find a revealed number cell whose unflagged neighbours include exactly
    # as many mines as its adjacency. For a just-flood-filled region, every
    # revealed number cell has all its mines still hidden — we flag all of
    # them, then chord.
    target = None
    for y in range(g.height):
        for x in range(g.width):
            idx = y * g.width + x
            if g.state[idx] != REVEALED or g.adjacency[idx] <= 0:
                continue
            mine_neighbours = []
            hidden_neighbours = []
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < g.width and 0 <= ny < g.height:
                        ni = ny * g.width + nx
                        if g.adjacency[ni] == MINE:
                            mine_neighbours.append((nx, ny))
                        elif g.state[ni] == HIDDEN:
                            hidden_neighbours.append((nx, ny))
            if mine_neighbours and hidden_neighbours:
                target = (x, y, mine_neighbours, hidden_neighbours)
                break
        if target:
            break
    assert target, "no chord candidate found"
    cx, cy, mines_n, hidden_n = target
    for mx, my in mines_n:
        g.flag(mx, my)
    revealed_before = g.cells_revealed
    # Use engine directly to avoid cursor-move keystroke overhead.
    g.chord(cx, cy)
    assert g.cells_revealed > revealed_before, (
        f"chord revealed nothing: {revealed_before} → {g.cells_revealed}"
    )


async def s_render_line_has_cursor_style(app, pilot):
    """The cursor cell's rendered segment uses the cursor-highlight bg."""
    board = app.board_view
    # Row of the board widget = world row (board fits in viewport in this
    # test terminal size). Each cell is 1 row tall so we render at cursor_y.
    cy = board.cursor_y
    strip = board.render_line(cy)
    segs = list(strip)  # public iteration — don't use ._segments
    # CURSOR_BG ends up rendered in `rich.style.Style.bgcolor` as a Color;
    # stringifying the style yields things like "not bold on #3a2e12".
    from minesweeper_tui.tiles import CURSOR_BG
    bg_marker = CURSOR_BG.lower()
    matched = [s for s in segs if bg_marker in str(s.style).lower()]
    assert matched, (
        f"cursor bg {CURSOR_BG} not present on row {cy}: "
        f"{[str(s.style) for s in segs[:10]]}"
    )


async def s_new_game_resets(app, pilot):
    """Pressing `n` starts a fresh board at the same difficulty."""
    await pilot.press("space")  # seed + reveal
    await pilot.pause()
    assert app.game.cells_revealed > 0
    await pilot.press("n")
    await pilot.pause()
    assert app.game.cells_revealed == 0
    assert not app.game.mines_seeded
    assert app.game.game_state == GameState.READY


async def s_modal_help_opens(app, pilot):
    """`?` opens HelpScreen; `escape` closes it."""
    await pilot.press("question_mark")
    await pilot.pause()
    assert app.screen.__class__.__name__ == "HelpScreen", \
        app.screen.__class__.__name__
    await pilot.press("escape")
    await pilot.pause()
    assert app.screen.__class__.__name__ == "Screen"


async def s_modal_legend_opens(app, pilot):
    """`l` opens LegendScreen."""
    await pilot.press("l")
    await pilot.pause()
    assert app.screen.__class__.__name__ == "LegendScreen"
    await pilot.press("escape")
    await pilot.pause()


async def s_modal_difficulty_opens(app, pilot):
    """`d` opens DifficultyScreen."""
    await pilot.press("d")
    await pilot.pause()
    assert app.screen.__class__.__name__ == "DifficultyScreen"
    await pilot.press("escape")
    await pilot.pause()


async def s_difficulty_switch_changes_board(app, pilot):
    """Picking 'Expert' from the menu swaps the board to 30x16."""
    await pilot.press("d")
    await pilot.pause()
    await pilot.press("3")  # Expert
    await pilot.pause()
    assert app.game.width == 30
    assert app.game.height == 16
    assert app.game.mine_count == 99


async def s_sound_disabled_is_noop(app, pilot):
    """Default-off sound: play() returns cleanly and spawns nothing."""
    assert app.sounds.enabled is False
    app.sounds.play("reveal")  # must not raise
    app.sounds.play("explosion")


async def s_mouse_click_reveals(app, pilot):
    """A left-click on the board reveals the clicked cell."""
    # Click somewhere on the board. The board is small (9x9 at CELL_W=3
    # = 27 cells wide), so an offset like (13, 4) is in bounds.
    await pilot.click("BoardView", offset=(13, 4))
    await pilot.pause()
    assert app.game.mines_seeded, "click should seed + reveal"
    assert app.game.cells_revealed > 0


async def s_state_snapshot_shape(app, pilot):
    """state_snapshot returns a JSON-safe dict with expected keys."""
    snap = app.game.state_snapshot()
    for k in ("width", "height", "mine_count", "game_state", "cells"):
        assert k in snap, f"missing key: {k}"
    assert len(snap["cells"]) == app.game.height
    assert len(snap["cells"][0]) == app.game.width
    # Covered cells must hide their adjacency over the API.
    g = app.game
    any_hidden = False
    for y in range(g.height):
        for x in range(g.width):
            if g.state[y * g.width + x] == HIDDEN:
                any_hidden = True
                assert snap["cells"][y][x]["adj"] is None, (
                    f"adj leaked for hidden cell ({x},{y})"
                )
    assert any_hidden  # sanity — a fresh game has hidden cells


async def s_unknown_cell_state_does_not_crash(app, pilot):
    """Robustness: a corrupt state value renders without crashing."""
    # Poison one cell with an invalid state value.
    g = app.game
    g.state[0] = 99
    try:
        strip = app.board_view.render_line(0)
        segs = list(strip)
        assert len(segs) > 0, "render_line returned no segments for corrupt state"
    finally:
        g.state[0] = HIDDEN  # restore so later scenarios (same runner) are clean


async def s_state_snapshot_before_reveal(app, pilot):
    """state_snapshot must work BEFORE any reveal (no-mount / early-API case)."""
    # Fresh game — no reveals yet.
    snap = app.game.state_snapshot()
    # All cells hidden, no adj leaked.
    for row in snap["cells"]:
        for cell in row:
            assert cell["state"] == "hidden"
            assert cell["adj"] is None


async def s_highscore_on_win(app, pilot):
    """Winning at Beginner records a highscore."""
    # Force-win by revealing all safe cells via the engine.
    g = app.game
    app.board_view.cursor_x = g.width // 2
    app.board_view.cursor_y = g.height // 2
    await pilot.press("space")
    await pilot.pause()
    for y in range(g.height):
        for x in range(g.width):
            if g.adjacency[y * g.width + x] != MINE:
                g.reveal(x, y)
    assert g.game_state == GameState.WON
    # Simulate the app win flow — app's _apply_action is what records
    # high scores, so we call it via a cursor-applied reveal on an
    # already-revealed cell (will return NO_CHANGE) just to trigger the
    # overall flow. Instead, directly invoke _on_game_over:
    app.start_time = app.start_time or (__import__("time").monotonic() - 5)
    app.end_time = __import__("time").monotonic()
    # Clear any pre-existing beginner record.
    app.highscores.pop("Beginner", None)
    app._on_game_over(won=True)
    await pilot.pause()
    assert "Beginner" in app.highscores
    assert app.highscores["Beginner"] > 0
    # Close the result screen that _on_game_over pushed.
    await pilot.press("escape")
    await pilot.pause()


# ---------- runner ----------

SCENARIOS: list[Scenario] = [
    Scenario("mount_clean", s_mount_clean),
    Scenario("cursor_starts_centered", s_cursor_starts_centered),
    Scenario("cursor_moves", s_cursor_moves),
    Scenario("cursor_clamps", s_cursor_clamps),
    Scenario("first_reveal_safe", s_first_reveal_safe),
    Scenario("flood_fill_expands", s_flood_fill_expands),
    Scenario("flag_toggles", s_flag_toggles),
    Scenario("flag_blocks_reveal", s_flag_blocks_reveal),
    Scenario("mine_click_loses", s_mine_click_loses),
    Scenario("win_on_last_safe_cell", s_win_on_last_safe_cell),
    Scenario("chord_reveals_neighbours", s_chord_reveals_neighbours),
    Scenario("render_line_has_cursor_style", s_render_line_has_cursor_style),
    Scenario("new_game_resets", s_new_game_resets),
    Scenario("modal_help_opens", s_modal_help_opens),
    Scenario("modal_legend_opens", s_modal_legend_opens),
    Scenario("modal_difficulty_opens", s_modal_difficulty_opens),
    Scenario("difficulty_switch_changes_board", s_difficulty_switch_changes_board),
    Scenario("sound_disabled_is_noop", s_sound_disabled_is_noop),
    Scenario("mouse_click_reveals", s_mouse_click_reveals),
    Scenario("state_snapshot_shape", s_state_snapshot_shape),
    Scenario("unknown_cell_state_does_not_crash", s_unknown_cell_state_does_not_crash),
    Scenario("state_snapshot_before_reveal", s_state_snapshot_before_reveal),
    Scenario("highscore_on_win", s_highscore_on_win),
]


async def run_scenario(scn: Scenario) -> tuple[str, bool, str]:
    # Deterministic seed so chord / flood scenarios are reproducible.
    app = MinesweeperApp(Difficulty.BEGINNER, seed=12345)
    try:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            try:
                await scn.fn(app, pilot)
                app.save_screenshot(str(OUT / f"{scn.name}.PASS.svg"))
                return (scn.name, True, "")
            except AssertionError as e:
                try:
                    app.save_screenshot(str(OUT / f"{scn.name}.FAIL.svg"))
                except Exception:
                    pass
                return (scn.name, False, f"AssertionError: {e}")
            except Exception as e:
                tb = traceback.format_exc()
                try:
                    app.save_screenshot(str(OUT / f"{scn.name}.ERROR.svg"))
                except Exception:
                    pass
                return (scn.name, False, f"{type(e).__name__}: {e}\n{tb}")
    except Exception as e:
        tb = traceback.format_exc()
        return (scn.name, False, f"launch error: {e}\n{tb}")


async def main(patterns: list[str]) -> int:
    selected = [s for s in SCENARIOS
                if not patterns or any(p in s.name for p in patterns)]
    if not selected:
        print(f"no scenarios match {patterns}")
        return 1
    failures: list[tuple[str, str]] = []
    for scn in selected:
        name, ok, msg = await run_scenario(scn)
        icon = "PASS" if ok else "FAIL"
        print(f"  [{icon}] {name}" + (f"   -- {msg.splitlines()[0]}" if not ok else ""))
        if not ok:
            failures.append((name, msg))
    print()
    if failures:
        print(f"{len(failures)}/{len(selected)} failed:")
        for name, msg in failures:
            print(f"--- {name} ---\n{msg}\n")
        return len(failures)
    print(f"all {len(selected)} scenarios passed")
    return 0


if __name__ == "__main__":
    patterns = sys.argv[1:]
    rc = asyncio.run(main(patterns))
    sys.exit(rc)
