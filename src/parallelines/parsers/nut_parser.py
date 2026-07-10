"""Extract dependencies from .nut Squirrel script files using regex patterns."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Match IncludeScript("path") — captures the path argument.
_INCLUDE_SCRIPT_RE = re.compile(r'IncludeScript\s*\(\s*"([^"]+)"\s*\)')

# Match PrecacheModel("path") — captures the model path argument.
_PRECACHE_MODEL_RE = re.compile(r'PrecacheModel\s*\(\s*"([^"]+)"\s*\)')

# Match PrecacheSound("path") — captures the sound path argument.
_PRECACHE_SOUND_RE = re.compile(r'PrecacheSound\s*\(\s*"([^"]+)"\s*\)')


def _resolve_include_script(raw: str) -> str:
    """Resolve an ``IncludeScript`` argument to a virtual filesystem path.

    - If the path has no file extension, ``.nut`` is appended.
    - If the path has no directory prefix, ``scripts/vscripts/`` is prepended.

    Args:
        raw: The raw path string from ``IncludeScript("...")``.

    Returns:
        Resolved virtual path.
    """
    path = raw.strip().replace("\\", "/")

    if not path.endswith(".nut"):
        path += ".nut"

    if "/" not in path:
        path = "scripts/vscripts/" + path

    return path


def extract_nut_dependencies(file_content: str) -> set[str]:
    """Extract dependency paths from Squirrel (``.nut``) script content.

    Detects the following patterns:

    - ``IncludeScript("path")`` -- script includes, resolved to
      ``scripts/vscripts/`` paths with ``.nut`` extension appended if
      missing.
    - ``PrecacheModel("path")`` -- model precache references, kept as-is.

    Args:
        file_content: The full text content of a ``.nut`` file.

    Returns:
        Set of resolved dependency paths. Empty set on failure.
    """
    try:
        dependencies: set[str] = set()

        for match in _INCLUDE_SCRIPT_RE.finditer(file_content):
            raw = match.group(1)
            dependencies.add(_resolve_include_script(raw))

        for match in _PRECACHE_MODEL_RE.finditer(file_content):
            raw = match.group(1)
            dependencies.add(raw)

        for match in _PRECACHE_SOUND_RE.finditer(file_content):
            raw = match.group(1)
            path = raw.strip().replace("\\", "/")
            if not path.lower().startswith("sound/"):
                path = "sound/" + path
            dependencies.add(path)

        return dependencies

    except Exception as exc:
        logger.warning("Failed to extract .nut dependencies: %s", exc)
        return set()
