"""ImpactAnalyzer — compute transitive dependency impact for each active file."""

from __future__ import annotations

from parallelines.analysis.base import Analyzer
from parallelines.types import AnalysisFragment


class ImpactAnalyzer(Analyzer):
    """Computes how many other active files depend on each file transitively.

    Formal definition:
        Impact(f) = {g ∈ Live | f →* g}

    Results are sorted by impact count descending, capped at ``top_n`` entries.
    """

    def __init__(self, top_n: int = 20):
        self.top_n = top_n

    def analyze(self, vfs, graph) -> AnalysisFragment:
        """Compute impact for all active files and return the top N.

        Args:
            vfs: VirtualFileSystem instance (may be None in testing contexts).
            graph: DependencyGraph instance (may be None in testing contexts).

        Returns:
            An AnalysisFragment with up to ``top_n`` items sorted by impact
            descending.
        """
        if vfs is None or graph is None:
            return AnalysisFragment(analyzer_name="ImpactAnalyzer", items=[])

        active_files = vfs.get_all_active()

        impacts: list[dict] = []
        for node in active_files:
            try:
                descendants = graph.get_descendants(node.virtual_path)
                count = len(descendants)
            except Exception:
                count = 0

            if count > 100:
                impact_analysis = f"高影响面 — 修改将影响 {count} 个文件"
            elif count > 10:
                impact_analysis = "中等影响"
            else:
                impact_analysis = "低影响"

            impacts.append(
                {
                    "virtual_path": node.virtual_path,
                    "impact_count": count,
                    "source_name": node.source_name,
                    "impact_analysis": impact_analysis,
                }
            )

        # Sort by impact_count descending and take the top N.
        impacts.sort(key=lambda x: x["impact_count"], reverse=True)
        impacts = impacts[: self.top_n]

        return AnalysisFragment(analyzer_name="ImpactAnalyzer", items=impacts)
