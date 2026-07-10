"""DeadFileAnalyzer — detect files unreachable from any entry point."""

from __future__ import annotations

import icontract

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

    @icontract.ensure(
        lambda self, store: store.files is None
        or not (self.entry_points is not None and store.files is not None
                and any(
                    r.is_dead and r.virtual_path in self.entry_points
                    for r in store.files.rows
                )),
        "入口点不应被标记为 dead"
    )
    def analyze(self, vfs, graph, store: ResultStore) -> None:
        """Mark dead (unreachable) files in the store.

        Computes the set of live paths via a single multi-source BFS, collects
        dead (virtual_path, source_name) keys, then makes one pass over
        ``store.files`` in O(n+m) instead of O(n*m).
        """
        if vfs is None or graph is None or self.entry_points is None:
            return

        # Compute the set of live (reachable) virtual paths.
        reachable = graph.reachable_from_all(self.entry_points)
        live = self.entry_points | reachable

        # Collect dead keys from active VFS nodes not in the live set.
        dead_keys = {
            (n.virtual_path, n.source_name)
            for n in vfs.get_all_active()
            if n.virtual_path not in live
        }

        if not dead_keys:
            return

        # Single pass over store.files to flip the flag.
        for row in store.files.rows:  # type: ignore[union-attr]
            if (row.virtual_path, row.source_name) in dead_keys:
                row.is_dead = True
