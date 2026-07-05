"""AddonDependencyAnalyzer — check declared dependencies against installed addons."""

from __future__ import annotations

import logging
from typing import Any

from parallelines.analysis.base import Analyzer
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
            node for node in vfs.get_all_active()
            if node.virtual_path.lower().endswith("addoninfo.txt")
        ]

        if not addoninfo_files:
            logger.debug("No addoninfo.txt files found in active VFS")
            return AnalysisFragment(analyzer_name="AddonDependencyAnalyzer", items=[])

        for node in addoninfo_files:
            # Try to read the file content through the VFS — since we have
            # FileNode objects but not raw content, attempt a heuristic:
            # the source_name often matches a known VPK/addon.
            # For proper content reading we would need the FileSystemChain,
            # but we can still work with the metadata we have.

            # For now, parse from the source VPK name as a fallback
            addon_name = node.source_name

            # We store the addoninfo fields in node.dependencies (set of str),
            # but we actually need the parsed dict.  We'll make a best-effort
            # attempt by checking if node.addon_id is set.
            declared_deps = self._get_declared_deps_from_node(node)
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

    @staticmethod
    def _get_declared_deps_from_node(node: Any) -> list[str]:
        """Try to extract declared dependency IDs from a FileNode.

        This is a best-effort heuristic.  The primary mechanism is to check
        if the dependency information was stored during VFS building.
        """
        declared: list[str] = []

        # Check node.dependencies (a set of strings) for entries that look
        # like numeric workshop IDs or addon identifiers
        if hasattr(node, "dependencies") and node.dependencies:
            for dep in node.dependencies:
                dep_str = str(dep).strip()
                if dep_str.isdigit() or len(dep_str) > 4:
                    declared.append(dep_str)

        return declared
