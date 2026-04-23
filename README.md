# Minesweeper TUI

Terminal-native Minesweeper. Python + Textual. Mouse and keyboard. Built
following the `/tui-game-build` skill playbook, mirroring the
`simcity-tui` reference project's layout.

## Quick start

```bash
make all        # create venv + install
make run        # launch at Beginner difficulty
# or:
.venv/bin/python minesweeper.py intermediate
.venv/bin/python minesweeper.py expert
.venv/bin/python minesweeper.py custom --width 20 --height 12 --mines 50
```

## Controls

| Key               | Action                                      |
|-------------------|---------------------------------------------|
| Arrows / Home/End / PgUp/PgDn | move cursor                         |
| Space / Enter     | reveal cell                                  |
| `f`               | toggle flag                                  |
| `c`               | chord (reveal safe neighbours of a number)   |
| `n`               | new game (same difficulty)                   |
| `d`               | pick difficulty                              |
| `?`               | help                                         |
| `l`               | legend                                       |
| `h`               | high scores                                  |
| `q`               | quit                                         |
| Left click        | reveal                                       |
| Right click       | flag                                         |
| Middle click      | chord                                        |

### Flags

| Flag                 | Effect                                          |
|----------------------|-------------------------------------------------|
| `--sound`            | enable synth SFX (reveal / flag / chord / …)    |
| `--seed N`           | deterministic board (for repro / testing)       |
| `--agent`            | run the REST agent API alongside the TUI        |
| `--headless`         | agent API only, no TUI                          |
| `--host H --port P`  | override API bind address (default 127.0.0.1:8765) |

## Features

- Classic Beginner (9×9/10), Intermediate (16×16/40), Expert (30×16/99)
  presets plus custom boards (4..80 × 4..40).
- Mouse + keyboard input with flag/reveal/chord operations.
- **Safe first click** — first reveal is never a mine, and its 8
  neighbours are also cleared so flood-fill always kicks off.
- Flood-fill on 0-adjacency cells.
- Win/loss detection with end-game modal + post-loss "reveal all mines"
  board view with exploded-cell highlight and wrong-flag `✗` markers.
- Elapsed-time + mines-remaining counters.
- High scores persisted to `~/.local/share/minesweeper-tui/highscores.json`.
- Opt-in synth SFX (`--sound`). Silent-on-failure.
- Deterministic boards with `--seed N` for reproducible puzzles / testing.

## Agent REST API

Minesweeper ships an opt-in HTTP API for external agents (LLMs, RL gyms,
integration tests). Start alongside the TUI with `--agent`, or standalone
with `--headless`:

```bash
.venv/bin/python minesweeper.py beginner --agent           # TUI + API
.venv/bin/python minesweeper.py expert  --headless         # API only
```

| Route              | Method | Body                                       | Returns                                |
|--------------------|--------|--------------------------------------------|----------------------------------------|
| `/healthz`         | GET    | –                                          | `{"ok": true}`                         |
| `/state`           | GET    | –                                          | full `state_snapshot()`                |
| `/reveal`          | POST   | `{x, y}`                                   | `{ok, result, state}`                  |
| `/flag`            | POST   | `{x, y}`                                   | `{ok, result, state}`                  |
| `/chord`           | POST   | `{x, y}`                                   | `{ok, result, state}`                  |
| `/new_game`        | POST   | `{difficulty, seed?, width?, height?, mines?}` | `{ok, state}`                      |

The state snapshot masks `adj` on hidden cells so a naïve agent can't
peek at mine locations.

## Testing

```bash
make test                 # full QA: 23 TUI scenarios + 11 API + perf
make test-api             # agent-API subset only
make test-only PAT=flag   # TUI subset filtered by substring
make test-sound           # 2-second audio pipeline diagnostic
```

Every TUI scenario writes a PASS/FAIL SVG screenshot to `tests/out/` for
visual diffing across commits.

## Requirements

- Python 3.10+
- Linux / macOS terminal with 256-color + mouse-tracking support
  (any modern emulator — xterm, kitty, alacritty, iTerm2, Ghostty, etc.)

## Design notes

See [`DECISIONS.md`](./DECISIONS.md) for why we ship a pure-Python
engine (no SWIG binding), the difficulty conventions, and what's
deliberately deferred.

## License

MIT (this is an original implementation; no vendored engine, see
`DECISIONS.md`).
