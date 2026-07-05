"""Tests for parallelines.graph.deps — DependencyGraph."""

from __future__ import annotations

import unittest

import networkx as nx

from parallelines.graph.deps import DependencyGraph


class TestDependencyGraph(unittest.TestCase):
    """Verify DependencyGraph add, query, and freeze behaviour."""

    def setUp(self) -> None:
        self.graph = DependencyGraph()

    def test_empty_graph(self) -> None:
        """A freshly created graph should have zero nodes and edges."""
        self.assertEqual(self.graph.node_count, 0)
        self.assertEqual(self.graph.edge_count, 0)

    def test_add_edges(self) -> None:
        """Add edges and verify counts."""
        edges = [
            ("maps/c1m1_hotel.bsp", "materials/brick/brick.vtf"),
            ("maps/c1m1_hotel.bsp", "models/props/chair/chair.mdl"),
            ("maps/c1m2_streets.bsp", "materials/brick/brick.vtf"),
        ]
        self.graph.add_edges(edges)
        self.assertEqual(self.graph.node_count, 4)
        self.assertEqual(self.graph.edge_count, 3)

    def test_get_descendants(self) -> None:
        """Verify transitive closure (descendants)."""
        self.graph.add_edges([
            ("A", "B"),
            ("B", "C"),
            ("C", "D"),
        ])
        descendants = self.graph.get_descendants("A")
        self.assertSetEqual(descendants, {"B", "C", "D"})

    def test_get_ancestors(self) -> None:
        """Verify reverse traversal (ancestors)."""
        self.graph.add_edges([
            ("A", "B"),
            ("B", "C"),
            ("C", "D"),
        ])
        ancestors = self.graph.get_ancestors("D")
        self.assertSetEqual(ancestors, {"A", "B", "C"})

    def test_has_path(self) -> None:
        """Verify path existence between nodes."""
        self.graph.add_edges([
            ("root.nut", "materials/brick.vtf"),
            ("materials/brick.vtf", "materials/brick_normal.vtf"),
        ])
        self.assertTrue(self.graph.has_path("root.nut", "materials/brick_normal.vtf"))
        self.assertFalse(self.graph.has_path("materials/brick_normal.vtf", "root.nut"))

    def test_reachable_from_all(self) -> None:
        """Verify multi-source BFS reachable_from_all."""
        self.graph.add_edges([
            ("A", "B"),
            ("A", "C"),
            ("D", "E"),
            ("C", "F"),
        ])
        result = self.graph.reachable_from_all({"A", "D"})
        self.assertSetEqual(result, {"B", "C", "E", "F"})

    def test_reachable_from_all_missing_source(self) -> None:
        """Sources not in the graph are silently skipped."""
        self.graph.add_edges([
            ("A", "B"),
        ])
        result = self.graph.reachable_from_all({"A", "NONEXISTENT"})
        self.assertSetEqual(result, {"B"})

    def test_freeze(self) -> None:
        """Frozen graph should reject mutations."""
        self.graph.add_edges([("A", "B")])
        self.graph.freeze()

        with self.assertRaises(RuntimeError):
            self.graph.add_edges([("B", "C")])

        with self.assertRaises(RuntimeError):
            self.graph.add_node("Z")

    def test_add_node(self) -> None:
        """Add a single node with optional attributes."""
        self.graph.add_node("standalone_node", file_size=1234)
        self.assertEqual(self.graph.node_count, 1)
        self.assertEqual(self.graph.edge_count, 0)
        # Node attributes should be stored internally
        self.assertIn("standalone_node", self.graph.graph.nodes)
        self.assertEqual(
            self.graph.graph.nodes["standalone_node"]["file_size"], 1234
        )

    def test_get_descendants_no_edges(self) -> None:
        """A node with no outgoing edges should have empty descendants."""
        self.graph.add_node("orphan")
        self.assertSetEqual(self.graph.get_descendants("orphan"), set())

    def test_reachable_from_all_empty(self) -> None:
        """Empty source set should produce empty result."""
        self.graph.add_edges([("A", "B")])
        result = self.graph.reachable_from_all(set())
        self.assertSetEqual(result, set())

    def test_graph_property(self) -> None:
        """The .graph property should expose the internal DiGraph (read-only)."""
        self.graph.add_edges([("X", "Y")])
        g = self.graph.graph
        self.assertIsInstance(g, nx.DiGraph)
        self.assertTrue(g.has_edge("X", "Y"))

    def test_freeze_makes_graph_readonly(self) -> None:
        """After freeze, the internal graph should be a frozen DiGraph."""
        self.graph.add_edges([("A", "B")])
        self.graph.freeze()
        g = self.graph.graph
        with self.assertRaises(nx.NetworkXError):
            g.add_edge("B", "C")


if __name__ == "__main__":
    unittest.main()
