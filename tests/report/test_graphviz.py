"""Tests for parallelines.report.graphviz -- generate_dot."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from parallelines.graph.deps import DependencyGraph
from parallelines.report.graphviz import generate_dot


class TestGraphviz(unittest.TestCase):
    """Smoke tests for graphviz .dot generation."""

    def test_importable(self) -> None:
        """Module can be imported and generate_dot is callable."""
        from parallelines.report.graphviz import generate_dot as gd

        self.assertTrue(callable(gd))

    def test_generate_dot_empty_graph(self) -> None:
        """generate_dot returns a Path when given an empty graph."""
        graph = DependencyGraph()
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "graph.dot"
            result = generate_dot(graph, out_path)

            self.assertIsInstance(result, Path)
            self.assertTrue(result.exists())
            self.assertEqual(result.suffix, ".dot")
            self.assertEqual(result, out_path.resolve())

            content = result.read_text(encoding="utf-8")
            self.assertIn("digraph G {", content)
            self.assertIn("rankdir=LR;", content)
            self.assertIn("concentrate=true;", content)
            self.assertIn("}", content)

    def test_generate_dot_with_nodes(self) -> None:
        """generate_dot includes nodes and edges from a populated graph."""
        graph = DependencyGraph()
        graph.add_edges(
            [
                ("maps/c1m1_hotel.bsp", "materials/wall.vmt"),
                ("materials/wall.vmt", "materials/wall.vtf"),
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "graph.dot"
            result = generate_dot(graph, out_path)

            content = result.read_text(encoding="utf-8")
            self.assertIn("maps/c1m1_hotel.bsp", content)
            self.assertIn("materials/wall.vmt", content)
            self.assertIn("materials/wall.vtf", content)
            self.assertIn("->", content)

    def test_generate_dot_max_nodes(self) -> None:
        """generate_dot respects max_nodes limit and includes node colours."""
        graph = DependencyGraph()
        edges = [(f"file_{i}.txt", f"file_{i + 1}.txt") for i in range(100)]
        graph.add_edges(edges)

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "limited.dot"
            result = generate_dot(graph, out_path, max_nodes=10)

            content = result.read_text(encoding="utf-8")
            lines = content.splitlines()
            node_lines = [line for line in lines if "fillcolor" in line]
            self.assertLessEqual(len(node_lines), 10)

    def test_generate_dot_vmt_node_color(self) -> None:
        """VMT nodes receive the correct colour."""
        graph = DependencyGraph()
        graph.add_node("materials/test.vmt")

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "color.dot"
            result = generate_dot(graph, out_path)

            content = result.read_text(encoding="utf-8")
            self.assertIn('fillcolor="lightblue"', content)


if __name__ == "__main__":
    unittest.main()
