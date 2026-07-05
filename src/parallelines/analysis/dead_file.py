"""DeadFileAnalyzer — detect files unreachable from any entry point."""

from __future__ import annotations

from parallelines.analysis.base import Analyzer
from parallelines.engine import ResultStore


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

    def analyze(self, vfs, graph, store: ResultStore) -> None:
        """Mark dead (unreachable) files in the store.

        Args:
            vfs: VirtualFileSystem instance.
            graph: DependencyGraph instance.
            store: ResultStore to write results into.
        """
        if vfs is None or graph is None or self.entry_points is None:
            return

        # Compute the set of live (reachable) virtual paths.
        reachable = graph.reachable_from_all(self.entry_points)
        live = self.entry_points | reachable

        # Anything active but not in the live set is dead.
        for node in vfs.get_all_active():
            if node.virtual_path not in live:
                store.files.update_cell(  # type: ignore[union-attr]
                    lambda r, vp=node.virtual_path, sn=node.source_name: (  # type: ignore[misc]
                        r.virtual_path == vp and r.source_name == sn
                    ),
                    "is_dead",
                    True,
                )
