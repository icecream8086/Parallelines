"""ExternalVpkOverlay — simulate injecting an external .vpk into the VFS for what-if conflict analysis.

This module provides a non-destructive overlay mechanism to answer:
"What would happen if I installed this VPK into my current game environment?"

The base VFS is never modified; all analysis is performed on a temporary copy.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from parallelines.exceptions import ParseError
from parallelines.parsers.vpk_parser import parse_vpk_index
from parallelines.types import FileNode
from parallelines.vfs.filesystem import VirtualFileSystem

logger = logging.getLogger(__name__)


class ExternalVpkOverlay:
    """Simulate injecting an external .vpk into an existing VFS for conflict analysis.

    The base VFS is never modified -- a temporary overlay is created for analysis.

    Parameters
    ----------
    base_vfs:
        The resolved VirtualFileSystem representing the current game environment.
    vpk_path:
        Path to the external ``.vpk`` file to analyze.
    priority:
        Simulated priority for the external VPK's files.  Higher values win
        during VFS resolution when multiple sources provide the same virtual path.
    """

    def __init__(
        self,
        base_vfs: VirtualFileSystem,
        vpk_path: str | Path,
        priority: int = 0,
    ) -> None:
        self.base_vfs = base_vfs
        self.vpk_path = Path(vpk_path)
        self.priority = priority

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_overlay(self) -> VirtualFileSystem:
        """Return a temporary VFS that merges *base_vfs* with the external VPK.

        Steps:
        1. Parse the external VPK's file index.
        2. Create a fresh VFS and copy all base-VFS FileNodes into it.
        3. Inject the external VPK's files at ``self.priority``.
        4. Call :meth:`~VirtualFileSystem.resolve` to determine winners.
        5. Return the overlay VFS.

        The base VFS is never mutated; all FileNodes are shallow-copied.
        """
        overlay = VirtualFileSystem()

        # Copy every FileNode from the base pool (detached copies).
        for node in self.base_vfs.get_all_files():
            overlay.add_file(replace(node))

        # Parse and inject external VPK entries.
        try:
            entries = parse_vpk_index(self.vpk_path)
        except ParseError as exc:
            logger.error("Failed to parse external VPK '%s': %s", self.vpk_path, exc)
            return overlay

        source_name = self.vpk_path.name
        for entry in entries:
            ext_node = FileNode(
                virtual_path=entry["virtual_path"],
                source_type="vpk",
                source_name=source_name,
                source_path=str(self.vpk_path.resolve()),
                priority=self.priority,
                file_size=entry.get("file_size", 0),
                file_hash=entry.get("crc"),
            )
            overlay.add_file(ext_node)

        overlay.resolve()

        logger.debug(
            "Overlay built: %d base files + %d external VPK files",
            len(self.base_vfs.get_all_files()),
            len(entries),
        )

        return overlay

    # analyze() has been removed in S9 — use ResultStore.load_reference() +
    # preset queries (cli.py) for external VPK comparison.
