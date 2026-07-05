"""RedundancyAnalyzer — detect files overridden by higher-priority sources."""

from __future__ import annotations

from parallelines.analysis.base import Analyzer
from parallelines.engine import ResultStore


class RedundancyAnalyzer(Analyzer):
    """Identifies FileNodes that are overridden by a higher-priority source.

    After VFS resolution, every virtual path has at most one "active" winner.
    All other FileNodes sharing the same virtual_path are marked as redundant.
    This analyzer reports those redundant entries so the user can see what was
    overridden and by whom.
    """

    def analyze(self, vfs, graph, store: ResultStore) -> None:
        """Mark all redundant FileNodes in the store.

        Args:
            vfs: VirtualFileSystem instance (may be None in testing contexts).
            graph: DependencyGraph instance (unused by this analyzer).
            store: ResultStore to write results into.
        """
        if vfs is None:
            return

        for node in vfs.get_all_files():
            if node.is_redundant:
                store.files.update_cell(  # type: ignore[union-attr]
                    lambda r, vp=node.virtual_path, sn=node.source_name: (  # type: ignore[misc]
                        r.virtual_path == vp and r.source_name == sn
                    ),
                    "is_redundant",
                    True,
                )
