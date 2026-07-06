"""REPL prompt rendering."""
from __future__ import annotations
import os
from pathlib import Path

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.styles import Style as _Style
    from prompt_toolkit.formatted_text import HTML

    _HAS_PT = True
except ImportError:
    _HAS_PT = False


_HIST_DIR = Path(os.environ.get("APPDATA", Path.home() / ".local" / "share")) / "parallelines"
_HIST_DIR.mkdir(parents=True, exist_ok=True)
_HISTORY_PATH = _HIST_DIR / "history.txt"


if _HAS_PT:
    _STYLE = _Style.from_dict({
        "game": "bold cyan",
        "external": "ansiyellow",
        "prompt": "",
    })

    def _get_session(completer=None) -> PromptSession:
        return PromptSession(
            history=FileHistory(str(_HISTORY_PATH)),
            completer=completer,
            complete_while_typing=True,
            style=_STYLE,
        )

    def make_prompt(game: str, externals: list[str] | None = None):
        base = f"<game>{game}</game>"
        if externals:
            refs = "+".join(externals)
            base += f" (<external>ref:{refs}</external>)"
        return HTML(f"<prompt>{base}&gt; </prompt>")
else:
    def _get_session(completer=None):  # type: ignore[misc]
        """Fallback: readline input when prompt_toolkit is not available."""
        return None

    def make_prompt(game: str, externals: list[str] | None = None) -> str:  # type: ignore[return]
        base = game
        if externals:
            refs = "+".join(externals)
            base += f" (ref:{refs})"
        return f"{base}> "
