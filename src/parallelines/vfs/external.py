"""ExternalVpkOverlay — simulate injecting an external .vpk into the VFS for what-if conflict analysis.

This module provides a non-destructive overlay mechanism to answer:
"What would happen if I installed this VPK into my current game environment?"

The base VFS is never modified; all analysis is performed on a temporary copy.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

from parallelines.exceptions import ParseError
from parallelines.parsers.vpk_parser import parse_vpk_index
from parallelines.types import FileNode
from parallelines.vfs.filesystem import VirtualFileSystem

logger = logging.getLogger(__name__)


class ExternalVpkOverlay:
    """Simulate injecting an external .vpk into an existing VFS for conflict analysis.

    The base VFS is never modified — a temporary overlay is created for analysis.

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

    def analyze(self) -> dict[str, Any]:
        """Run diff analysis and return a report dict.

        Compares the base VFS (before) against the overlay VFS (after) to
        categorise every file in the external VPK.

        Returns
        -------
        dict with keys:

        ``external_vpk``
            File name of the external VPK.
        ``injected_priority``
            The simulated priority value used.
        ``summary``
            ``{"total_files_in_vpk": N, "will_override": N,
              "will_be_overridden": N, "new_files": N}``
        ``overrides``
            List of files the external VPK **will** override (external wins).
            Each item: ``{"virtual_path": ..., "existing_source": ...,
            "existing_priority": ..., "file_size": ..., "external_hash": ...}``
        ``will_be_overridden``
            List of files the external VPK provides but existing files win.
        ``new_files``
            List of files in the external VPK that do not conflict with anything.
        ``error``
            Present only when the VPK could not be parsed.
        """
        # Parse the external VPK index.
        try:
            entries = parse_vpk_index(self.vpk_path)
        except ParseError as exc:
            return {
                "external_vpk": self.vpk_path.name,
                "injected_priority": self.priority,
                "error": str(exc),
                "summary": {
                    "total_files_in_vpk": 0,
                    "will_override": 0,
                    "will_be_overridden": 0,
                    "new_files": 0,
                },
                "overrides": [],
                "will_be_overridden": [],
                "new_files": [],
            }

        will_override: list[dict[str, Any]] = []
        will_be_overridden: list[dict[str, Any]] = []
        new_files: list[dict[str, Any]] = []

        for entry in entries:
            vpath = entry["virtual_path"]
            existing = self.base_vfs.get_active_file(vpath)

            file_info: dict[str, Any] = {
                "virtual_path": vpath,
                "file_size": entry.get("file_size", 0),
                "external_hash": entry.get("crc"),
            }

            if existing is None:
                # Path does not exist in the base environment → truly new.
                new_files.append(file_info)
            elif existing.priority < self.priority:
                # External VPK has higher priority → it will override the current file.
                file_info["existing_source"] = existing.source_name
                file_info["existing_priority"] = existing.priority
                will_override.append(file_info)
            else:
                # Existing file has higher (or equal) priority → external file is overridden.
                file_info["existing_source"] = existing.source_name
                file_info["existing_priority"] = existing.priority
                will_be_overridden.append(file_info)

        summary = {
            "total_files_in_vpk": len(entries),
            "will_override": len(will_override),
            "will_be_overridden": len(will_be_overridden),
            "new_files": len(new_files),
        }

        return {
            "external_vpk": self.vpk_path.name,
            "injected_priority": self.priority,
            "summary": summary,
            "overrides": will_override,
            "will_be_overridden": will_be_overridden,
            "new_files": new_files,
        }
