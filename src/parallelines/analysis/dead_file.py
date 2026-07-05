"""DeadFileAnalyzer — detect files unreachable from any entry point."""

from __future__ import annotations

from parallelines.analysis.base import Analyzer
from parallelines.types import AnalysisFragment


class DeadFileAnalyzer(Analyzer):
    """Identifies active files that are unreachable from any configured entry point.

    A "dead" file is one that exists in the active (resolved) VFS but is not
    transitively depended upon by any of the specified entry points.  These
    files can often be removed or moved to a lazy-loading path with no change
    in behaviour.
    """

    def __init__(self, entry_points: set[str] | None = None) -> None:
        """Configure the set of entry-point virtual paths.

        Args:
            entry_points: Optional set of virtual paths that serve as roots
                for the reachability traversal.  When ``None`` (the default)
                every active file is considered live.
        """
        self.entry_points = entry_points

    def analyze(self, vfs, graph) -> AnalysisFragment:
        """Find and mark active files not reachable from the entry points.

        Args:
            vfs: VirtualFileSystem instance.
            graph: DependencyGraph instance.

        Returns:
            An AnalysisFragment with one item per dead file.
        """
        if vfs is None or graph is None:
            return AnalysisFragment(analyzer_name="DeadFileAnalyzer", items=[])

        active_files = vfs.get_all_active()

        # No explicit entry points → everything is assumed live.
        if self.entry_points is None:
            return AnalysisFragment(analyzer_name="DeadFileAnalyzer", items=[])

        # Compute the set of live (reachable) virtual paths.
        reachable = graph.reachable_from_all(self.entry_points)
        live = self.entry_points | reachable

        # Anything active but not in the live set is dead.
        items: list[dict] = []
        for node in active_files:
            if node.virtual_path not in live:
                node.is_dead = True
                items.append(
                    {
                        "virtual_path": node.virtual_path,
                        "source_name": node.source_name,
                    }
                )

        return AnalysisFragment(analyzer_name="DeadFileAnalyzer", items=items)
