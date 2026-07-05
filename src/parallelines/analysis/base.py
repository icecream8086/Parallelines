from __future__ import annotations

from abc import ABC, abstractmethod

from parallelines.engine import ResultStore


class Analyzer(ABC):
    """Base class for all analysis rules."""

    @abstractmethod
    def analyze(self, vfs, graph, store: ResultStore) -> None:
        """Run analysis on the given virtual file system and dependency graph.

        Args:
            vfs: VirtualFileSystem instance (resolved active files).
            graph: DependencyGraph instance.
            store: ResultStore instance to populate with results.
        """
        ...
