"""Tests for the 4 dependency anomaly analyzers (S6i)."""

from __future__ import annotations

import unittest

import networkx as nx

from parallelines.analysis.cascade_detector import CascadeDetector
from parallelines.analysis.cycle_detector import CycleDetector
from parallelines.analysis.global_script_detector import GlobalScriptDetector
from parallelines.analysis.implicit_dep_detector import ImplicitDepDetector
from parallelines.engine import Relation, ResultStore
from parallelines.engine.schema import (
    CascadeOverrideRow,
    DependencyCycleRow,
    FileRow,
    GlobalScriptRow,
    ImplicitDepRow,
)


class TestCycleDetector(unittest.TestCase):
    """Verify cycle detection in the dependency graph."""

    def setUp(self) -> None:
        self.analyzer = CycleDetector()

    def test_cycle_detector(self) -> None:
        """A graph with a simple cycle -> one DependencyCycleRow."""
        g = nx.DiGraph()
        g.add_edges_from([("a.txt", "b.txt"), ("b.txt", "c.txt"), ("c.txt", "a.txt")])
        store = ResultStore()
        store.graph = g

        self.analyzer.analyze(None, None, store)

        self.assertIsNotNone(store.dependency_cycles)
        rows = store.dependency_cycles.rows
        self.assertEqual(len(rows), 1)
        cycle = rows[0]
        self.assertIsInstance(cycle, DependencyCycleRow)
        self.assertEqual(cycle.length, 3)
        # The cycle is a, b, c (rotations are valid)
        self.assertEqual(set(cycle.cycle), {"a.txt", "b.txt", "c.txt"})

    def test_cycle_detector_no_cycle(self) -> None:
        """A DAG -> no DependencyCycleRow."""
        g = nx.DiGraph()
        g.add_edges_from([("a.txt", "b.txt"), ("b.txt", "c.txt")])
        store = ResultStore()
        store.graph = g

        self.analyzer.analyze(None, None, store)

        self.assertIsNone(store.dependency_cycles)

    def test_cycle_detector_empty_graph(self) -> None:
        """An empty graph -> no rows."""
        g = nx.DiGraph()
        store = ResultStore()
        store.graph = g

        self.analyzer.analyze(None, None, store)

        self.assertIsNone(store.dependency_cycles)

    def test_cycle_detector_no_graph(self) -> None:
        """store.graph is None -> no error."""
        store = ResultStore()
        self.analyzer.analyze(None, None, store)
        self.assertIsNone(store.dependency_cycles)

    def test_cycle_detector_two_cycles(self) -> None:
        """Two disjoint cycles -> 2 rows."""
        g = nx.DiGraph()
        g.add_edges_from([("a", "b"), ("b", "a"), ("c", "d"), ("d", "e"), ("e", "c")])
        store = ResultStore()
        store.graph = g

        self.analyzer.analyze(None, None, store)

        self.assertIsNotNone(store.dependency_cycles)
        self.assertEqual(len(store.dependency_cycles.rows), 2)
        lengths = sorted(r.length for r in store.dependency_cycles.rows)
        self.assertEqual(lengths, [2, 3])


