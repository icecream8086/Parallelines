"""ImpactAnalyzer — compute transitive dependency impact for each active file."""

from __future__ import annotations

from parallelines.analysis.base import Analyzer
from parallelines.engine import Relation, ResultStore
from parallelines.engine.schema import ImpactRow
from parallelines.error_policy import parse_failure


class ImpactAnalyzer(Analyzer):
    """Computes how many other active files depend on each file transitively.

    Formal definition:
        Impact(f) = {g ∈ Live | f →* g}

    Results are sorted by impact count descending, capped at ``top_n`` entries.
    """

    def __init__(self, top_n: int = 20):
        self.top_n = top_n

    def analyze(self, vfs, graph, store: ResultStore) -> None:
        """Compute impact for all active files and return the top N.

        Args:
            vfs: VirtualFileSystem instance (may be None in testing contexts).
            graph: DependencyGraph instance (may be None in testing contexts).
            store: ResultStore to write results into.
        """
        if vfs is None or graph is None:
            return

        rows: list[ImpactRow] = []
        for node in vfs.get_all_active():
            try:
                count = len(graph.get_descendants(node.virtual_path))
            except Exception as exc:
                parse_failure(exc, "impact.transitive_closure")
                count = 0

            rows.append(
                ImpactRow(
                    virtual_path=node.virtual_path,
                    source_name=node.source_name,
                    impact_count=count,
                )
            )

        rows.sort(key=lambda r: r.impact_count, reverse=True)
        store.impact = Relation.from_rows("impact", rows[: self.top_n])
