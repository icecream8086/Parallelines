"""AddonDependencyAnalyzer — check declared dependencies against installed addons."""

from __future__ import annotations

import logging
from typing import Any

from parallelines.analysis.base import Analyzer
from parallelines.parsers.addoninfo import extract_dependency_ids, parse_addoninfo
from parallelines.types import AnalysisFragment

logger = logging.getLogger(__name__)


class AddonDependencyAnalyzer(Analyzer):
    """Check if addons' declared dependencies are actually installed.

    Scans active files for ``addoninfo.txt``, parses each to extract declared
    dependencies (e.g. ``workshop_id``), and cross-references against the set of
    installed addon IDs in the virtual file system.

    Missing dependencies are reported with the addon name, the expected ID,
    and the source VPK or addon folder name.
    """

    def __init__(self, chain=None) -> None:
        """Initialize the analyzer.

        Args:
            chain: Optional ``srctools.filesys.FileSystemChain`` for reading
                   addoninfo.txt content from VPKs.
        """
        self.chain = chain

    def analyze(self, vfs, graph) -> AnalysisFragment:
        """Identify missing addon dependencies.

        Args:
            vfs: :class:`~parallelines.vfs.filesystem.VirtualFileSystem` instance.
            graph: :class:`~parallelines.graph.deps.DependencyGraph` instance
                   (unused by this analyzer).

        Returns:
            An :class:`~parallelines.types.AnalysisFragment` with one item per
            missing dependency.
        """
        if vfs is None:
            return AnalysisFragment(analyzer_name="AddonDependencyAnalyzer", items=[])

        # 1. Collect all installed addon IDs from the VFS
        installed_ids: dict[str, set[str]] = {}  # addon_id -> source_names
        for node in vfs.get_all_active():
            if node.addon_id:
                installed_ids.setdefault(node.addon_id, set()).add(node.source_name)
            # Also capture the VPK source_name as a fallback identifier
            if node.source_name:
                installed_ids.setdefault(node.source_name, set()).add(node.source_name)

        # 2. Find all addoninfo.txt files among active files and parse them
        items: list[dict[str, Any]] = []
        addoninfo_files = [
            node
            for node in vfs.get_all_active()
            if node.virtual_path.lower().endswith("addoninfo.txt")
        ]

        if not addoninfo_files:
            logger.debug("No addoninfo.txt files found in active VFS")
            return AnalysisFragment(analyzer_name="AddonDependencyAnalyzer", items=[])

        for node in addoninfo_files:
            addon_name = node.source_name
            declared_deps = self._parse_addoninfo_deps(node)
            if not declared_deps:
                continue

            for dep_id in declared_deps:
                # Check if the dependency is installed
                if dep_id not in installed_ids:
                    items.append(
                        {
                            "addon": addon_name,
                            "virtual_path": node.virtual_path,
                            "missing_dependency_id": dep_id,
                            "severity": "warning",
                        }
                    )
                else:
                    dep_sources = installed_ids[dep_id]
                    logger.debug(
                        "Addon '%s' dependency %s satisfied by %s",
                        addon_name,
                        dep_id,
                        ", ".join(sorted(dep_sources)),
                    )

        if not items:
            logger.info("All declared addon dependencies are satisfied")

        return AnalysisFragment(analyzer_name="AddonDependencyAnalyzer", items=items)

    def _parse_addoninfo_deps(self, node: Any) -> list[str]:
        """Read addoninfo.txt content through the FileSystemChain and extract dependency IDs.

        Args:
            node: A FileNode whose virtual_path points to addoninfo.txt.

        Returns:
            A list of declared dependency identifier strings (empty if the chain is
            unavailable or parsing fails).
        """
        if self.chain is None:
            logger.debug("No chain available; cannot read %s", node.virtual_path)
            return []
        try:
            file_obj = self.chain[node.virtual_path]
            content = file_obj.open_str().read()
        except Exception:
            logger.debug("Failed to read %s via chain", node.virtual_path)
            return []

        meta = parse_addoninfo(content)
        return extract_dependency_ids(meta)
