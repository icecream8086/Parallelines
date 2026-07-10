"""Simple line-based list parser for sound_prefetch.txt and similar files."""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


def parse_simple_list(file_content: str, prefix: str = "") -> set[str]:
    """Parse a simple line-based list file (one path per line, no KeyValues).

    Skips empty lines and comment lines starting with ``//`` or ``#``.
    Optionally prepends a path prefix to non-absolute entries.

    Args:
        file_content: Raw text content of the list file.
        prefix: Optional path prefix to add if the entry doesn't already start with it.

    Returns:
        Set of normalized dependency paths.
    """
    deps: set[str] = set()
    try:
        for line in file_content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("//", "#")):
                continue
            path = stripped.replace("\\", "/")
            if prefix and not path.lower().startswith(prefix.lower()):
                path = prefix + path
            deps.add(path)
        return deps
    except Exception as exc:
        logger.warning("Failed to parse simple list: %s", exc)
        return set()
