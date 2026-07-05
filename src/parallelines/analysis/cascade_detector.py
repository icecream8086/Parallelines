"""Detect cascade overrides — paths with 3+ providers."""

from __future__ import annotations

from collections import defaultdict

from parallelines.analysis.base import Analyzer
from parallelines.engine import Relation, ResultStore
from parallelines.engine.schema import CascadeOverrideRow


class CascadeDetector(Analyzer):
    """Find virtual_paths with 3 or more providers forming an override chain."""

    def analyze(self, vfs, graph, store: ResultStore) -> None:
        if store.files is None:
            return
        path_to_rows = defaultdict(list)
        for row in store.files.rows:
            path_to_rows[row.virtual_path].append(row)

        cascades = []
        for vpath, nodes in path_to_rows.items():
            if len(nodes) < 3:
                continue
            chain = sorted(nodes, key=lambda n: n.priority, reverse=True)
            cascades.append(
                CascadeOverrideRow(
                    virtual_path=vpath,
                    chain_sources=[n.source_name for n in chain],
                    chain_priorities=[n.priority for n in chain],
                    active_source=chain[0].source_name,
                )
            )

        if cascades:
            store.cascade_overrides = Relation.from_rows("cascade_overrides", cascades)
