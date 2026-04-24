"""Rules text for the Rules modal."""

RULES_TEXT = """\
MINESWEEPER
===========

Reveal every safe cell without stepping on a mine.

Object
------
Flag every mine and reveal every safe cell.

Rules
-----
Click (reveal) a cell to turn it over.
  - If it's a mine — you lose.
  - If it's a number — that's how many mines touch that cell
    (including diagonals).
  - If it's blank — the board flood-fills until it hits numbered
    neighbors.

Flag a cell you're confident is a mine. Flagged cells can't be
accidentally revealed.

Chord on a revealed number — reveal all unflagged neighbors at once
(only if the count of flagged neighbors equals the number). This is
the fastest way to clear a large board.

Difficulty
----------
  Beginner       9 × 9    10 mines
  Intermediate  16 × 16   40 mines
  Expert        30 × 16   99 mines

Controls summary
----------------
  ← → ↑ ↓    Move cursor
  Space      Reveal
  f          Flag / unflag
  c          Chord (reveal all unflagged around a satisfied number)
  n          New game
  d          Difficulty picker
  r          Rules
  m          Music toggle
  ?          Help
  q          Quit
"""


def rules_text() -> str:
    return RULES_TEXT