class TestCascadeDetector(unittest.TestCase):
    """Verify cascade override detection."""

    def setUp(self) -> None:
        self.analyzer = CascadeDetector()

    def test_cascade_detector(self) -> None:
        """3 FileRows same path different priorities -> cascade detected."""
        store = ResultStore()
        store.files = Relation.from_rows(
            "files",
            [
                FileRow("scripts/test.nut", "addon_a", "addon", 100, "h1", 10, True),
                FileRow("scripts/test.nut", "addon_b", "addon", 200, "h2", 10, True),
                FileRow("scripts/test.nut", "addon_c", "addon", 50, "h3", 10, True),
            ],
        )

        self.analyzer.analyze(None, None, store)

        self.assertIsNotNone(store.cascade_overrides)
        rows = store.cascade_overrides.rows
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertIsInstance(row, CascadeOverrideRow)
        self.assertEqual(row.virtual_path, "scripts/test.nut")
        # Sorted by priority descending: addon_b(200), addon_a(100), addon_c(50)
        self.assertEqual(row.chain_sources, ["addon_b", "addon_a", "addon_c"])
        self.assertEqual(row.chain_priorities, [200, 100, 50])
        self.assertEqual(row.active_source, "addon_b")

    def test_cascade_detector_no_cascade(self) -> None:
        """Only 2 providers for a path -> no cascade."""
        store = ResultStore()
        store.files = Relation.from_rows(
            "files",
            [
                FileRow("scripts/test.nut", "addon_a", "addon", 100, "h1", 10, True),
                FileRow("scripts/test.nut", "addon_b", "addon", 200, "h2", 10, True),
            ],
        )

        self.analyzer.analyze(None, None, store)

        self.assertIsNone(store.cascade_overrides)

    def test_cascade_detector_mixed(self) -> None:
        """Multiple paths: some cascade, some don't."""
        store = ResultStore()
        store.files = Relation.from_rows(
            "files",
            [
                # This path has 3 providers -> cascade
                FileRow("scripts/test.nut", "addon_a", "addon", 100, "h1", 10, True),
                FileRow("scripts/test.nut", "addon_b", "addon", 200, "h2", 10, True),
                FileRow("scripts/test.nut", "addon_c", "addon", 50, "h3", 10, True),
                # This path has only 1 provider -> no cascade
                FileRow("unique.txt", "addon_d", "addon", 100, "h4", 10, True),
            ],
        )

        self.analyzer.analyze(None, None, store)

        self.assertIsNotNone(store.cascade_overrides)
        self.assertEqual(len(store.cascade_overrides.rows), 1)

    def test_cascade_detector_no_files(self) -> None:
        """No files in store -> no error."""
        store = ResultStore()
        self.analyzer.analyze(None, None, store)
        self.assertIsNone(store.cascade_overrides)


class TestGlobalScriptDetector(unittest.TestCase):
    """Verify global .nut script detection."""

    def setUp(self) -> None:
        self.analyzer = GlobalScriptDetector()

    def test_global_script_detector(self) -> None:
        """A .nut file outside maps/ -> detected."""
        store = ResultStore()
        store.files = Relation.from_rows(
            "files",
            [
                FileRow(
                    "scripts/vscripts/global.nut",
                    "addon_a",
                    "addon",
                    100,
                    "h1",
                    10,
                    True,
                ),
            ],
        )

        self.analyzer.analyze(None, None, store)

        self.assertIsNotNone(store.global_scripts)
        rows = store.global_scripts.rows
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertIsInstance(row, GlobalScriptRow)
        self.assertEqual(row.virtual_path, "scripts/vscripts/global.nut")
        self.assertEqual(row.source_name, "addon_a")
        self.assertEqual(row.source_type, "addon")

    def test_global_script_detector_map_scripts_excluded(self) -> None:
        """A .nut file inside maps/ -> excluded."""
        store = ResultStore()
        store.files = Relation.from_rows(
            "files",
            [
                FileRow("maps/c1m1_hotel.nut", "addon_b", "addon", 100, "h2", 10, True),
                FileRow(
                    "maps/c1m1_hotel_sprinklers.nut",
                    "addon_b",
                    "addon",
                    100,
                    "h3",
                    10,
                    True,
                ),
            ],
        )

        self.analyzer.analyze(None, None, store)

        self.assertIsNone(store.global_scripts)

    def test_global_script_detector_non_nut_ignored(self) -> None:
        """Non-.nut files -> not included."""
        store = ResultStore()
        store.files = Relation.from_rows(
            "files",
            [
                FileRow("scripts/skill.cfg", "game", "game", 100, "h4", 10, True),
                FileRow("materials/brick.vtf", "game", "game", 100, "h5", 10, True),
            ],
        )

        self.analyzer.analyze(None, None, store)

        self.assertIsNone(store.global_scripts)

    def test_global_script_detector_no_files(self) -> None:
        """No files -> no error."""
        store = ResultStore()
        self.analyzer.analyze(None, None, store)
        self.assertIsNone(store.global_scripts)


