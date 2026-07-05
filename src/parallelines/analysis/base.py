from __future__ import annotations

from abc import ABC, abstractmethod

from parallelines.types import AnalysisFragment


class Analyzer(ABC):
    """Base class for all analysis rules."""

    @abstractmethod
    def analyze(self, vfs, graph) -> AnalysisFragment:
        """Run analysis on the given virtual file system and dependency graph.

        Args:
            vfs: VirtualFileSystem instance (resolved active files).
            graph: DependencyGraph instance.

        Returns:
            AnalysisFragment containing results from this analyzer.
        """
        ...
