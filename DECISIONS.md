# Minesweeper TUI — Design Decisions

## Engine: pure-Python, no SWIG binding

The `/tui-game-build` skill's "vendor native engine" stage typically wraps a
C/C++ engine via SWIG. **For Minesweeper this is the wrong tradeoff.**

### Why not vendor bsd-games `mines` via SWIG

- bsd-games `mines` is a self-contained **curses program**, not a library.
  It owns the input loop, the screen, and the rendering. There's no stable
  C API to call from Python — "just the logic" would require extracting +
  refactoring several hundred LOC of C, for ~150 lines of game logic that
  trivially re-express in Python.
- The state machine (board with mines + adjacency counts, reveal + flag
  operations, flood-fill clear on zero-neighbor cells, win/loss detection)
  is textbook and has zero performance concerns — an 80×80 board with 30%
  mines still renders in microseconds.
- Textual's async model collaborates badly with foreign input loops; a
  pure-Python engine runs naturally in the asyncio event loop.

### What we did vendor

- `engine/reference/` — a stripped reference implementation (pure-Python
  `MinesweeperEngine`) living alongside the package that mirrors what a
  vendored C engine would provide: `new_game(w, h, mines, seed)`,
  `reveal(x, y)`, `flag(x, y)`, `chord(x, y)`, `state_snapshot()`.
- Difficulty conventions borrowed from the classic Microsoft + bsd-games
  canon:
  - Beginner:     9×9, 10 mines
  - Intermediate: 16×16, 40 mines
  - Expert:       30×16, 99 mines
- Safe-first-click guarantee (mines relocated if the first clicked cell
  contains one — both the first cell AND its 8 neighbours are
  mine-free, matching modern Windows Minesweeper).
- Board coordinates use `(x, y)` throughout where `x` is column, `y` is
  row — matches the simcity-tui convention so the QA harness idioms
  port directly.

## Reference project layout mirrored from simcity-tui

- `minesweeper.py` — argparse entry point → `run()`
- `minesweeper_tui/engine.py` — pure-Python engine (no SWIG)
- `minesweeper_tui/tiles.py` — cell-state → (glyph, style) tables
- `minesweeper_tui/app.py` — Textual `App`, `BoardView`, panels
- `minesweeper_tui/screens.py` — modal screens (Help, Difficulty, Custom,
  WinLoss, Legend, HighScores, Confirm)
- `minesweeper_tui/sounds.py` — opt-in synth SFX (same pattern as
  simcity-tui, no vendor WAVs — tones only)
- `minesweeper_tui/tui.tcss` — Textual stylesheet
- `tests/qa.py` — Pilot-driven scenarios (headless)
- `tests/perf.py` — hot-path benchmarks
- `tests/sound_test.py` — "I can't hear anything" diagnostic

## Polish phases followed from the skill

- **A — UI beauty:** per-digit color palette for neighbor numbers
  (classic MS palette: 1=blue, 2=green, 3=red, 4=navy, 5=maroon,
  6=teal, 7=black, 8=grey), distinct styles for covered/revealed/flagged,
  mine-explosion cell background, cursor highlight, smiley-face header.
- **B — Submenus:** Help, Difficulty picker, Custom board dialog,
  WinLoss result screen, Legend, HighScores. `+`/`-` for edits in
  modals (priority-binding safe).
- **C — Agent REST API:** `aiohttp` server; POST `/reveal {x,y}`,
  `/flag {x,y}`, `/chord {x,y}`, `/new_game {difficulty|w,h,mines}`,
  GET `/state`. Headless mode lets a remote agent play alone.
- **D — Sound:** synth-only tones for reveal, flag, chord, explosion,
  win-chime. Debounced per-name.
- **E — Polish:** HighScores persistence (JSON in user data dir),
  settings persistence, custom difficulty with sane limits.
- **F — Animation:** smiley-face timer pulse, cursor blink, post-loss
  mine "cascade" reveal sequence.

## Game features shipped

- Difficulty presets: Beginner / Intermediate / Expert, plus custom.
- Mouse + keyboard input. Mouse: left=reveal, right=flag, middle=chord.
  Keyboard: arrows to move, space/enter to reveal, `f` to flag, `c` to
  chord, `n` to start a new game, `d` to pick difficulty.
- Flag/reveal/chord ops with win/loss detection.
- Timer (seconds) and mines-remaining counter.
- Safe-first-click guarantee.
- HighScores persistence per difficulty.

## Not shipped (explicit non-goals for v0.1)

- **Guaranteed no-guess boards.** Generation of solvable-without-guessing
  boards is a surprisingly deep subproblem (requires a constraint solver
  to verify). Noted in README as a future enhancement.
- **LLM advisor.** The simcity-tui Phase G applies poorly here —
  Minesweeper advice is mechanical ("chord that 1 with two unrevealed
  neighbours and one flag"), not strategic. A built-in solver hint
  system is a better fit, deferred.
