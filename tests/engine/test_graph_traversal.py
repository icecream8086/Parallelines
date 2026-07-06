"""Graph traversal integration tests (GRP-01 ~ GRP-10)."""
from __future__ import annotations

import pytest
import networkx as nx

from parallelines.engine import ResultStore
from parallelines.engine.schema import DependencyCycleRow, FileRow
from parallelines.engine.store import Relation


@pytest.fixture
def store() -> ResultStore:
    store = ResultStore()
    store.files = Relation[FileRow].from_rows("files", [
        FileRow("maps/m1.bsp", "vpk1", "vpk", 100, "a", 1024, True),
        FileRow("materials/m1.vmt", "vpk1", "vpk", 100, "b", 512, True),
        FileRow("scripts/test.nut", "vpk1", "vpk", 100, "c", 256, True),
        FileRow("maps/m2.bsp", "vpk2", "vpk", 200, "d", 2048, True),
        FileRow("unused.txt", "vpk3", "vpk", 300, "e", 64, True),
    ])
    g = nx.DiGraph()
    g.add_edge("maps/m1.bsp", "materials/m1.vmt")
    g.add_edge("maps/m1.bsp", "scripts/test.nut")
    g.add_edge("materials/m1.vmt", "unused.txt")
    g.add_edge("maps/m2.bsp", "unused.txt")
    store.graph = g
    # Empty cycles — no cycles in this graph
    store.dependency_cycles = Relation[DependencyCycleRow].from_rows(
        "dependency_cycles", []
    )
    store.external_files = Relation.from_rows("external_files", [])
    return store


class TestDescendantsOf:
    def test_valid_path(self, store: ResultStore):
        """GRP-01: descendants_of returns all downstream files."""
        r = store.execute({
            "select": ["*"],
            "from": {"descendants_of": "maps/m1.bsp"},
        })
        assert len(r) >= 1
        paths = {row[0] if isinstance(row, tuple) else row.virtual_path for row in r.rows}
        assert "materials/m1.vmt" in paths
        assert "scripts/test.nut" in paths

    def test_nonexistent_path(self, store: ResultStore):
        """GRP-02: descendants_of nonexistent path returns empty."""
        r = store.execute({
            "select": ["*"],
            "from": {"descendants_of": "ghost/path.txt"},
        })
        assert len(r) == 0

    def test_no_graph(self):
        """GRP-03: descendants_of when graph is None returns empty."""
        s = ResultStore()
        s.files = Relation[FileRow].from_rows("files", [
            FileRow("a.txt", "base", "game", 100, "a", 1, True),
        ])
        r = s.execute({
            "select": ["*"],
            "from": {"descendants_of": "a.txt"},
        })
        assert len(r) == 0


class TestAncestorsOf:
    def test_valid_path(self, store: ResultStore):
        """GRP-04: ancestors_of returns all upstream files."""
        r = store.execute({
            "select": ["*"],
            "from": {"ancestors_of": "materials/m1.vmt"},
        })
        assert len(r) >= 1
        paths = {row[0] if isinstance(row, tuple) else row.virtual_path for row in r.rows}
        assert "maps/m1.bsp" in paths

    def test_nonexistent_path(self, store: ResultStore):
        """GRP-05: ancestors_of nonexistent returns empty."""
        r = store.execute({
            "select": ["*"],
            "from": {"ancestors_of": "ghost/path.txt"},
        })
        assert len(r) == 0


class TestFindCycles:
    def test_no_cycles(self, store: ResultStore):
        """GRP-07: find_cycles on acyclic graph returns empty."""
        r = store.execute({
            "select": ["*"],
            "from": {"find_cycles": True},
        })
        assert len(r) == 0

    def test_with_cycles(self):
        """GRP-06: find_cycles on graph with cycles returns rows."""
        s = ResultStore()
        s.dependency_cycles = Relation[DependencyCycleRow].from_rows(
            "dependency_cycles",
            [DependencyCycleRow(["a", "b", "c"], 3)],
        )
        r = s.execute({
            "select": ["*"],
            "from": {"find_cycles": True},
        })
        assert len(r) == 1
        row = r.rows[0]
        assert row.cycle == ["a", "b", "c"]
        assert row.length == 3


class TestGraphPredicates:
    def test_ancestor_is_map_true(self, store: ResultStore):
        """GRP-08: ancestor_is_map on path with .bsp ancestor."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"ancestor_is_map": "virtual_path"},
        })
        # materials/m1.vmt, scripts/test.nut, and unused.txt have .bsp ancestors
        assert len(r) >= 2

    def test_ancestor_is_map_false(self, store: ResultStore):
        """GRP-08: path with no .bsp ancestor."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"and": [
                {"ancestor_is_map": "virtual_path"},
                {"eq": ["virtual_path", "maps/m1.bsp"]},
            ]},
        })
        # maps/m1.bsp has no ancestors, so ancestor_is_map is False
        assert len(r) == 0

    def test_descendant_is_script_true(self, store: ResultStore):
        """GRP-09: descendant_is_script on path with .nut descendant."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"descendant_is_script": "virtual_path"},
        })
        # maps/m1.bsp has .nut descendant (scripts/test.nut)
        assert len(r) >= 1

    def test_descendant_is_script_false(self):
        """GRP-09b: descendant_is_script on path with no .nut descendant."""
        s = ResultStore()
        s.files = Relation[FileRow].from_rows("files", [
            FileRow("a.txt", "base", "game", 100, "a", 1, True),
        ])
        s.graph = nx.DiGraph()
        s.graph.add_edge("a.txt", "b.txt")
        r = s.execute({
            "select": ["*"], "from": "files",
            "where": {"descendant_is_script": "virtual_path"},
        })
        assert len(r) == 0  # no .nut descendants

    def test_graph_predicate_no_graph(self):
        """GRP-10: GraphPred when graph is None returns False."""
        s = ResultStore()
        s.files = Relation[FileRow].from_rows("files", [
            FileRow("a.txt", "base", "game", 100, "a", 1, True),
        ])
        r = s.execute({
            "select": ["*"], "from": "files",
            "where": {"ancestor_is_map": "virtual_path"},
        })
        assert len(r) == 0  # no match because graph is None
