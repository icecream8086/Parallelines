"""Parse Source engine manifest files (soundscapes, particles, etc.)."""

from __future__ import annotations

import logging
from pathlib import Path

from parallelines.exceptions import ParseError

logger = logging.getLogger(__name__)


def parse_manifest(manifest_path: str | Path) -> list[str]:
    """Read a manifest text file and return non-comment, non-empty lines.

    Lines are stripped of leading/trailing whitespace. Lines starting with
    ``//`` or ``#`` are treated as comments and skipped, as are completely
    empty lines.

    Args:
        manifest_path: Path to the manifest file.

    Returns:
        List of path strings found in the manifest. Empty list on failure.
    """
    try:
        path_obj = Path(manifest_path)
        lines: list[str] = []

        with path_obj.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("//") or stripped.startswith("#"):
                    continue
                lines.append(stripped)

        return lines

    except FileNotFoundError:
        raise ParseError(f"Manifest file not found: {manifest_path}")
    except Exception as exc:
        raise ParseError(f"Failed to parse manifest at {manifest_path}: {exc}")


def is_manifest_path(path: str) -> bool:
    """Return ``True`` if the path looks like a known Source engine manifest filename.

    A path is considered a manifest if its lowercase form contains the word
    ``manifest`` and it ends with ``.txt``.

    Args:
        path: The file path to check.

    Returns:
        ``True`` if the path matches the manifest naming pattern.
    """
    try:
        lower = path.lower()
        return "manifest" in lower and lower.endswith(".txt")
    except Exception:
        return False
