"""Modal screens for Minesweeper TUI: Help, Difficulty picker, Custom size,
WinLoss, Legend, HighScores, Confirm-new-game.

Key rule (from the skill's gotcha catalog): priority App bindings beat modal
screens, so use non-conflicting keys inside dialogs. `+`/`-` instead of
arrows for adjustment, `enter` only on widgets that don't get filtered by
the App's Enter-to-reveal binding (we still allow escape to close).
"""

from __future__ import annotations

from typing import Callable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


HELP_TEXT = """
[bold #f0c080]MINESWEEPER — TUI[/]

[bold]Movement[/]
  Arrow keys          move cursor
  Home / End          jump to row start / end
  PgUp / PgDn         jump to top / bottom

[bold]Actions[/]
  Space / Enter       reveal cell under cursor
  f                   toggle flag
  c                   chord (reveal safe neighbours of a number
                      if flag-count matches it)
  n                   new game (same difficulty)
  d                   change difficulty
  Left-click          reveal        Right-click   flag
  Middle-click        chord         (mouse enabled by default)

[bold]Menus[/]
  ?                   this help
  l                   legend (symbol key)
  h                   high scores
  q                   quit

[bold]Rules[/]
  Reveal every safe cell to win. Stepping on a mine loses. Numbers show
  how many mines are in the 8 neighbours. A 0-cell flood-fills.
  [dim]First click is guaranteed safe (including all 8 neighbours).[/]
"""


LEGEND_TEXT = """
[bold #f0c080]LEGEND[/]

[dim #808080]·[/]    covered cell (unrevealed)
[bold rgb(240,80,80)]⚑[/]    flag (your guess: "mine here")
[bold rgb(250,220,120)]✸[/]    mine (revealed on loss)
[bold rgb(240,120,90)]✗[/]    wrong flag (post-loss — this was NOT a mine)
     [on rgb(140,20,20)]   [/]  the mine you clicked (exploded)

[bold]Digits[/] — count of mines in 8 neighbours
  [bold rgb(80,160,255)]1[/]  [bold rgb(80,220,110)]2[/]  [bold rgb(240,80,80)]3[/]  [bold rgb(160,100,220)]4[/]  [bold rgb(230,140,60)]5[/]  [bold rgb(80,200,210)]6[/]  [bold rgb(220,220,220)]7[/]  [bold rgb(180,180,180)]8[/]

[dim]A revealed empty cell with no digit means 0 neighbours — its
8 neighbours were auto-revealed by flood-fill.[/]
"""


class HelpScreen(ModalScreen):
    BINDINGS = [Binding("escape,q,question_mark", "app.pop_screen", "close")]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(HELP_TEXT, id="help-body"),
            id="help-container",
        )


class LegendScreen(ModalScreen):
    BINDINGS = [Binding("escape,q,l", "app.pop_screen", "close")]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(LEGEND_TEXT, id="legend-body"),
            id="legend-container",
        )


DIFFICULTIES = [
    ("Beginner",     9,  9,  10),
    ("Intermediate", 16, 16, 40),
    ("Expert",       30, 16, 99),
    ("Custom…",      0,  0,  0),
]


