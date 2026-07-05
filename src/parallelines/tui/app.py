"""Parallelines TUI — monitoring dashboard with run/language actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import App

from parallelines.types import AnalysisReport, AnalysisFragment


class ParallelinesTUI(App):
    """TUI with `r` to run analysis, `l` to switch language."""

    TITLE = "Parallelines"
    CSS_PATH = None
    BINDINGS = []
    ENABLE_COMMAND_PALETTE = False
    SCREEN_NOTIFY = False

    def __init__(self, game: str = "", game_root: str = "",
                 report_path: str | None = None, **kwargs: Any) -> None:
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
        fragments = []
        for entry in raw:
            an = entry.get("analyzer", entry.get("analyzer_name", "?"))
            items = entry.get("results", entry.get("items", []))
            fragments.append(AnalysisFragment(analyzer_name=an, items=items))
        screen.load_report(AnalysisReport(fragments=fragments))
