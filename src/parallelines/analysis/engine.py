from __future__ import annotations

from typing import List

from parallelines.analysis.base import Analyzer
from parallelines.engine import ResultStore


class AnalyzerEngine:
    """Orchestrates all registered Analyzer instances."""

    def __init__(self, analyzers: List[Analyzer] | None = None) -> None:
        self.analyzers: List[Analyzer] = analyzers or []

    def register(self, analyzer: Analyzer) -> None:
        """Add a new analyzer to the pipeline."""
        self.analyzers.append(analyzer)

    def run(self, vfs, graph, store: ResultStore) -> ResultStore:
        """Execute all analyzers and collect results."""
        for analyzer in self.analyzers:
            analyzer.analyze(vfs, graph, store)
        return store
