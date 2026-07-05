"""Main screen — monitoring dashboard with async analysis pipeline."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Static, DataTable

from parallelines.i18n import _, set_language, detect_language


def _fmt(n: int) -> str:
    try:
        return f"{n:,}"
    except Exception:
        return str(n)


_HELP_TEXT = """
[bold]Keyboard Shortcuts[/]
  r        Run analysis (async — UI stays responsive)
  l        Switch language (zh/en)
  q / Esc  Quit
  h / F1   Toggle this help
  Ctrl+S   Save report
"""


def _run_pipeline(game: str, game_root: str, status_cb) -> Any:
    """Synchronous data pipeline — runs in a thread, reports progress via callback."""
    from parallelines.analysis.addon_dep import AddonDependencyAnalyzer
    from parallelines.analysis.dead_file import DeadFileAnalyzer
    from parallelines.analysis.dep_conflict import DependencyConflictAnalyzer
    from parallelines.analysis.engine import AnalyzerEngine
    from parallelines.analysis.entry_points import discover_entry_points
    from parallelines.analysis.hash_conflict import HashConflictAnalyzer
    from parallelines.analysis.impact import ImpactAnalyzer
    from parallelines.analysis.isolated import IsolatedPackageAnalyzer
    from parallelines.analysis.redundancy import RedundancyAnalyzer
    from parallelines.config import load_config
    from parallelines.graph.builder import GraphBuilder
    from parallelines.vfs.builder import VfsBuilder

    root = Path(game_root).resolve()
    config = load_config()
    config.general.game = game
    config.general.game_root = str(root)

    status_cb("Building VFS...")
    builder = VfsBuilder(root, config)
    vfs = builder.build()

    status_cb("Building graph...")
    chain = builder.get_chain()
    graph = None
    if chain:
        gb = GraphBuilder(chain, vfs)
        graph = gb.build()

    status_cb("Running analyzers...")
    entries = discover_entry_points(vfs, chain=chain) if vfs else set()
    engine = AnalyzerEngine()
    engine.register(RedundancyAnalyzer())
    engine.register(DeadFileAnalyzer(entry_points=entries if entries else None))
    engine.register(HashConflictAnalyzer())
    engine.register(DependencyConflictAnalyzer())
    engine.register(IsolatedPackageAnalyzer())
    engine.register(ImpactAnalyzer(top_n=20))
    engine.register(AddonDependencyAnalyzer(chain=chain))

    report = engine.run(vfs, graph)
    return report


class MainScreen(Screen):
    """Single-page dashboard. Analysis runs in a thread — UI stays alive."""

    BINDINGS = [
        Binding("r", "run_analysis", "Run", priority=True),
        Binding("l", "cycle_language", "Lang", priority=True),
        Binding("q", "quit", "Quit", priority=True),
        Binding("escape", "quit", "", priority=True),
        Binding("h", "toggle_help", "Help", priority=True),
        Binding("f1", "toggle_help", "", priority=True),
        Binding("s", "save_report", "Save", priority=True),
    ]

    DEFAULT_CSS = """
    MainScreen { align: center top; }
    #header {
        text-style: bold; padding: 0 1;
        background: $accent; color: $text;
    }
    #status { padding: 0 1; }
    #sep { color: $surface; }
    #analyzers { margin: 0 1; height: 1fr; }
    #help {
        margin: 0 2; padding: 1 2;
        border: solid $primary;
        height: auto;
        display: none;
    }
    #help.visible { display: block; }
    DataTable { border: none; }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._report = None
        self._game_root: str = ""
        self._game: str = ""
        self._show_help = False
        self._running = False
        self._lock = threading.Lock()

    def set_game(self, game: str, game_root: str) -> None:
        self._game = game
        self._game_root = game_root

    def compose(self) -> ComposeResult:
        yield Static(id="header")
        yield Static(id="status")
        yield Static("─" * 60, id="sep")
        yield Static(_HELP_TEXT, id="help")
        yield DataTable(id="analyzers")

    def on_mount(self) -> None:
        self._running = False  # reset stale state from previous crashes
        self._redraw()
        self.query_one("#analyzers", DataTable).add_columns(
            _("analyzer.redundancy"), _("report.issues"), _("report.status")
        )
        self._refresh_table()

    # ── Actions ─────────────────────────────────────────────

    def action_run_analysis(self) -> None:
        with self._lock:
            if self._running:
                self._running = False
                self._redraw_status(msg="Cancelled")
                return
        if not self._game_root:
            self._redraw_status(msg="Set --game-root first")
            return
        self._redraw_status(msg="Starting (async)...")
        self.refresh()
        with self._lock:
            self._running = True
        self._run_async()

    def action_cycle_language(self) -> None:
        set_language("en" if detect_language() == "zh" else "zh")
        self._redraw()
        self._update_table_lang()

    def action_quit(self) -> None:
        self.app.exit()

    def action_toggle_help(self) -> None:
        self._show_help = not self._show_help
        self.query_one("#help", Static).set_class(self._show_help, "visible")

    def action_save_report(self) -> None:
        if self._report:
            try:
                from parallelines.report.generators import generate_report

                p = generate_report(self._report, "json", "./reports")
                self._redraw_status(msg=f"Saved: {p.name}")
            except Exception as exc:
                self._redraw_status(msg=f"Save error: {exc}")
        else:
            self._redraw_status(msg="No report to save")

    # ── Async pipeline ──────────────────────────────────────

    def _run_async(self) -> None:
        """Dispatch analysis to a thread; keep UI responsive."""
        game = self._game
        game_root = self._game_root

        def _on_done(fut: asyncio.Future) -> None:
            with self._lock:
                self._running = False
            exc = fut.exception()
            if exc:
                self._redraw_status(msg=f"Error: {exc}")
                return
            self._report = fut.result()
            elapsed = time.perf_counter() - self._t0
            self._refresh_table()
            self._redraw_status(msg=f"Done ({elapsed:.1f}s)")

        def _status(msg: str) -> None:
            self.app.call_from_thread(self._redraw_status, msg=msg)

        self._t0 = time.perf_counter()
        loop = asyncio.get_event_loop()
        task = loop.run_in_executor(None, _run_pipeline, game, game_root, _status)
        task.add_done_callback(_on_done)

    # ── UI helpers ──────────────────────────────────────────

    def _redraw(self) -> None:
        lang = "ZH" if detect_language() == "zh" else "EN"
        self.query_one("#header", Static).update(
            f"Parallelines  v0.1.0  [{lang}]  "
            f"r:{_('tui.run_analysis')}  "
            f"l:{_('lang.switch')}  "
            "h:Help  "
            f"q:{_('app.quit')}"
        )

    def _redraw_status(self, msg: str = "") -> None:
        parts = []
        if self._report:
            total = sum(len(f.items) for f in self._report.fragments)
            parts.append(f"issues:{_fmt(total)}")
        if msg:
            parts.append(msg)
        if self._game_root:
            parts.append(f"Game:{self._game}")
        self.query_one("#status", Static).update("  |  ".join(parts))

    def _update_table_lang(self) -> None:
        """Update table column labels to current language without clearing rows."""
        t = self.query_one("#analyzers", DataTable)
        labels = [_("analyzer.redundancy"), _("report.issues"), _("report.status")]
        for i, label in enumerate(labels):
            try:
                t.columns[i].label = label  # type: ignore[assignment,index]
            except Exception:
                pass

    def _refresh_table(self) -> None:
        t = self.query_one("#analyzers", DataTable)
        t.clear()
        t.add_columns(_("analyzer.redundancy"), _("report.issues"), _("report.status"))
        if not self._report or not self._report.fragments:
            t.add_rows([["—", "—", _("report.ok")]])
            return
        for f in self._report.fragments:
            name = f.analyzer_name.replace("Analyzer", "")
            cnt = len(f.items)
            status = _("report.ok") if cnt == 0 else f"{_fmt(cnt)} found"
            t.add_rows([[name, str(cnt), status]])

    def load_report(self, report) -> None:
        self._report = report
        if self.is_mounted:
            self._refresh_table()
            self._redraw_status()
