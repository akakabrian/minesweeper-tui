"""Agent REST API QA for minesweeper-tui.

Spins up a fresh AgentAPI on an ephemeral port, hits every endpoint, asserts
response shape + state transitions. Runs in isolation from the Pilot-based
TUI QA in `tests.qa`.

    python -m tests.api_qa
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from dataclasses import dataclass
from typing import Awaitable, Callable

from aiohttp import ClientSession

from minesweeper_tui.agent_api import AgentAPI, start_server
from minesweeper_tui.engine import Difficulty, new_game


@dataclass
class Scenario:
    name: str
    fn: Callable[[ClientSession, str], Awaitable[None]]


def _url(base: str, path: str) -> str:
    return f"{base}{path}"


# ---------- scenarios ----------

async def s_healthz_ok(session: ClientSession, base: str) -> None:
    async with session.get(_url(base, "/healthz")) as r:
        assert r.status == 200, r.status
        body = await r.json()
        assert body == {"ok": True}, body


async def s_state_shape(session: ClientSession, base: str) -> None:
    async with session.get(_url(base, "/state")) as r:
        assert r.status == 200
        body = await r.json()
    for k in ("width", "height", "mine_count", "game_state", "cells",
              "mines_remaining", "flags_placed"):
        assert k in body, f"missing key {k!r}"
    assert len(body["cells"]) == body["height"]
    assert len(body["cells"][0]) == body["width"]
    # Before any reveal everything is hidden + adj masked.
    for row in body["cells"]:
        for cell in row:
            assert cell["state"] == "hidden"
            assert cell["adj"] is None


async def s_reveal_happy_path(session: ClientSession, base: str) -> None:
    async with session.post(_url(base, "/reveal"), json={"x": 4, "y": 4}) as r:
        assert r.status == 200
        body = await r.json()
    assert body["ok"] is True, body
    assert body["result"] in ("ok", "win"), body["result"]
    assert body["state"]["mines_seeded"] is True
    assert body["state"]["cells_revealed"] >= 1


async def s_reveal_bad_payload(session: ClientSession, base: str) -> None:
    async with session.post(_url(base, "/reveal"), json={"x": "nope"}) as r:
        assert r.status == 400, r.status
        body = await r.json()
        assert "error" in body


async def s_reveal_out_of_bounds_marks_invalid(
    session: ClientSession, base: str,
) -> None:
    async with session.post(
        _url(base, "/reveal"), json={"x": 999, "y": 999},
    ) as r:
        assert r.status == 400
        body = await r.json()
        assert body["result"] == "invalid", body


async def s_flag_toggles(session: ClientSession, base: str) -> None:
    # Flag a hidden cell, verify flag count, then unflag.
    async with session.post(_url(base, "/flag"), json={"x": 0, "y": 0}) as r:
        body = await r.json()
    assert body["state"]["flags_placed"] == 1
    async with session.post(_url(base, "/flag"), json={"x": 0, "y": 0}) as r:
        body = await r.json()
    assert body["state"]["flags_placed"] == 0


async def s_new_game_resets(session: ClientSession, base: str) -> None:
    # Reveal a cell (seeds mines).
    async with session.post(_url(base, "/reveal"), json={"x": 4, "y": 4}) as r:
        body = await r.json()
    assert body["state"]["mines_seeded"] is True
    # Now start a fresh beginner game.
    async with session.post(
        _url(base, "/new_game"), json={"difficulty": "beginner", "seed": 42},
    ) as r:
        assert r.status == 200
        body = await r.json()
    assert body["ok"] is True
    assert body["state"]["mines_seeded"] is False
    assert body["state"]["cells_revealed"] == 0


async def s_new_game_expert_shape(session: ClientSession, base: str) -> None:
    async with session.post(
        _url(base, "/new_game"), json={"difficulty": "expert"},
    ) as r:
        body = await r.json()
    st = body["state"]
    assert st["width"] == 30 and st["height"] == 16 and st["mine_count"] == 99


async def s_new_game_custom(session: ClientSession, base: str) -> None:
    async with session.post(
        _url(base, "/new_game"),
        json={"difficulty": "custom", "width": 10, "height": 8, "mines": 12,
              "seed": 123},
    ) as r:
        assert r.status == 200
        body = await r.json()
    st = body["state"]
    assert st["width"] == 10 and st["height"] == 8 and st["mine_count"] == 12


async def s_new_game_unknown_difficulty(
    session: ClientSession, base: str,
) -> None:
    async with session.post(
        _url(base, "/new_game"), json={"difficulty": "impossible"},
    ) as r:
        assert r.status == 400
        body = await r.json()
        assert "error" in body


async def s_chord_wires_engine(session: ClientSession, base: str) -> None:
    # Simplest way to verify /chord is reachable and returns the schema:
    # call it on an unrevealed cell → NO_CHANGE. Any 200 with schema is
    # enough here; the logic itself is covered in tests.qa.
    async with session.post(_url(base, "/chord"), json={"x": 0, "y": 0}) as r:
        assert r.status == 200
        body = await r.json()
    assert "result" in body
    assert body["result"] in ("no_change", "ok", "mine", "win", "invalid")


# ---------- runner ----------

SCENARIOS: list[Scenario] = [
    Scenario("healthz_ok", s_healthz_ok),
    Scenario("state_shape", s_state_shape),
    Scenario("reveal_happy_path", s_reveal_happy_path),
    Scenario("reveal_bad_payload", s_reveal_bad_payload),
    Scenario("reveal_out_of_bounds_marks_invalid",
             s_reveal_out_of_bounds_marks_invalid),
    Scenario("flag_toggles", s_flag_toggles),
    Scenario("new_game_resets", s_new_game_resets),
    Scenario("new_game_expert_shape", s_new_game_expert_shape),
    Scenario("new_game_custom", s_new_game_custom),
    Scenario("new_game_unknown_difficulty", s_new_game_unknown_difficulty),
    Scenario("chord_wires_engine", s_chord_wires_engine),
]


async def run_scenario(scn: Scenario) -> tuple[str, bool, str]:
    # Fresh game + server on ephemeral port per scenario so there's no
    # cross-test state. seed=12345 lines up with tests.qa for determinism.
    game = new_game(Difficulty.BEGINNER, seed=12345)
    api = AgentAPI(game)
    runner, port = await start_server(api, host="127.0.0.1", port=0)
    base = f"http://127.0.0.1:{port}"
    try:
        async with ClientSession() as session:
            try:
                await scn.fn(session, base)
                return (scn.name, True, "")
            except AssertionError as e:
                return (scn.name, False, f"AssertionError: {e}")
            except Exception as e:
                return (scn.name, False,
                        f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
    finally:
        await runner.cleanup()


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
        print(f"  [{icon}] {name}"
              + (f"   -- {msg.splitlines()[0]}" if not ok else ""))
        if not ok:
            failures.append((name, msg))
    print()
    if failures:
        print(f"{len(failures)}/{len(selected)} failed:")
        for name, msg in failures:
            print(f"--- {name} ---\n{msg}\n")
        return len(failures)
    print(f"all {len(selected)} API scenarios passed")
    return 0


if __name__ == "__main__":
    patterns = sys.argv[1:]
    rc = asyncio.run(main(patterns))
    sys.exit(rc)
