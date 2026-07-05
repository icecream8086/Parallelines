"""IsolatedPackageAnalyzer — detect addons/packages where all files are dead."""

from __future__ import annotations

from collections import Counter

from parallelines.analysis.base import Analyzer
from parallelines.types import AnalysisFragment


class IsolatedPackageAnalyzer(Analyzer):
    """Identifies sources (addons / VPKs) where every file is marked as dead.

    A package whose every file is dead contributes nothing to the final build
    and can likely be disabled or removed entirely.  This analyzer reports both
    fully-isolated packages and partially-dead ones so the user can decide
    whether to clean them up.
    """

    def analyze(self, vfs, graph) -> AnalysisFragment:
        """Group all files by source and flag sources with 100 % dead files.

        Args:
            vfs: VirtualFileSystem instance.
            graph: DependencyGraph instance (unused by this analyzer).

        Returns:
            An AnalysisFragment with one item per source.
        """
        if vfs is None:
            return AnalysisFragment(analyzer_name="IsolatedPackageAnalyzer", items=[])

        all_files = vfs.get_all_files()

        # Count total files and dead files per source.
        total_counter: Counter[str] = Counter()
        dead_counter: Counter[str] = Counter()

        for node in all_files:
            total_counter[node.source_name] += 1
            if node.is_dead:
                dead_counter[node.source_name] += 1

        items: list[dict] = []
        for source_name in sorted(total_counter):
            total = total_counter[source_name]
            dead = dead_counter[source_name]
            isolated = total > 0 and dead == total
            items.append(
                {
                    "source_name": source_name,
                    "total_files": total,
                    "dead_files": dead,
                    "reason": "all_files_dead" if isolated else "partial",
                }
            )

        return AnalysisFragment(analyzer_name="IsolatedPackageAnalyzer", items=items)
