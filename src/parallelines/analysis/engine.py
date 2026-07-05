from __future__ import annotations

from typing import List

from parallelines.analysis.base import Analyzer
from parallelines.types import AnalysisReport, AnalysisFragment


class AnalyzerEngine:
    """Orchestrates all registered Analyzer instances."""

    def __init__(self, analyzers: List[Analyzer] | None = None) -> None:
        self.analyzers: List[Analyzer] = analyzers or []

    def register(self, analyzer: Analyzer) -> None:
        """Add a new analyzer to the pipeline."""
        self.analyzers.append(analyzer)

    def run(self, vfs, graph) -> AnalysisReport:
        """Execute all analyzers and collect results."""
        fragments: list[AnalysisFragment] = []
        for analyzer in self.analyzers:
            fragment = analyzer.analyze(vfs, graph)
            fragments.append(fragment)
        return AnalysisReport(fragments=fragments)
