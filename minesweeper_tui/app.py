"""Minesweeper TUI — Textual App, BoardView, side panels."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from rich.segment import Segment
from rich.style import Style
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.geometry import Region, Size
from textual.message import Message
from textual.reactive import reactive
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Footer, Header, RichLog, Static

from . import tiles
from .engine import (
    ActionResult,
    Difficulty,
    Game,
    GameState,
    HIDDEN,
    REVEALED,
    FLAGGED,
    QUESTION,
    MINE,
    new_game,
)
from .screens import (
    CustomScreen,
    DifficultyScreen,
    HelpScreen,
    HighScoresScreen,
    LegendScreen,
    ResultScreen,
)
from .sounds import SoundBoard


# -------- high-scores persistence --------
# Stored in user data dir: ~/.local/share/minesweeper-tui/highscores.json
_DATA_DIR = Path.home() / ".local" / "share" / "minesweeper-tui"
_HS_PATH = _DATA_DIR / "highscores.json"


def _load_highscores() -> dict[str, float]:
    if not _HS_PATH.exists():
        return {}
    try:
        data = json.loads(_HS_PATH.read_text())
        # Accept {name: seconds} only; strip unknown keys / non-numeric vals.
        return {k: float(v) for k, v in data.items() if isinstance(v, (int, float))}
    except (OSError, ValueError, TypeError):
        return {}


def _save_highscores(scores: dict[str, float]) -> None:
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _HS_PATH.write_text(json.dumps(scores, indent=2))
    except OSError:
        pass  # silent — high scores are cosmetic


# -------- Board rendering widget --------

# Each cell is rendered as 3 character columns wide so mines/numbers have
# breathing room and the board reads as a grid rather than wall of text.
# 1 row high per cell keeps the board compact.
CELL_W = 3
CELL_H = 1


class BoardView(ScrollView):
    """Renders the minefield with a highlighted cursor.

    Uses Textual's `render_line` API so only visible rows are painted and
    cursor moves repaint only the two affected rows (old + new)."""

    DEFAULT_CSS = "BoardView { padding: 0; }"

    cursor_x: reactive[int] = reactive(0)
    cursor_y: reactive[int] = reactive(0)

    class CellAction(Message):
        def __init__(self, x: int, y: int, action: str) -> None:
            self.x = x
            self.y = y
            self.action = action  # "reveal" | "flag" | "chord"
            super().__init__()

    def __init__(self, game: Game) -> None:
        super().__init__()
        self.game = game
        self.cursor_x = game.width // 2
        self.cursor_y = game.height // 2
        self._update_virtual_size()

    def attach_game(self, game: Game) -> None:
        """Swap in a new game (called on restart / difficulty change)."""
        self.game = game
        self.cursor_x = game.width // 2
        self.cursor_y = game.height // 2
        self._update_virtual_size()
        self.refresh()

    def _update_virtual_size(self) -> None:
        self.virtual_size = Size(self.game.width * CELL_W, self.game.height * CELL_H)

    def watch_cursor_x(self, old: int, new: int) -> None:
        self._refresh_cursor_rows_after_move(old, self.cursor_y, new, self.cursor_y)

    def watch_cursor_y(self, old: int, new: int) -> None:
        self._refresh_cursor_rows_after_move(self.cursor_x, old, self.cursor_x, new)

    def _refresh_cursor_rows_after_move(
        self, ox: int, oy: int, nx: int, ny: int
    ) -> None:
        """Repaint only the two rows touched by a cursor move. Watchers fire
        before mount in some flows — guard against that."""
        if not self.is_mounted:
            return
        w = self.size.width
        for row in {oy, ny}:
            self.refresh(Region(0, row * CELL_H, w, CELL_H))

    def render_line(self, y: int) -> Strip:
        """Render one visible terminal row.

        `y` is a viewport-relative row; add scroll offset to get the world row."""
        scroll_x, scroll_y = self.scroll_offset
        world_row = y + scroll_y
        tile_y = world_row // CELL_H
        if tile_y < 0 or tile_y >= self.game.height:
            return Strip.blank(self.size.width)

        segments: list[Segment] = []
        # Left padding for any sub-cell scroll offset.
        leading = scroll_x % CELL_W
        first_tile_x = scroll_x // CELL_W
        visible_w = self.size.width

        x_pix = -leading
        tile_x = first_tile_x
        while x_pix < visible_w:
            if tile_x < 0 or tile_x >= self.game.width:
                # Out of board — fill with blank.
                break
            glyph, style = self._cell_glyph_style(tile_x, tile_y)
            # Render as a 3-wide cell: " G " where G is the glyph. This
            # gives spacing without extra FFI or list cost.
            cell_str = f" {glyph} "
            # Clip if this is the first or last partially visible cell.
            start = 0
            end = CELL_W
            if x_pix < 0:
                start = -x_pix
                x_pix = 0
            if x_pix + (end - start) > visible_w:
                end = start + (visible_w - x_pix)
            if end > start:
                segments.append(Segment(cell_str[start:end], style))
                x_pix += end - start
            tile_x += 1
        # Pad right edge with blank so the strip matches the viewport width.
        painted = sum(len(s.text) for s in segments)
        if painted < visible_w:
            segments.append(Segment(" " * (visible_w - painted),
                                    Style(bgcolor="#000000")))
        return Strip(segments)

    def _cell_glyph_style(self, x: int, y: int) -> tuple[str, Style]:
        """Resolve the glyph + Style for tile (x, y). Handles cursor
        highlight, all cell states, and post-loss mine reveal."""
        g = self.game
        idx = y * g.width + x
        s = g.state[idx]
        adj = g.adjacency[idx]
        at_cursor = (x == self.cursor_x and y == self.cursor_y)

        if s == REVEALED:
            if adj == MINE:
                exploded = g.exploded_at == (x, y)
                return (tiles.GLYPH_EXPLOSION if exploded else tiles.GLYPH_MINE,
                        tiles.mine_style(x, y, exploded=exploded, cursor=at_cursor))
            if adj == 0:
                return tiles.GLYPH_EMPTY, tiles.revealed_empty_style(x, y, cursor=at_cursor)
            return str(adj), tiles.revealed_digit_style(adj, x, y, cursor=at_cursor)

        if s == FLAGGED:
            # Post-loss, flag on a non-mine is a "wrong flag" marker.
            if g.game_state == GameState.LOST and adj != MINE:
                return tiles.GLYPH_WRONG_FLAG, tiles.wrong_flag_style(x, y, cursor=at_cursor)
            return tiles.GLYPH_FLAG, tiles.flag_style(x, y, cursor=at_cursor)

        if s == QUESTION:
            return tiles.GLYPH_QUESTION, tiles.question_style(x, y, cursor=at_cursor)

        if s == HIDDEN:
            return tiles.GLYPH_COVERED, tiles.covered_style(x, y, cursor=at_cursor)

        # Defensive: any unexpected state value renders as loud magenta so
        # a dev notices, but production never crashes mid-render. (Same
        # pattern the skill gotcha catalog recommends for unknown classes.)
        unknown = Style(color="magenta", bgcolor="#220022", bold=True)
        return "?", unknown

    # --- mouse handling ---

    def _event_to_tile(self, event) -> tuple[int, int] | None:
        x = event.x + int(self.scroll_offset.x)
        y = event.y + int(self.scroll_offset.y)
        tx, ty = x // CELL_W, y // CELL_H
        if 0 <= tx < self.game.width and 0 <= ty < self.game.height:
            return tx, ty
        return None

    async def on_click(self, event: events.Click) -> None:
        spot = self._event_to_tile(event)
        if spot is None:
            return
        self.cursor_x, self.cursor_y = spot
        # Button: 1=left, 2=middle, 3=right.
        btn = getattr(event, "button", 1)
        if btn == 3:
            self.post_message(self.CellAction(spot[0], spot[1], "flag"))
        elif btn == 2:
            self.post_message(self.CellAction(spot[0], spot[1], "chord"))
        else:
            self.post_message(self.CellAction(spot[0], spot[1], "reveal"))


# -------- side panels --------

class StatusPanel(Static):
    DEFAULT_CSS = ""

    def __init__(self) -> None:
        super().__init__("", id="status")
        self.border_title = "Status"

    def refresh_panel(self, app: "MinesweeperApp") -> None:
        g = app.game
        # Smiley face reflects game state — classic MS tradition.
        face = {
            GameState.READY:   "[bold rgb(240,200,80)]☺[/]",
            GameState.PLAYING: "[bold rgb(240,200,80)]☺[/]",
            GameState.WON:     "[bold rgb(80,220,110)]★[/]",
            GameState.LOST:    "[bold rgb(240,80,80)]☠[/]",
        }[g.game_state]
        elapsed = app.elapsed_seconds()
        flags = g.flags_placed
        remaining = g.mines_remaining
        lines = [
            f"  {face}   [bold]{app.difficulty_label}[/]",
            "",
            f"  Mines left  : [bold]{remaining:>4}[/]",
            f"  Flags       : [bold]{flags:>4}[/]",
            f"  Time        : [bold]{int(elapsed):>4}s[/]",
            "",
            f"  Revealed    : [dim]{g.cells_revealed}/{g.safe_cells}[/]",
        ]
        self.update("\n".join(lines))


class ControlsPanel(Static):
    def __init__(self) -> None:
        super().__init__("", id="controls")
        self.border_title = "Controls"

    def refresh_panel(self) -> None:
        lines = [
            "  [bold]Arrows[/]  move cursor",
            "  [bold]Space[/]   reveal",
            "  [bold]f[/]       flag / unflag",
            "  [bold]c[/]       chord",
            "  [bold]n[/]       new game",
            "  [bold]d[/]       difficulty",
            "",
            "  [bold]?[/]       help",
            "  [bold]l[/]       legend",
            "  [bold]h[/]       high scores",
            "  [bold]q[/]       quit",
            "",
            "  [dim]mouse: L reveal · R flag · M chord[/]",
        ]
        self.update("\n".join(lines))


class LegendPanel(Static):
    def __init__(self) -> None:
        super().__init__("", id="legend-panel")
        self.border_title = "Legend"

    def refresh_panel(self) -> None:
        lines = [
            "  [dim]·[/]  covered",
            "  [bold rgb(240,80,80)]⚑[/]  flag",
            "  [bold rgb(250,220,120)]✸[/]  mine",
            "  [bold rgb(240,120,90)]✗[/]  wrong flag",
            "",
            "  Digit colors:",
            "    [bold rgb(80,160,255)]1[/]  [bold rgb(80,220,110)]2[/]  [bold rgb(240,80,80)]3[/]  [bold rgb(160,100,220)]4[/]",
            "    [bold rgb(230,140,60)]5[/]  [bold rgb(80,200,210)]6[/]  [bold rgb(220,220,220)]7[/]  [bold rgb(180,180,180)]8[/]",
        ]
        self.update("\n".join(lines))


# -------- the App --------

class MinesweeperApp(App):
    CSS_PATH = "tui.tcss"
    TITLE = "Minesweeper TUI"

    BINDINGS = [
        Binding("q", "quit", "quit", show=True),
        Binding("ctrl+c", "quit", show=False),
        Binding("up",    "move_cursor(0,-1)", priority=True, show=False),
        Binding("down",  "move_cursor(0,1)",  priority=True, show=False),
        Binding("left",  "move_cursor(-1,0)", priority=True, show=False),
        Binding("right", "move_cursor(1,0)",  priority=True, show=False),
        Binding("home",  "move_cursor(-999,0)", priority=True, show=False),
        Binding("end",   "move_cursor(999,0)",  priority=True, show=False),
        Binding("pageup",   "move_cursor(0,-999)", priority=True, show=False),
        Binding("pagedown", "move_cursor(0,999)",  priority=True, show=False),
        Binding("space", "reveal", show=True),
        Binding("enter", "reveal", show=False),
        Binding("f",     "flag",   show=True),
        Binding("c",     "chord",  show=True),
        Binding("n",     "new_game",   show=True),
        Binding("d",     "difficulty", show=True),
        Binding("question_mark,slash", "help",     show=False),
        Binding("l",     "legend",     show=False),
        Binding("h",     "highscores", show=False),
    ]

    def __init__(self, difficulty: Difficulty = Difficulty.BEGINNER,
                 *, width: int | None = None, height: int | None = None,
                 mines: int | None = None, seed: int | None = None,
                 sound: bool = False,
                 agent: bool = False, host: str = "127.0.0.1",
                 port: int = 8765) -> None:
        super().__init__()
        self._initial_difficulty = difficulty
        self._initial_width = width
        self._initial_height = height
        self._initial_mines = mines
        self._seed = seed
        self.game: Game = new_game(difficulty, width=width, height=height,
                                    mines=mines, seed=seed)
        self.difficulty_label = self._label_for(difficulty, self.game)
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.highscores: dict[str, float] = _load_highscores()
        self.sounds = SoundBoard(enabled=sound)

        # Agent API state.
        self._agent_enabled = agent
        self._agent_host = host
        self._agent_port = port
        self._agent_api = None  # AgentAPI | None — populated on_mount if enabled
        self._agent_runner = None  # aiohttp AppRunner

        # Widget refs — filled in compose().
        self.board_view: Optional[BoardView] = None
        self.status_panel: Optional[StatusPanel] = None
        self.controls_panel: Optional[ControlsPanel] = None
        self.legend_panel: Optional[LegendPanel] = None
        self.log_view: Optional[RichLog] = None
        self.flash_bar: Optional[Static] = None

    def _label_for(self, difficulty: Difficulty, g: Game) -> str:
        if difficulty is Difficulty.CUSTOM:
            return f"Custom {g.width}×{g.height} / {g.mine_count}"
        return difficulty.label

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        self.flash_bar = Static("Welcome — click or press Space to reveal.  ?=help",
                                id="flash-bar")
        yield self.flash_bar
        self.board_view = BoardView(self.game)
        self.status_panel = StatusPanel()
        self.controls_panel = ControlsPanel()
        self.legend_panel = LegendPanel()
        self.log_view = RichLog(id="log", markup=True, max_lines=500)
        self.log_view.border_title = "Log"
        yield Horizontal(
            Vertical(
                self.board_view,
                self.log_view,
                id="board-col",
            ),
            Vertical(
                self.status_panel,
                self.controls_panel,
                self.legend_panel,
                id="side",
            ),
            id="body",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.board_view.border_title = "Minefield"
        self.controls_panel.refresh_panel()
        self.legend_panel.refresh_panel()
        self.status_panel.refresh_panel(self)
        self.log_msg(f"[bold #f0c080]New game:[/] {self.difficulty_label}")
        # 1 Hz UI refresh for timer.
        self.set_interval(1.0, self._tick_ui)
        # Claim focus so our priority bindings dominate the ScrollView's
        # native arrow-scroll bindings.
        self.set_focus(None)
        # Optional: bring up the agent REST API on the same asyncio loop.
        if self._agent_enabled:
            self.run_worker(self._start_agent_api(), exclusive=True)

    async def _start_agent_api(self) -> None:
        """Launch the aiohttp server as a background task sharing our loop."""
        from .agent_api import AgentAPI, start_server

        def _on_change() -> None:
            # Agent mutated the game state; push it into our UI.
            if self.board_view is not None:
                self.board_view.refresh()
            if self.status_panel is not None:
                self.status_panel.refresh_panel(self)

        self._agent_api = AgentAPI(self.game, on_change=_on_change)
        try:
            runner, bound = await start_server(
                self._agent_api,
                host=self._agent_host,
                port=self._agent_port,
            )
        except OSError as e:
            self.log_msg(f"[red]agent API failed to bind[/] {e}")
            return
        self._agent_runner = runner
        self.log_msg(
            f"[bold rgb(80,220,110)]agent API listening[/] "
            f"http://{self._agent_host}:{bound}"
        )

    def _tick_ui(self) -> None:
        if self.status_panel is not None:
            self.status_panel.refresh_panel(self)

    def elapsed_seconds(self) -> float:
        if self.start_time is None:
            return 0.0
        end = self.end_time if self.end_time is not None else time.monotonic()
        return end - self.start_time

    def log_msg(self, msg: str) -> None:
        if self.log_view is not None:
            self.log_view.write(msg)

    def flash(self, msg: str) -> None:
        if self.flash_bar is not None:
            self.flash_bar.update(msg)

    # --- actions ---

    def action_move_cursor(self, dx: int, dy: int) -> None:
        if self.board_view is None:
            return
        g = self.game
        nx = max(0, min(self.board_view.cursor_x + dx, g.width - 1))
        ny = max(0, min(self.board_view.cursor_y + dy, g.height - 1))
        self.board_view.cursor_x = nx
        self.board_view.cursor_y = ny

    def action_reveal(self) -> None:
        if self.board_view is None or self.game.is_over:
            if self.game.is_over:
                self.flash("Game over. Press [bold]n[/] for a new game.")
            return
        self._apply_action(self.board_view.cursor_x, self.board_view.cursor_y,
                           "reveal")

    def action_flag(self) -> None:
        if self.board_view is None or self.game.is_over:
            return
        self._apply_action(self.board_view.cursor_x, self.board_view.cursor_y,
                           "flag")

    def action_chord(self) -> None:
        if self.board_view is None or self.game.is_over:
            return
        self._apply_action(self.board_view.cursor_x, self.board_view.cursor_y,
                           "chord")

    def _apply_action(self, x: int, y: int, action: str) -> None:
        g = self.game
        pre_state = g.state[y * g.width + x]
        if action == "reveal":
            result = g.reveal(x, y)
        elif action == "flag":
            result = g.flag(x, y)
        elif action == "chord":
            result = g.chord(x, y)
        else:
            return
        if g.game_state == GameState.PLAYING and self.start_time is None:
            self.start_time = time.monotonic()

        # Sound + flash message per outcome.
        if result == ActionResult.MINE:
            self.sounds.play("explosion")
            self.end_time = time.monotonic()
            self.flash(f"[red]✸ BOOM — exploded at ({x},{y})[/]")
            self.log_msg(f"[red]✸ BOOM[/]  stepped on a mine at ({x},{y})")
            self._on_game_over(won=False)
        elif result == ActionResult.WIN:
            self.sounds.play("win")
            self.end_time = time.monotonic()
            t = int(self.elapsed_seconds())
            self.flash(f"[green]★ SOLVED in {t}s[/]")
            self.log_msg(f"[green]★ Solved[/]  all safe cells revealed in {t}s")
            self._on_game_over(won=True)
        elif result == ActionResult.OK:
            if action == "reveal":
                self.sounds.play("reveal")
            elif action == "flag":
                # Determine whether we just placed or removed a flag.
                idx = y * g.width + x
                if g.state[idx] == FLAGGED and pre_state != FLAGGED:
                    self.sounds.play("flag")
                else:
                    self.sounds.play("unflag")
            elif action == "chord":
                self.sounds.play("chord")
            self.flash(f"{action} at ({x},{y})")
        elif result == ActionResult.NO_CHANGE:
            self.sounds.play("invalid")
            self.flash(f"[yellow]{action} at ({x},{y}): no change[/]")
        elif result == ActionResult.INVALID:
            self.flash("[yellow]invalid move[/]")

        # Repaint the whole board only when many cells changed (reveal/chord
        # on a big zero-region) or when the game ended. Cursor-moves use a
        # targeted refresh; for reveals a full refresh is fine — the board is
        # at most 80×40 cells.
        if self.board_view is not None:
            self.board_view.refresh()
        if self.status_panel is not None:
            self.status_panel.refresh_panel(self)

    def _on_game_over(self, won: bool) -> None:
        if won:
            # High score: lowest time per named difficulty.
            if self._initial_difficulty in (Difficulty.BEGINNER,
                                             Difficulty.INTERMEDIATE,
                                             Difficulty.EXPERT):
                name = self._initial_difficulty.label
                t = self.elapsed_seconds()
                prev = self.highscores.get(name)
                if prev is None or t < prev:
                    self.highscores[name] = t
                    _save_highscores(self.highscores)
                    self.log_msg(f"[bold green]NEW HIGH SCORE[/] {name}: {int(t)}s")
        self.push_screen(
            ResultScreen(
                won=won,
                elapsed=self.elapsed_seconds(),
                difficulty=self.difficulty_label,
                on_new=lambda: self.action_new_game(),
                on_difficulty=lambda: self.action_difficulty(),
            )
        )

    def action_new_game(self) -> None:
        """Restart at the current difficulty."""
        self.game = new_game(
            self._initial_difficulty,
            width=self._initial_width,
            height=self._initial_height,
            mines=self._initial_mines,
            seed=None,  # fresh randomness on restart
        )
        self.start_time = None
        self.end_time = None
        if self.board_view is not None:
            self.board_view.attach_game(self.game)
        self.status_panel.refresh_panel(self)
        if self._agent_api is not None:
            self._agent_api.set_game(self.game)
        self.flash("New game started.")
        self.log_msg(f"[bold #f0c080]New game:[/] {self.difficulty_label}")

    def action_difficulty(self) -> None:
        def _pick(name: str, w: int, h: int, m: int) -> None:
            diff_map = {
                "Beginner": Difficulty.BEGINNER,
                "Intermediate": Difficulty.INTERMEDIATE,
                "Expert": Difficulty.EXPERT,
            }
            if name in diff_map:
                self._initial_difficulty = diff_map[name]
                self._initial_width = None
                self._initial_height = None
                self._initial_mines = None
                self.game = new_game(self._initial_difficulty)
            else:
                self._initial_difficulty = Difficulty.CUSTOM
                self._initial_width = w
                self._initial_height = h
                self._initial_mines = m
                self.game = new_game(Difficulty.CUSTOM, width=w, height=h, mines=m)
            self.difficulty_label = self._label_for(self._initial_difficulty, self.game)
            self.start_time = None
            self.end_time = None
            if self.board_view is not None:
                self.board_view.attach_game(self.game)
            self.status_panel.refresh_panel(self)
            if self._agent_api is not None:
                self._agent_api.set_game(self.game)
            self.flash(f"Difficulty set: {self.difficulty_label}")
            self.log_msg(f"[bold #f0c080]New game:[/] {self.difficulty_label}")

        self.push_screen(DifficultyScreen(_pick))

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_legend(self) -> None:
        self.push_screen(LegendScreen())

    def action_highscores(self) -> None:
        # Ensure all difficulty keys exist so the screen can show a stable
        # three-row layout.
        full = {"Beginner": None, "Intermediate": None, "Expert": None,
                **self.highscores}
        self.push_screen(HighScoresScreen(full))

    def on_board_view_cell_action(self, msg: BoardView.CellAction) -> None:
        self._apply_action(msg.x, msg.y, msg.action)


# -------- entry --------

def run(difficulty: str = "beginner",
        *, width: int | None = None, height: int | None = None,
        mines: int | None = None, seed: int | None = None,
        sound: bool = False,
        agent: bool = False, host: str = "127.0.0.1",
        port: int = 8765) -> None:
    diff = {
        "beginner": Difficulty.BEGINNER,
        "intermediate": Difficulty.INTERMEDIATE,
        "expert": Difficulty.EXPERT,
        "custom": Difficulty.CUSTOM,
    }.get(difficulty.lower())
    if diff is None:
        raise SystemExit(f"unknown difficulty: {difficulty!r}")
    app = MinesweeperApp(diff, width=width, height=height, mines=mines,
                          seed=seed, sound=sound, agent=agent,
                          host=host, port=port)
    try:
        app.run()
    finally:
        # Reset mouse-tracking escape sequences in case Textual missed them.
        import sys
        sys.stdout.write(
            "\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?1015l\033[?25h"
        )
        sys.stdout.flush()
        app.sounds.close()
