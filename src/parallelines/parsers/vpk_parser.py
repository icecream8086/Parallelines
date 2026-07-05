"""Parse .vpk file indexes — extract file list and hashes.

Uses ``srctools.vpk.VPK`` which supports both VPK v1 and v2 formats
across all Source Engine games (L4D2, CS:GO, TF2, Portal 2, Dota 2, etc.).

Does NOT support:
- Respawn-modified VPKs (Titanfall)
- Non-Source .vpk files (Vampire: The Masquerade – Bloodlines)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from parallelines.exceptions import ParseError

logger = logging.getLogger(__name__)

try:
    from srctools.vpk import VPK as _VPK

    SRCTOOLS_AVAILABLE = True
except ImportError:
    logger.warning("srctools not installed; VPK parsing disabled.")
    SRCTOOLS_AVAILABLE = False
    _VPK = None  # type: ignore[assignment]


def parse_vpk_index(vpk_path: str | Path) -> list[dict[str, Any]]:
    """Open a .vpk file and extract its full file index.

    Returns a list of dicts with keys ``virtual_path``, ``file_size``, and
    ``crc`` (hex string).  Returns an empty list if srctools is unavailable
    or the VPK cannot be parsed.

    Raises:
        ParseError: If the file does not exist.
    """
    path_obj = Path(vpk_path)

    if not path_obj.exists():
        raise ParseError(f"VPK file not found: {vpk_path}")
    if not SRCTOOLS_AVAILABLE:
        raise ParseError("srctools is not available, cannot parse VPK files")

    try:
        archive = _VPK(path_obj)
        entries: list[dict[str, Any]] = []

        for info in archive:
            entries.append(
                {
                    "virtual_path": info.filename,
                    "file_size": info.size,
                    "crc": f"{info.crc:08x}" if info.crc else None,
                }
            )

        return entries

    except Exception as exc:
        raise ParseError(f"Failed to parse VPK index at {vpk_path}: {exc}") from exc
