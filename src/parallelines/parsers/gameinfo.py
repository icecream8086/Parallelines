"""Parse gameinfo.txt — extract SearchPaths, Game dirs, addon roots.

Uses ``srctools.keyvalues.Keyvalues`` which handles C++-style comments
and VDF quirks across all Source Engine games.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from parallelines.error_policy import parse_failure
from parallelines.exceptions import ParseError
from parallelines.io import FileReader

logger = logging.getLogger(__name__)

try:
    from srctools.keyvalues import Keyvalues

    SRCTOOLS_AVAILABLE = True
except ImportError:
    SRCTOOLS_AVAILABLE = False
    Keyvalues = None  # type: ignore[assignment]


def parse_gameinfo(path: str | Path) -> dict[str, Any]:
    """Parse a gameinfo.txt VDF file and return the content as nested dicts.

    Args:
        path: Path to the gameinfo.txt file.

    Returns:
        Parsed content as nested ``{name: value}`` dicts.

    Raises:
        ParseError: If the file cannot be read or parsed.
    """
    if not SRCTOOLS_AVAILABLE:
        raise ParseError("srctools is not installed; cannot parse gameinfo.txt")

    path_obj = Path(path)
    if not path_obj.exists():
        raise ParseError(f"gameinfo.txt not found: {path}")

    try:
        text = FileReader.read_game_text(path_obj)
        kv = Keyvalues.parse(text)
    except Exception as exc:
        raise ParseError(f"Failed to parse gameinfo.txt at {path}: {exc}") from exc

    return _kv_to_dict(kv)


def _kv_to_dict(kv: Any) -> dict[str, Any]:
    """Convert a Keyvalues tree to plain dicts."""
    result: dict[str, Any] = {}
    try:
        for child in kv:
            name = str(child.name).lower()
            if isinstance(child.value, list):
                result[name] = _kv_list_to_dicts(child.value)
            else:
                result[name] = str(child.value)
    except Exception as exc:
        parse_failure(exc, "gameinfo.kv_to_dict")
    return result


def _kv_list_to_dicts(children: list[Any]) -> dict[str, Any] | list[str]:
    """Convert a list of Keyvalues children.

    If all children share the same key name, collapse to a list of values
    (handles duplicate keys like multiple ``Game`` entries).
    Otherwise return a merged dict.
    """
    if not children:
        return {}

    # Check if all children have the same name (e.g. all "Game")
    names = [str(c.name) for c in children]
    if len(set(names)) == 1:
        name = names[0]
        values: list[Any] = []
        for c in children:
            if isinstance(c.value, list):
                values.append(_kv_list_to_dicts(c.value))
            else:
                values.append(str(c.value))
        return {name: values if len(values) > 1 else values[0]}

    result: dict[str, Any] = {}
    for child in children:
        name = str(child.name)
        if isinstance(child.value, list):
            result[name] = _kv_list_to_dicts(child.value)
        else:
            # Handle duplicate keys by converting to list
            if name in result:
                existing = result[name]
                if isinstance(existing, list):
                    existing.append(str(child.value))
                else:
                    result[name] = [existing, str(child.value)]
            else:
                result[name] = str(child.value)
    return result


def extract_search_paths(gameinfo: dict[str, Any]) -> dict[str, Any]:
    """Extract the ``FileSystem > SearchPaths`` section from the GameInfo dict.

    Handles the common VDF root-key wrapping (e.g. ``{"gameinfo": {"filesystem":
    ...}}``) by unwrapping the single root key before extraction.
    """
    try:
        # The parsed result is often wrapped under the root key (e.g. "gameinfo").
        # Unwrap it so callers don't need to know about the VDF container format.
        if len(gameinfo) == 1:
            inner = next(iter(gameinfo.values()))
            if isinstance(inner, dict):
                fs: dict[str, Any] = inner.get("filesystem", {})
                sp: dict[str, Any] = fs.get("searchpaths", {})
                return dict(sp)
        fs = gameinfo.get("filesystem", {})
        sp = fs.get("searchpaths", {})
        return dict(sp)
    except Exception as exc:
        parse_failure(exc, "gameinfo.extract_search_paths")
        return {}


def extract_game_dirs(search_paths: dict[str, Any]) -> list[str]:
    """Extract ``Game`` directory entries from SearchPaths."""
    result: list[str] = []
    try:
        game_entries = search_paths.get("game", [])
        if isinstance(game_entries, str):
            result.append(game_entries)
        elif isinstance(game_entries, list):
            result.extend(str(v) for v in game_entries)
    except Exception as exc:
        parse_failure(exc, "gameinfo.extract_game_dirs")
    return result


def extract_vpk_mounts(search_paths: dict[str, Any]) -> list[str]:
    """Deprecated — kept for compatibility.  Use :func:`extract_game_dirs`."""
    return extract_game_dirs(search_paths)


def extract_all_game_dirs(search_paths: dict[str, Any]) -> list[tuple[str, str]]:
    """Extract all ``Game*`` entries, returning ``(token, path)`` pairs.

    Unlike :func:`extract_game_dirs`, this preserves the original token name
    (e.g. ``"game update"``) so the caller can decide how to handle each
    search-path type.
    """
    result: list[tuple[str, str]] = []
    try:
        for key, value in search_paths.items():
            key_lower = key.lower()
            if key_lower.startswith("game"):
                if isinstance(value, str):
                    result.append((key_lower, value))
                elif isinstance(value, list):
                    for v in value:
                        result.append((key_lower, str(v)))
    except Exception as exc:
        parse_failure(exc, "gameinfo.extract_all_game_dirs")
    return result


def extract_addon_roots(search_paths: dict[str, Any]) -> list[str]:
    """Extract search path values containing ``addon``."""
    result: list[str] = []
    try:
        for key, value in search_paths.items():
            if "addon" in key.lower():
                if isinstance(value, str):
                    result.append(value)
                elif isinstance(value, list):
                    result.extend(str(v) for v in value)
    except Exception as exc:
        parse_failure(exc, "gameinfo.extract_addon_roots")
    return result