class TestImplicitDepDetector(unittest.TestCase):
    """Verify implicit cross-addon dependency detection."""

    def setUp(self) -> None:
        self.analyzer = ImplicitDepDetector()

    def test_implicit_dep(self) -> None:
        """Cross-addon edge -> ImplicitDepRow."""
        g = nx.DiGraph()
        g.add_edge("addon_a/scripts/a.nut", "addon_b/scripts/b.nut")

        store = ResultStore()
        store.graph = g
        store.files = Relation.from_rows(
            "files",
            [
                FileRow(
                    "addon_a/scripts/a.nut", "addon_a", "addon", 100, "h1", 10, True
                ),
                FileRow(
                    "addon_b/scripts/b.nut", "addon_b", "addon", 200, "h2", 10, True
                ),
            ],
        )

        self.analyzer.analyze(None, None, store)

        self.assertIsNotNone(store.implicit_deps)
        rows = store.implicit_deps.rows
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertIsInstance(row, ImplicitDepRow)
        self.assertEqual(row.dependent_addon, "addon_a")
        self.assertEqual(row.provider_addon, "addon_b")
        self.assertEqual(row.virtual_path, "addon_b/scripts/b.nut")

    def test_implicit_dep_same_addon(self) -> None:
        """Same-addon edge -> no ImplicitDepRow."""
        g = nx.DiGraph()
        g.add_edge("addon_a/scripts/a.nut", "addon_a/scripts/b.nut")

        store = ResultStore()
        store.graph = g
        store.files = Relation.from_rows(
            "files",
            [
                FileRow(
                    "addon_a/scripts/a.nut", "addon_a", "addon", 100, "h1", 10, True
                ),
                FileRow(
                    "addon_a/scripts/b.nut", "addon_a", "addon", 200, "h2", 10, True
                ),
            ],
        )

        self.analyzer.analyze(None, None, store)

        self.assertIsNone(store.implicit_deps)

    def test_implicit_dep_deduplication(self) -> None:
        """Identical (dependent, provider, path) tuples -> deduplicated."""
        g = nx.DiGraph()
        # Two edges with the same (src, dst) pair
        g.add_edge("addon_a/a.nut", "addon_b/b.nut")
        g.add_edge("addon_a/a.nut", "addon_b/b.nut")

        store = ResultStore()
        store.graph = g
        store.files = Relation.from_rows(
            "files",
            [
                FileRow("addon_a/a.nut", "addon_a", "addon", 100, "h1", 10, True),
                FileRow("addon_b/b.nut", "addon_b", "addon", 200, "h2", 10, True),
            ],
        )

        self.analyzer.analyze(None, None, store)

        self.assertIsNotNone(store.implicit_deps)
        self.assertEqual(len(store.implicit_deps.rows), 1)

    def test_implicit_dep_no_graph(self) -> None:
        """No graph -> no error."""
        store = ResultStore()
        store.files = Relation.from_rows(
            "files",
            [
                FileRow("a.nut", "addon_a", "addon", 100, "h1", 10, True),
            ],
        )
        self.analyzer.analyze(None, None, store)
        self.assertIsNone(store.implicit_deps)

    def test_implicit_dep_no_files(self) -> None:
        """No files -> no error."""
        g = nx.DiGraph()
        g.add_edge("a.nut", "b.nut")
        store = ResultStore()
        store.graph = g
        self.analyzer.analyze(None, None, store)
        self.assertIsNone(store.implicit_deps)

    def test_implicit_dep_multiple_cross(self) -> None:
        """Multiple cross-addon edges -> multiple rows."""
        g = nx.DiGraph()
        g.add_edges_from(
            [
                ("addon_a/a.nut", "addon_b/b.nut"),
                ("addon_a/c.nut", "addon_c/d.nut"),
            ]
        )

        store = ResultStore()
        store.graph = g
        store.files = Relation.from_rows(
            "files",
            [
                FileRow("addon_a/a.nut", "addon_a", "addon", 100, "h1", 10, True),
                FileRow("addon_a/c.nut", "addon_a", "addon", 100, "h3", 10, True),
                FileRow("addon_b/b.nut", "addon_b", "addon", 200, "h2", 10, True),
                FileRow("addon_c/d.nut", "addon_c", "addon", 200, "h4", 10, True),
            ],
        )

        self.analyzer.analyze(None, None, store)

        self.assertIsNotNone(store.implicit_deps)
        self.assertEqual(len(store.implicit_deps.rows), 2)


if __name__ == "__main__":
    unittest.main()
