"""Performance benchmark for minesweeper-tui hot paths.

Times:
    - full-board render_line loop   (what Textual does per frame)
    - single reveal flood-fill       (largest single action)
    - state_snapshot construction    (REST API / agent hot path)
    - full win sweep                  (stress: reveal every safe cell)

No optimization target numbers — this is a baseline for the robustness
pass to measure against.
"""

from __future__ import annotations

import time
from minesweeper_tui.engine import Difficulty, MINE, new_game


def bench_render_loop(label: str, difficulty: Difficulty, iters: int = 50) -> None:
    from minesweeper_tui.app import MinesweeperApp

    async def _run():
        app = MinesweeperApp(difficulty, seed=42)
        async with app.run_test(size=(180, 50)) as pilot:
            await pilot.pause()
            # Reveal something so the board has mixed cell states.
            await pilot.press("space")
            await pilot.pause()
            board = app.board_view
            t0 = time.perf_counter()
            for _ in range(iters):
                for y in range(app.game.height):
                    board.render_line(y)
            elapsed = time.perf_counter() - t0
            avg_ms = 1000 * elapsed / iters
            print(f"  render_loop {label:<14} {iters}× "
                  f"H={app.game.height}  →  {avg_ms:.2f} ms/frame "
                  f"({1000*elapsed:.0f} ms total)")

    import asyncio
    asyncio.run(_run())


def bench_flood_fill(label: str, difficulty: Difficulty, iters: int = 200) -> None:
    elapsed = 0.0
    for _ in range(iters):
        g = new_game(difficulty, seed=None)
        t0 = time.perf_counter()
        g.reveal(g.width // 2, g.height // 2)
        elapsed += time.perf_counter() - t0
    avg_us = 1_000_000 * elapsed / iters
    print(f"  first_reveal   {label:<14} {iters}×  →  {avg_us:.1f} µs/call")


def bench_full_sweep(label: str, difficulty: Difficulty, iters: int = 30) -> None:
    """Reveal every safe cell — models the win-condition stress case."""
    elapsed = 0.0
    cells = 0
    for _ in range(iters):
        g = new_game(difficulty, seed=None)
        g.reveal(g.width // 2, g.height // 2)
        t0 = time.perf_counter()
        for y in range(g.height):
            for x in range(g.width):
                if g.adjacency[y * g.width + x] != MINE:
                    g.reveal(x, y)
        elapsed += time.perf_counter() - t0
        cells = g.safe_cells
    avg_ms = 1000 * elapsed / iters
    print(f"  full_sweep     {label:<14} {iters}× ({cells} safe cells) "
          f" →  {avg_ms:.2f} ms/run")


def bench_snapshot(label: str, difficulty: Difficulty, iters: int = 500) -> None:
    g = new_game(difficulty, seed=42)
    g.reveal(g.width // 2, g.height // 2)
    t0 = time.perf_counter()
    for _ in range(iters):
        g.state_snapshot()
    elapsed = time.perf_counter() - t0
    avg_us = 1_000_000 * elapsed / iters
    print(f"  snapshot       {label:<14} {iters}×  →  {avg_us:.1f} µs/call")


def main() -> None:
    print("Minesweeper TUI — perf baseline\n")
    print("Render loop (full board render, as Textual does per frame):")
    for label, diff in (("beginner", Difficulty.BEGINNER),
                         ("intermediate", Difficulty.INTERMEDIATE),
                         ("expert", Difficulty.EXPERT)):
        bench_render_loop(label, diff, iters=20)
    print("\nEngine operations:")
    for label, diff in (("beginner", Difficulty.BEGINNER),
                         ("intermediate", Difficulty.INTERMEDIATE),
                         ("expert", Difficulty.EXPERT)):
        bench_flood_fill(label, diff, iters=100)
    for label, diff in (("beginner", Difficulty.BEGINNER),
                         ("intermediate", Difficulty.INTERMEDIATE),
                         ("expert", Difficulty.EXPERT)):
        bench_full_sweep(label, diff, iters=20)
    for label, diff in (("beginner", Difficulty.BEGINNER),
                         ("intermediate", Difficulty.INTERMEDIATE),
                         ("expert", Difficulty.EXPERT)):
        bench_snapshot(label, diff, iters=200)


if __name__ == "__main__":
    main()
