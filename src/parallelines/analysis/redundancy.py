"""RedundancyAnalyzer — detect files overridden by higher-priority sources."""

from __future__ import annotations

from parallelines.analysis.base import Analyzer
from parallelines.types import AnalysisFragment


class RedundancyAnalyzer(Analyzer):
    """Identifies FileNodes that are overridden by a higher-priority source.

    After VFS resolution, every virtual path has at most one "active" winner.
    All other FileNodes sharing the same virtual_path are marked as redundant.
    This analyzer reports those redundant entries so the user can see what was
    overridden and by whom.
    """

    def analyze(self, vfs, graph) -> AnalysisFragment:
        """Collect all redundant FileNodes from the virtual file system.

        Args:
            vfs: VirtualFileSystem instance (may be None in testing contexts).
            graph: DependencyGraph instance (unused by this analyzer).

        Returns:
            An AnalysisFragment with one item per redundant FileNode.
        """
        if vfs is None:
            return AnalysisFragment(analyzer_name="RedundancyAnalyzer", items=[])

        items: list[dict] = []
        for node in vfs.get_all_files():
            if not node.is_redundant:
                continue

            winner = vfs.get_active_file(node.virtual_path)
            items.append(
                {
                    "virtual_path": node.virtual_path,
                    "source_name": node.source_name,
                    "priority": node.priority,
                    "overridden_by": winner.source_name if winner else None,
                }
            )

        return AnalysisFragment(analyzer_name="RedundancyAnalyzer", items=items)
