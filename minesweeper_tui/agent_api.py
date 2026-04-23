"""Agent REST API for minesweeper-tui.

Exposes the engine over HTTP so an external agent (LLM, RL, tests) can
drive the game. Mirrors the skill's Phase C recipe + the micropolis REST
schema adapted to Minesweeper.

    POST /new_game   {difficulty, seed?, width?, height?, mines?}
    POST /reveal     {x, y}
    POST /flag       {x, y}
    POST /chord      {x, y}
    GET  /state                → state_snapshot()
    GET  /healthz              → {"ok": true}

All state-mutating responses include the post-action `state` so the agent
can single-turn. Everything is JSON; errors return 4xx with `{"error": ...}`.

Design notes (from the skill's gotcha catalogue):
  - runs on the same asyncio loop as the Textual App via a background task;
  - does NOT touch the UI directly — UI layers a 1 Hz redraw on top that
    will re-read the mutated engine state normally;
  - in `--headless` mode the TUI is skipped entirely so agents can play
    solo without a terminal.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

try:
    from aiohttp import web
except ImportError as e:  # pragma: no cover - handled by caller
    raise SystemExit(
        "aiohttp is required for the agent API. "
        "Install with: pip install -e '.[agent]'"
    ) from e

from .engine import (
    ActionResult,
    Difficulty,
    Game,
    new_game,
)


_DIFF_MAP = {
    "beginner": Difficulty.BEGINNER,
    "intermediate": Difficulty.INTERMEDIATE,
    "expert": Difficulty.EXPERT,
    "custom": Difficulty.CUSTOM,
}


class AgentAPI:
    """Holds a `Game` reference that the API can mutate; also allows the
    owning App to swap in a new Game (restart / difficulty change) via
    `set_game`. A callback (`on_change`) is fired after any state-mutating
    route so the TUI can refresh its panels immediately."""

    def __init__(self, game: Game, on_change: Callable[[], None] | None = None) -> None:
        self._game = game
        self._on_change = on_change

    @property
    def game(self) -> Game:
        return self._game

    def set_game(self, game: Game) -> None:
        self._game = game

    def _notify(self) -> None:
        if self._on_change is not None:
            try:
                self._on_change()
            except Exception:
                # Never let a UI refresh failure take down the API.
                pass

    # ---------- request handlers ----------

    async def _state(self, _req: web.Request) -> web.Response:
        return web.json_response(self._game.state_snapshot())

    async def _healthz(self, _req: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def _new_game(self, req: web.Request) -> web.Response:
        try:
            data = await req.json()
        except (ValueError, Exception):
            data = {}
        diff_name = str(data.get("difficulty", "beginner")).lower()
        diff = _DIFF_MAP.get(diff_name)
        if diff is None:
            return web.json_response(
                {"error": f"unknown difficulty: {diff_name!r}"}, status=400,
            )
        try:
            g = new_game(
                diff,
                width=data.get("width"),
                height=data.get("height"),
                mines=data.get("mines"),
                seed=data.get("seed"),
            )
        except (ValueError, TypeError) as e:
            return web.json_response({"error": str(e)}, status=400)
        self._game = g
        self._notify()
        return web.json_response(
            {"ok": True, "state": g.state_snapshot()},
        )

    async def _action(self, req: web.Request, fn_name: str) -> web.Response:
        try:
            data = await req.json()
        except (ValueError, Exception):
            return web.json_response({"error": "invalid JSON"}, status=400)
        try:
            x = int(data["x"])
            y = int(data["y"])
        except (KeyError, TypeError, ValueError):
            return web.json_response(
                {"error": "x and y are required integers"}, status=400,
            )
        fn = getattr(self._game, fn_name)
        result: ActionResult = fn(x, y)
        self._notify()
        return web.json_response(
            {
                "ok": result != ActionResult.INVALID,
                "result": result.value,
                "state": self._game.state_snapshot(),
            },
            status=200 if result != ActionResult.INVALID else 400,
        )

    async def _reveal(self, req: web.Request) -> web.Response:
        return await self._action(req, "reveal")

    async def _flag(self, req: web.Request) -> web.Response:
        return await self._action(req, "flag")

    async def _chord(self, req: web.Request) -> web.Response:
        return await self._action(req, "chord")

    # ---------- app wiring ----------

    def make_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/state", self._state)
        app.router.add_get("/healthz", self._healthz)
        app.router.add_post("/new_game", self._new_game)
        app.router.add_post("/reveal", self._reveal)
        app.router.add_post("/flag", self._flag)
        app.router.add_post("/chord", self._chord)
        return app


async def start_server(
    api: AgentAPI, host: str = "127.0.0.1", port: int = 8765,
) -> tuple[web.AppRunner, int]:
    """Start the HTTP server on `host:port`. Returns the runner and the
    actual port bound (useful when `port=0` is passed by tests)."""
    aio_app = api.make_app()
    runner = web.AppRunner(aio_app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    # Resolve bound port (port=0 → kernel picks).
    bound_port = port
    for sock in getattr(site, "_server", None).sockets if site._server else []:
        bound_port = sock.getsockname()[1]
        break
    return runner, bound_port


async def run_headless(
    difficulty: Difficulty = Difficulty.BEGINNER,
    *,
    width: int | None = None,
    height: int | None = None,
    mines: int | None = None,
    seed: int | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Headless server loop — no TUI. Serves until cancelled (Ctrl-C)."""
    g = new_game(difficulty, width=width, height=height, mines=mines, seed=seed)
    api = AgentAPI(g)
    runner, bound = await start_server(api, host=host, port=port)
    print(f"minesweeper-tui agent API listening on http://{host}:{bound}")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await runner.cleanup()
