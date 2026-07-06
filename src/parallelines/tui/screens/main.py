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
from textual.widgets import Static, DataTable, ProgressBar

from parallelines.engine import ResultStore

from parallelines.i18n import _, set_language, detect_language


def _fmt(n: int) -> str:
    try:
        return f"{n:,}"
    except Exception:
        return str(n)


_HELP_TEXT = """
[bold]Keyboard Shortcuts[/]
  r        Run analysis (async -- UI stays responsive)
  l        Switch language (zh/en)
  q / Esc  Quit
  h / F1   Toggle this help
  Ctrl+S   Save report
"""


_PROGRESS_MAP: dict[str, int] = {
    "Building VFS...": 20,
    "Building graph...": 50,
    "Running analyzers...": 80,
}


def _run_pipeline(game: str, game_root: str, status_cb,
                  external_vpk_path: str | None = None) -> Any:
    """Synchronous data pipeline — runs in a thread, reports progress via callback."""
    from parallelines.analysis.addon_dep import AddonDependencyAnalyzer
    from parallelines.analysis.cascade_detector import CascadeDetector
    from parallelines.analysis.cycle_detector import CycleDetector
    from parallelines.analysis.dead_file import DeadFileAnalyzer
    from parallelines.analysis.dep_conflict import DependencyConflictAnalyzer
    from parallelines.analysis.entry_points import discover_entry_points
    from parallelines.analysis.global_script_detector import GlobalScriptDetector
    from parallelines.analysis.hash_conflict import HashConflictAnalyzer
    from parallelines.analysis.implicit_dep_detector import ImplicitDepDetector
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

    analyzers = [
        RedundancyAnalyzer(),
        DeadFileAnalyzer(entry_points=entries if entries else None),
        HashConflictAnalyzer(),
        DependencyConflictAnalyzer(),
        IsolatedPackageAnalyzer(),
        ImpactAnalyzer(top_n=20),
        AddonDependencyAnalyzer(chain=chain),
        CycleDetector(),
        CascadeDetector(),
        GlobalScriptDetector(),
        ImplicitDepDetector(),
    ]

    store = ResultStore.from_analysis(
        vfs=vfs,
        graph=graph,
        analyzers=analyzers,
        entry_points=entries,
        addon_manifests=None,
    )

    # S9: optionally load external VPK reference
    if external_vpk_path:
        store.load_reference(Path(external_vpk_path).stem, external_vpk_path)

    return store


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
    #progress { margin: 0 1; }
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
        self._store = None
        self._game_root: str = ""
        self._game: str = ""
        self._external_vpk_path: str | None = None
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
        yield ProgressBar(total=100, id="progress", show_eta=False)
        yield Static(_HELP_TEXT, id="help")
        yield DataTable(id="analyzers")

    def on_mount(self) -> None:
        self._running = False  # reset stale state from previous crashes
        self._redraw()
        self.query_one("#analyzers", DataTable).add_columns(
            _("analyzer.redundancy"), _("report.issues"), _("report.status")
        )
        self._refresh_table()
        if self._game_root and not self._store:
            self.action_run_analysis()

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
        if self._store:
            try:
                from parallelines.report.generators import generate_report_from_store

                p = generate_report_from_store(self._store, "json", "./reports")
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
                self._update_progress(0)
                self._redraw_status(msg=f"Error: {exc}")
                return
            self._store = fut.result()
            elapsed = time.perf_counter() - self._t0
            self._refresh_table()
            self._update_progress(100)
            self._redraw_status(msg=f"Done ({elapsed:.1f}s)")

        def _status(msg: str) -> None:
            self.app.call_from_thread(self._redraw_status, msg=msg)
            progress = _PROGRESS_MAP.get(msg)
            if progress is not None:
                self.app.call_from_thread(self._update_progress, progress)

        self._t0 = time.perf_counter()
        loop = asyncio.get_event_loop()
        task = loop.run_in_executor(
            None,
            lambda: _run_pipeline(
                game, game_root, _status,
                external_vpk_path=self._external_vpk_path,
            ),
        )
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
        parts = [f"Game: {self._game}"]
        if msg:
            parts.append(msg)
        elif self._store:
            total = 0
            if self._store.files:
                total += len(self._store.files.select(lambda r: r.is_dead))
                total += len(self._store.files.select(lambda r: r.is_redundant))
            if self._store.hash_conflicts:
                total += len(self._store.hash_conflicts)
            if self._store.dep_conflicts:
                total += len(self._store.dep_conflicts)
            parts.append(f"Total issues: {_fmt(total)}")
        self.query_one("#status", Static).update("  |  ".join(parts))

    def _update_progress(self, value: int) -> None:
        try:
            self.query_one("#progress", ProgressBar).update(progress=value)
        except Exception:
            pass

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

        if self._store is None:
            t.add_rows([["--", "--", _("report.ok")]])
            return

        fragments = [
            (
                "Redundancy",
                len(self._store.files.select(lambda r: r.is_redundant))
                if self._store.files
                else 0,
            ),
            (
                "DeadFile",
                len(self._store.files.select(lambda r: r.is_dead))
                if self._store.files
                else 0,
            ),
            (
                "HashConflict",
                len(self._store.hash_conflicts) if self._store.hash_conflicts else 0,
            ),
            (
                "DepConflict",
                len(self._store.dep_conflicts) if self._store.dep_conflicts else 0,
            ),
            (
                "Isolated",
                len(self._store.isolated.select(lambda r: r.dead_file_count > 0))
                if self._store.isolated
                else 0,
            ),
            ("Impact", len(self._store.impact) if self._store.impact else 0),
        ]
        for name, cnt in fragments:
            status = _("report.ok") if cnt == 0 else f"{_fmt(cnt)} found"
            t.add_rows([[name, str(cnt), status]])

    def load_report(self, store) -> None:
        self._store = store
        if self.is_mounted:
            self._refresh_table()
            self._redraw_status()
