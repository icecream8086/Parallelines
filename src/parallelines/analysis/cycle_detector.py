"""Detect cycles in the dependency graph."""

from __future__ import annotations

import networkx as nx

from parallelines.analysis.base import Analyzer
from parallelines.engine import Relation, ResultStore
from parallelines.engine.schema import DependencyCycleRow


class CycleDetector(Analyzer):
    """Find all simple cycles in the dependency graph."""

    def analyze(self, vfs, graph, store: ResultStore) -> None:
        if store.graph is None:
            return
        try:
            cycles = list(nx.simple_cycles(store.graph))
        except nx.NetworkXError:
            cycles = []
        rows = [DependencyCycleRow(cycle=list(c), length=len(c)) for c in cycles]
        if rows:
            store.dependency_cycles = Relation.from_rows("dependency_cycles", rows)
