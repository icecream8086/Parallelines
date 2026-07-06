"""sv_pure whitelist support — restrict analysis to server-allowed files.

The ``pure_server_whitelist.txt`` file defines which files are allowed on
a sv_pure server.  Patterns use ``fnmatch``-style wildcards (e.g.
``maps/*.bsp``, ``materials/...``).

This module provides loading of whitelist files and filtering of VFS file
sets to simulate a sv_pure server environment.
"""

from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import Iterable

from parallelines.types import FileNode

logger = logging.getLogger(__name__)


def load_pure_whitelist(path: str | Path) -> set[str]:
    """Load a ``pure_server_whitelist.txt`` file and return allowed patterns.

    The parser handles:
    - Comments (``//`` and ``#`` line prefixes)
    - Blank lines (skipped)
    - Whitespace-stripped pattern lines
    - ``*`` and ``?`` wildcards (fnmatch-compatible)
    - The special ``...`` token (matches everything recursively)

    Args:
        path: Filesystem path to the ``pure_server_whitelist.txt`` file.

    Returns:
        A set of allowed path patterns (empty if the file is not found or
        unreadable).
    """
    path_obj = Path(path)
    if not path_obj.exists():
        logger.warning("sv_pure whitelist not found: %s", path)
        return set()

    patterns: set[str] = set()
    try:
        text = path_obj.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            line = line.strip()

            # Strip comments
            comment_pos = -1
            for marker in ("//", "#"):
                idx = line.find(marker)
                if idx != -1 and (comment_pos == -1 or idx < comment_pos):
                    comment_pos = idx
            if comment_pos != -1:
                line = line[:comment_pos].strip()

            if not line:
                continue

            # Handle the special "..." pattern (match everything recursively)
            if line.strip() == "...":
                patterns.add("**")
            else:
                patterns.add(line)

        logger.info(
            "Loaded %d patterns from sv_pure whitelist: %s",
            len(patterns),
            path_obj,
        )
    except Exception as exc:
        logger.warning("Failed to load sv_pure whitelist %s: %s", path, exc)
        return set()

    return patterns


def match_whitelist(virtual_path: str, patterns: set[str]) -> bool:
    """Check if a virtual path matches any of the whitelist patterns.

    The ``**`` pattern (from ``...``) matches all paths.  Otherwise standard
    ``fnmatch`` rules apply.

    Args:
        virtual_path: The virtual path to check (e.g. ``"materials/foo/bar.vtf"``).
        patterns: A set of fnmatch patterns from :func:`load_pure_whitelist`.

    Returns:
        ``True`` if the path matches at least one pattern.
    """
    if not patterns:
        return False

    if "**" in patterns:
        return True

    for pattern in patterns:
        if fnmatch.fnmatch(virtual_path, pattern):
            return True

    return False


def filter_vfs_by_whitelist(
    files: Iterable[FileNode],
    patterns: set[str],
) -> list[FileNode]:
    """Filter a collection of FileNodes to only those matching the whitelist.

    Args:
        files: Iterable of :class:`~parallelines.types.FileNode` instances.
        patterns: Whitelist patterns from :func:`load_pure_whitelist`.

    Returns:
        A list of FileNodes whose virtual paths match at least one pattern.
    """
    if not patterns:
        logger.warning("Empty whitelist patterns -- no files will pass through")
        return []

    if "**" in patterns:
        return list(files)

    result: list[FileNode] = []
    for node in files:
        if match_whitelist(node.virtual_path, patterns):
            result.append(node)

    logger.debug(
        "Whitelist filter: %d / %d files matched",
        len(result),
        len(list(files)),
    )
    return result


def get_pure_whitelist_path(game_root: str | Path) -> Path | None:
    """Return the path to ``pure_server_whitelist.txt`` if it exists.

    The whitelist is searched for under the game root directory.

    Args:
        game_root: The game root directory (containing ``gameinfo.txt``).

    Returns:
        ``Path`` to the whitelist file, or ``None`` if not found.
    """
    candidates = [
        Path(game_root) / "pure_server_whitelist.txt",
        Path(game_root) / "whitelist" / "pure_server_whitelist.txt",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None