class DifficultyScreen(ModalScreen):
    """Pick a difficulty. Keys 1/2/3/4 select; enter confirms (no-op on
    Custom — that one pops CustomScreen instead). Escape cancels.

    Uses number keys (not arrows) to avoid the priority-binding trap."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "cancel"),
        Binding("1", "pick(0)", show=False),
        Binding("2", "pick(1)", show=False),
        Binding("3", "pick(2)", show=False),
        Binding("4", "pick(3)", show=False),
    ]

    def __init__(self, on_pick: Callable[[str, int, int, int], None]) -> None:
        super().__init__()
        self.on_pick = on_pick

    def compose(self) -> ComposeResult:
        lines = ["[bold #f0c080]NEW GAME — DIFFICULTY[/]", ""]
        for i, (name, w, h, m) in enumerate(DIFFICULTIES, start=1):
            if w == 0:
                lines.append(f"  [bold]{i}[/]  {name}")
            else:
                lines.append(f"  [bold]{i}[/]  {name:<14} {w}×{h}  {m} mines")
        lines.append("")
        lines.append("[dim]Press a number to start. Esc cancels.[/]")
        yield Vertical(
            Static("\n".join(lines), id="diff-body"),
            id="diff-container",
        )

    def action_pick(self, idx: int) -> None:
        name, w, h, m = DIFFICULTIES[idx]
        if name == "Custom…":
            self.app.pop_screen()
            self.app.push_screen(CustomScreen(self.on_pick))
            return
        self.on_pick(name, w, h, m)
        self.app.pop_screen()


class CustomScreen(ModalScreen):
    """Custom dimensions with +/- adjustment. Width, height, mines.
    Tab cycles the edited field. Enter confirms. Escape cancels."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "cancel"),
        Binding("plus,equals_sign", "bump(+1)", show=False),
        Binding("minus", "bump(-1)", show=False),
        Binding("greater_than_sign", "bump(+10)", show=False),
        Binding("less_than_sign", "bump(-10)", show=False),
        Binding("tab", "cycle", show=False),
        Binding("enter", "confirm", show=False),
    ]

    FIELDS = ["width", "height", "mines"]

    def __init__(self, on_pick: Callable[[str, int, int, int], None]) -> None:
        super().__init__()
        self.on_pick = on_pick
        self.width_val = 20
        self.height_val = 12
        self.mines_val = 50
        self.field = 0
        self._body: Static | None = None

    def compose(self) -> ComposeResult:
        self._body = Static(self._render(), id="custom-body")
        yield Vertical(self._body, id="custom-container")

    def _clamp(self) -> None:
        self.width_val = max(4, min(self.width_val, 80))
        self.height_val = max(4, min(self.height_val, 40))
        cells = self.width_val * self.height_val
        self.mines_val = max(1, min(self.mines_val, cells - 9))

    def _render(self) -> str:
        self._clamp()
        vals = {
            "width": self.width_val,
            "height": self.height_val,
            "mines": self.mines_val,
        }
        lines = ["[bold #f0c080]CUSTOM BOARD[/]", ""]
        for i, f in enumerate(self.FIELDS):
            marker = "▶" if i == self.field else " "
            label = f.capitalize()
            lines.append(f"  {marker} [bold]{label:<6}[/]  {vals[f]:>4}")
        density = self.mines_val * 100.0 / (self.width_val * self.height_val)
        lines += [
            "",
            f"  [dim]Density: {density:.1f}%  (Expert is 20.6%)[/]",
            "",
            "[dim]+/- adjusts · > and < adjust by 10 · Tab cycles field[/]",
            "[dim]Enter starts · Esc cancels[/]",
        ]
        return "\n".join(lines)

    def action_bump(self, delta: int) -> None:
        f = self.FIELDS[self.field]
        if f == "width":
            self.width_val += delta
        elif f == "height":
            self.height_val += delta
        else:
            self.mines_val += delta
        if self._body:
            self._body.update(self._render())

    def action_cycle(self) -> None:
        self.field = (self.field + 1) % len(self.FIELDS)
        if self._body:
            self._body.update(self._render())

    def action_confirm(self) -> None:
        self._clamp()
        self.on_pick("Custom", self.width_val, self.height_val, self.mines_val)
        self.app.pop_screen()


class ResultScreen(ModalScreen):
    """Shown on win or loss. Press n for new game, d for difficulty picker,
    q/escape to dismiss (stay on the final board view)."""

    BINDINGS = [
        Binding("escape,q", "app.pop_screen", "close"),
        Binding("n", "new_game", show=False),
        Binding("d", "difficulty", show=False),
    ]

    def __init__(self, won: bool, elapsed: float, difficulty: str,
                 on_new: Callable[[], None],
                 on_difficulty: Callable[[], None]) -> None:
        super().__init__()
        self.won = won
        self.elapsed = elapsed
        self.difficulty = difficulty
        self.on_new = on_new
        self.on_difficulty = on_difficulty

    def compose(self) -> ComposeResult:
        if self.won:
            title = "[bold rgb(80,220,110)]YOU WIN[/]"
            icon = "[bold rgb(80,220,110)]★[/]"
        else:
            title = "[bold rgb(240,80,80)]BOOM — YOU LOSE[/]"
            icon = "[bold rgb(240,80,80)]✸[/]"
        lines = [
            f"    {icon}  {title}  {icon}",
            "",
            f"  Difficulty : [bold]{self.difficulty}[/]",
            f"  Time       : [bold]{int(self.elapsed)}s[/]",
            "",
            "  [dim]n[/] — new game    [dim]d[/] — change difficulty",
            "  [dim]Esc[/] — close (back to board)",
        ]
        yield Vertical(
            Static("\n".join(lines), id="result-body"),
            id="result-container",
        )

    def action_new_game(self) -> None:
        self.app.pop_screen()
        self.on_new()

    def action_difficulty(self) -> None:
        self.app.pop_screen()
        self.on_difficulty()


class HighScoresScreen(ModalScreen):
    BINDINGS = [Binding("escape,q,h", "app.pop_screen", "close")]

    def __init__(self, scores: dict[str, float | None]) -> None:
        super().__init__()
        self.scores = scores

    def compose(self) -> ComposeResult:
        lines = ["[bold #f0c080]HIGH SCORES  (fastest time)[/]", ""]
        for name in ("Beginner", "Intermediate", "Expert"):
            t = self.scores.get(name)
            if t is None:
                lines.append(f"  {name:<14}  [dim]—[/]")
            else:
                lines.append(f"  {name:<14}  [bold]{int(t)}s[/]")
        lines += ["", "[dim]Custom boards aren't tracked (different shapes are different games).[/]"]
        yield Vertical(
            Static("\n".join(lines), id="hs-body"),
            id="hs-container",
        )
