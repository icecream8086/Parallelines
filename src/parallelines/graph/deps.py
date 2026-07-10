"""Dependency graph — NetworkX DiGraph wrapper."""

from __future__ import annotations

import os

_SHOULD_CHECK = os.environ.get("PARALLELINES_NO_CONTRACTS", "").lower() not in ("1", "true", "yes")

if _SHOULD_CHECK:
    import icontract

    _ensure = icontract.ensure
else:

    def _ensure(*args, **kwargs):  # type: ignore[misc]
        def wrapper(f):
            return f
        return wrapper


import networkx as nx


class DependencyGraph:
    """Wrapper around a NetworkX directed graph for dependency tracking.

    Supports freezing the graph to prevent further mutations.
    """

    def __init__(self) -> None:
        self._graph: nx.DiGraph = nx.DiGraph()
        self._frozen: bool = False

    def add_edges(self, edges: list[tuple[str, str]]) -> None:
        """Bulk-add directed edges.

        Each tuple is (source, target) meaning *source depends on target*.

        Raises:
            RuntimeError: If the graph has been frozen.
        """
        if self._frozen:
            raise RuntimeError("Cannot add edges to a frozen graph")
        self._graph.add_edges_from(edges)

    def add_node(self, node_id: str, **attrs) -> None:
        """Add a single node with optional attributes.

        Raises:
            RuntimeError: If the graph has been frozen.
        """
        if self._frozen:
            raise RuntimeError("Cannot add nodes to a frozen graph")
        self._graph.add_node(node_id, **attrs)

    @_ensure(lambda self: self._frozen)
    def freeze(self) -> None:
        """Prevent further mutations to the graph."""
        self._frozen = True
        self._graph = nx.freeze(self._graph)

    @_ensure(lambda result, node: node not in result)
    def get_descendants(self, node: str) -> set[str]:
        """Return all nodes reachable from *node* via directed edges."""
        return nx.descendants(self._graph, node)

    def get_ancestors(self, node: str) -> set[str]:
        """Return all nodes that can reach *node* via directed edges."""
        return nx.ancestors(self._graph, node)

    def has_path(self, source: str, target: str) -> bool:
        """Return True if there is a directed path from *source* to *target*."""
        return nx.has_path(self._graph, source, target)

    def reachable_from_all(self, sources: set[str]) -> set[str]:
        """Return the union of all nodes reachable from any source.

        Performs a multi-source traversal by computing descendants for each
        source and returning their union.  Sources not present in the graph
        are silently skipped.
        """
        result: set[str] = set()
        for source in sources:
            if source not in self._graph:
                continue
            try:
                result |= nx.descendants(self._graph, source)
            except Exception:
                continue
        return result

    @property
    @_ensure(lambda result: result >= 0)
    def node_count(self) -> int:
        """Return the number of nodes in the graph."""
        return self._graph.number_of_nodes()

    @property
    @_ensure(lambda result: result >= 0)
    def edge_count(self) -> int:
        """Return the number of edges in the graph."""
        return self._graph.number_of_edges()

    @property
    def graph(self) -> nx.DiGraph:
        """Return the internal NetworkX DiGraph (read-only access)."""
        return self._graph
