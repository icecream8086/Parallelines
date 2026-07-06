"""Tab completion for the REPL."""
from __future__ import annotations

try:
    from prompt_toolkit.completion import WordCompleter
    _HAS_PT = True
except ImportError:
    _HAS_PT = False

from parallelines.engine.store import ResultStore

_STORE_ATTRS = [
    "files", "dependencies", "addons", "hash_conflicts",
    "dep_conflicts", "isolated", "impact", "entry_points",
    "dependency_cycles", "cascade_overrides", "global_scripts",
    "implicit_deps", "mod_types", "external_files",
]

_META_COMMANDS = [
    ".help", ".tables", ".schema", ".mode", ".save", ".load",
    ".external", ".analyze", ".game", ".print", ".pager",
    ".exit", ".quit", ".history", ".echo", ".unload", ".stores",
]


def build_completer(store: ResultStore | None = None):
    """Build a WordCompleter for meta-commands and relation names.

    Returns a WordCompleter if prompt_toolkit is available, None otherwise.
    """
    if not _HAS_PT:
        return None
    words = list(_META_COMMANDS)
    if store is not None:
        for attr in _STORE_ATTRS:
            if getattr(store, attr, None) is not None:
                words.append(attr)
    try:
        from parallelines.cli import _find_queries_dir
        qdir = _find_queries_dir()
        if qdir.is_dir():
            for p in qdir.glob("*.json"):
                if p.name != "README.md":
                    words.append(p.stem)
    except Exception:
        pass
    return WordCompleter(sorted(set(words)), ignore_case=True, sentence=True)
