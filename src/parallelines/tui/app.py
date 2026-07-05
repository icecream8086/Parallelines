"""Parallelines TUI — monitoring dashboard with run/language actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import App

from parallelines.engine import ResultStore
from parallelines.engine.schema import (
    FileRow,
    DependencyRow,
    HashConflictRow,
    DepConflictRow,
    IsolatedPackageRow,
    ImpactRow,
)
from parallelines.engine.store import Relation


class ParallelinesTUI(App):
    """TUI with `r` to run analysis, `l` to switch language."""

    TITLE = "Parallelines"
    CSS_PATH = None
    BINDINGS = []
    ENABLE_COMMAND_PALETTE = False
    SCREEN_NOTIFY = False

    def __init__(
        self,
        game: str = "",
        game_root: str = "",
        report_path: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._game = game
        self._game_root = game_root
        self._report_path = report_path

    def on_ready(self) -> None:
        """App is fully running — safe to push screens now."""
        from parallelines.tui.screens.main import MainScreen

        screen = MainScreen()
        screen.set_game(self._game, self._game_root)
        self.push_screen(screen)

        if self._report_path:
            self._load_report(screen, self._report_path)

    def _load_report(self, screen, path_str: str) -> None:
        p = Path(path_str)
        if not p.is_file():
            return
        try:
            import json

            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return
        store = ResultStore()
        row_map = {
            "files": (
                FileRow,
                "virtual_path",
                "source_name",
                "source_type",
                "priority",
                "file_hash",
                "file_size",
                "is_active",
                "is_dead",
                "is_redundant",
            ),
            "dependencies": (DependencyRow, "from_path", "to_path", "expected_source"),
            "hash_conflicts": (
                HashConflictRow,
                "virtual_path",
                "winner_source",
                "loser_source",
                "winner_hash",
                "loser_hash",
            ),
            "dep_conflicts": (
                DepConflictRow,
                "from_path",
                "to_path",
                "expected_source",
                "actual_source",
            ),
            "isolated": (
                IsolatedPackageRow,
                "source_name",
                "dead_file_count",
                "example_paths",
            ),
            "impact": (ImpactRow, "virtual_path", "source_name", "impact_count"),
        }
        for rel_name, (cls, *fields) in row_map.items():
            items = raw.get(rel_name, [])
            if items:
                rows: list = [cls(**{f: item.get(f) for f in fields}) for item in items]  # type: ignore[operator,arg-type]
                setattr(store, rel_name, Relation.from_rows(rel_name, rows))
        screen.load_report(store)
