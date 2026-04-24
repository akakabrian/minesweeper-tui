"""Entry point — `python minesweeper.py [difficulty]`.

  python minesweeper.py                       # beginner
  python minesweeper.py intermediate
  python minesweeper.py expert
  python minesweeper.py custom --width 20 --height 12 --mines 50
  python minesweeper.py beginner --sound      # enable SFX
  python minesweeper.py beginner --seed 42    # deterministic board
  python minesweeper.py beginner --agent      # TUI + REST API on :8765
  python minesweeper.py beginner --headless   # server only, no TUI
"""

from __future__ import annotations

import argparse

from minesweeper_tui.app import run


def main() -> None:
    p = argparse.ArgumentParser(prog="minesweeper-tui")
    p.add_argument("difficulty", nargs="?", default="beginner",
                   choices=["beginner", "intermediate", "expert", "custom"],
                   help="difficulty preset (default: beginner)")
    p.add_argument("--width",  type=int, help="custom board width (4..80)")
    p.add_argument("--height", type=int, help="custom board height (4..40)")
    p.add_argument("--mines",  type=int, help="custom mine count")
    p.add_argument("--seed",   type=int, help="RNG seed (for reproducible boards)")
    p.add_argument("--sound", action="store_true",
                   help="enable synth SFX (default off)")
    p.add_argument("--music", action="store_true",
                   help="start background music on launch (toggle in-app with `m`)")
    p.add_argument("--agent", action="store_true",
                   help="expose the REST agent API alongside the TUI")
    p.add_argument("--headless", action="store_true",
                   help="run the agent API only, no TUI")
    p.add_argument("--host", default="127.0.0.1",
                   help="agent API host (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=8765,
                   help="agent API port (default 8765, 0=auto)")
    args = p.parse_args()
    if args.headless:
        # Pure server mode — no Textual App, just the engine + aiohttp loop.
        import asyncio

        from minesweeper_tui.agent_api import run_headless
        from minesweeper_tui.engine import Difficulty

        diff = {
            "beginner": Difficulty.BEGINNER,
            "intermediate": Difficulty.INTERMEDIATE,
            "expert": Difficulty.EXPERT,
            "custom": Difficulty.CUSTOM,
        }[args.difficulty]
        asyncio.run(run_headless(
            diff, width=args.width, height=args.height, mines=args.mines,
            seed=args.seed, host=args.host, port=args.port,
        ))
        return
    run(args.difficulty, width=args.width, height=args.height,
        mines=args.mines, seed=args.seed, sound=args.sound,
        music=args.music, agent=args.agent, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
