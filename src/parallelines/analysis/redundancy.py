"""RedundancyAnalyzer — detect files overridden by higher-priority sources."""

from __future__ import annotations

import icontract

from parallelines.analysis.base import Analyzer
from parallelines.engine import ResultStore


class RedundancyAnalyzer(Analyzer):
    """Identifies FileNodes that are overridden by a higher-priority source.

    After VFS resolution, every virtual path has at most one "active" winner.
    All other FileNodes sharing the same virtual_path are marked as redundant.
    This analyzer reports those redundant entries so the user can see what was
    overridden and by whom.
    """

    @icontract.ensure(lambda self, vfs, store: vfs is not None or store.files is None)
    def analyze(self, vfs, graph, store: ResultStore) -> None:
        """Mark all redundant FileNodes in the store.

        Builds a set of (virtual_path, source_name) keys for every redundant
        VFS node, then makes a single pass over ``store.files`` to flip the
        ``is_redundant`` flag in O(n+m) instead of O(n*m).
        """
        if vfs is None:
            return

        redundant_keys = {
            (n.virtual_path, n.source_name)
            for n in vfs.get_all_files()
            if n.is_redundant
        }

        if not redundant_keys:
            return

        for row in store.files.rows:  # type: ignore[union-attr]
            if (row.virtual_path, row.source_name) in redundant_keys:
                row.is_redundant = True
