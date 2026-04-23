"""Visual tables for Minesweeper cells.

Follows the simcity-tui pattern: pre-parse `rich.style.Style` objects at
import time so `render_line` is not re-parsing strings per cell on every
paint.

Classic Microsoft Minesweeper digit palette:
    1 = blue, 2 = green, 3 = red, 4 = dark blue, 5 = maroon,
    6 = teal, 7 = black (rendered as near-black, unreadable on our dark
    bg → we use bright grey instead), 8 = grey.
"""

from __future__ import annotations

from rich.style import Style

# -------- digit palette (revealed-cell foregrounds) --------
# MS-classic colors, retuned for dark terminal backgrounds.
_DIGIT_FG: dict[int, str] = {
    0: "#808080",          # should never be rendered as a digit; safe fallback
    1: "rgb(80,160,255)",  # bright blue
    2: "rgb(80,220,110)",  # green
    3: "rgb(240,80,80)",   # red
    4: "rgb(160,100,220)", # purple / navy reinterpreted for dark bg
    5: "rgb(230,140,60)",  # maroon → orange (readable on dark)
    6: "rgb(80,200,210)",  # teal
    7: "rgb(220,220,220)", # near-white (MS uses near-black → invisible here)
    8: "rgb(180,180,180)", # grey
}

# Revealed cell backgrounds — two shades for a subtle checkerboard so the
# grid reads as a painted canvas instead of a wall of same-colored text.
# Keyed by (x + y) & 1 in the renderer.
_REVEALED_BG = ("#1a1a1c", "#141416")

# Covered ("unrevealed") tile: slightly brighter for contrast. Two-tone
# checkerboard again.
_COVERED_BG = ("#2c2c30", "#26262a")

# Cursor highlight: a warm yellow border. We overlay it via reverse on top
# of the underlying bg so the cursor reads through any state.
CURSOR_BG = "#3a2e12"
CURSOR_FG = "rgb(255,220,120)"

# Exploded mine — the one the player actually clicked. Loud red bg so it
# stands out from the other reveal-at-loss mines.
EXPLODED_BG = "rgb(140,20,20)"
MINE_BG_NORMAL = "#1a0e0e"

# Flagged / question-mark tile foregrounds.
FLAG_FG = "rgb(240,80,80)"     # red flag
QUESTION_FG = "rgb(240,220,80)" # yellow "?"
MINE_FG = "rgb(250,220,120)"    # ochre mine icon

# -------- glyphs --------
GLYPH_COVERED = "·"   # middle-dot; reads as "something hidden here"
GLYPH_FLAG = "⚑"     # U+2691 BLACK FLAG (1-cell wide)
GLYPH_QUESTION = "?"
GLYPH_MINE = "✸"     # U+2738 HEAVY EIGHT POINTED RAYED ASTERISK
GLYPH_EXPLOSION = "✹" # U+2739 — slightly bigger spikier
GLYPH_EMPTY = " "     # revealed, 0 adjacent — just bg
GLYPH_WRONG_FLAG = "✗"  # red X over a flag cell that wasn't a mine (post-loss)


# -------- pre-parsed style cache --------
# Built lazily at import. Having these as real Style objects saves ~40%
# on render_line time.
_STYLE_CACHE: dict[tuple, Style] = {}


def _style(fg: str | None, bg: str, bold: bool = False) -> Style:
    key = (fg, bg, bold)
    s = _STYLE_CACHE.get(key)
    if s is None:
        s = Style(color=fg, bgcolor=bg, bold=bold)
        _STYLE_CACHE[key] = s
    return s


def covered_style(x: int, y: int, cursor: bool = False) -> Style:
    bg = CURSOR_BG if cursor else _COVERED_BG[(x + y) & 1]
    return _style(None, bg)


def flag_style(x: int, y: int, cursor: bool = False) -> Style:
    bg = CURSOR_BG if cursor else _COVERED_BG[(x + y) & 1]
    return _style(FLAG_FG, bg, bold=True)


def question_style(x: int, y: int, cursor: bool = False) -> Style:
    bg = CURSOR_BG if cursor else _COVERED_BG[(x + y) & 1]
    return _style(QUESTION_FG, bg, bold=True)


def revealed_digit_style(digit: int, x: int, y: int, cursor: bool = False) -> Style:
    bg = CURSOR_BG if cursor else _REVEALED_BG[(x + y) & 1]
    fg = _DIGIT_FG.get(digit, "#a0a0a0")
    return _style(fg, bg, bold=True)


def revealed_empty_style(x: int, y: int, cursor: bool = False) -> Style:
    bg = CURSOR_BG if cursor else _REVEALED_BG[(x + y) & 1]
    return _style(None, bg)


def mine_style(x: int, y: int, exploded: bool = False, cursor: bool = False) -> Style:
    if exploded:
        bg = EXPLODED_BG
    elif cursor:
        bg = CURSOR_BG
    else:
        bg = MINE_BG_NORMAL
    return _style(MINE_FG, bg, bold=True)


def wrong_flag_style(x: int, y: int, cursor: bool = False) -> Style:
    bg = CURSOR_BG if cursor else _COVERED_BG[(x + y) & 1]
    # Orange-red, conveys "you flagged this but it wasn't a mine".
    return _style("rgb(240,120,90)", bg, bold=True)
