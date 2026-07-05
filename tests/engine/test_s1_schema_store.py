"""Test engine schema and store (S1)."""
from __future__ import annotations

import networkx as nx
import pytest

from parallelines.engine import Relation, ResultStore
from parallelines.engine.schema import (
    AddonRow,
    DepConflictRow,
    DependencyRow,
    EntryPointRow,
    FileRow,
    HashConflictRow,
    ImpactRow,
    IsolatedPackageRow,
)


class TestSchema:
    def test_file_row_defaults(self):
        """is_dead and is_redundant default to False."""
        r = FileRow("a.txt", "base", "game", 100, "abc", 1024, True)
        assert r.is_dead is False
        assert r.is_redundant is False

    def test_isolated_package_row_defaults(self):
        """example_paths defaults to empty list."""
        r = IsolatedPackageRow("addon_x", 5)
        assert r.example_paths == []

    def test_all_dataclass_types(self):
        """All Row types are instantiatable with required fields."""
        rows = [
            FileRow("a.txt", "base", "game", 100, "abc", 1024, True),
            DependencyRow("a.txt", "b.txt", "base"),
            AddonRow("12345", "My Addon", True, 1000),
            HashConflictRow("x.txt", "base", "addon", "aaa", "bbb"),
            DepConflictRow("a.txt", "b.txt", "base", "addon"),
            IsolatedPackageRow("addon_x", 3, ["x.txt", "y.txt"]),
            ImpactRow("a.txt", "base", 5),
            EntryPointRow("a.txt", "map"),
        ]
        assert len(rows) == 8


class TestRelation:
    def test_empty_relation(self):
        rel = Relation.from_rows("empty", [])
        assert len(rel) == 0
        assert rel.columns == ()

    def test_from_rows_detects_columns(self):
        rows = [
            FileRow("a.txt", "base", "game", 100, "abc", 1024, True),
            FileRow("b.txt", "addon", "addon", 200, "def", 512, True, True, False),
        ]
        rel = Relation.from_rows("files", rows)
        assert "virtual_path" in rel.columns
        assert "is_dead" in rel.columns
        assert len(rel) == 2

    def test_build_index_and_lookup(self):
        rows = [
            FileRow("a.txt", "base", "game", 100, "abc", 1024, True),
            FileRow("b.txt", "addon", "addon", 200, "def", 512, True, True, False),
        ]
        rel = Relation.from_rows("files", rows)
        rel.build_index("virtual_path")
        result = rel.lookup("virtual_path", "a.txt")
        assert len(result) == 1
        assert result[0].source_name == "base"

    def test_lookup_missing_value(self):
        rows = [FileRow("a.txt", "base", "game", 100, "abc", 1024, True)]
        rel = Relation.from_rows("files", rows)
        rel.build_index("virtual_path")
        result = rel.lookup("virtual_path", "nonexistent.txt")
        assert result == []

    def test_lookup_not_indexed_raises(self):
        rows = [FileRow("a.txt", "base", "game", 100, "abc", 1024, True)]
        rel = Relation.from_rows("files", rows)
        with pytest.raises(KeyError, match="not indexed"):
            rel.lookup("virtual_path", "a.txt")

    def test_build_index_unknown_column_raises(self):
        rel = Relation.from_rows("files", [])
        with pytest.raises(KeyError, match="not in"):
            rel.build_index("nonexistent")

    def test_update_cell(self):
        rows = [
            FileRow("a.txt", "base", "game", 100, "abc", 1024, True),
            FileRow("b.txt", "addon", "addon", 200, "def", 512, True),
        ]
        rel = Relation.from_rows("files", rows)
        n = rel.update_cell(lambda r: r.virtual_path == "b.txt", "is_dead", True)
        assert n == 1
        assert rel.rows[0].is_dead is False
        assert rel.rows[1].is_dead is True

    def test_update_cell_no_match(self):
        rows = [FileRow("a.txt", "base", "game", 100, "abc", 1024, True)]
        rel = Relation.from_rows("files", rows)
        n = rel.update_cell(lambda r: r.virtual_path == "z.txt", "is_dead", True)
        assert n == 0

    def test_update_cell_multi_match(self):
        rows = [
            FileRow("a.txt", "base", "game", 100, "abc", 1024, True),
            FileRow("b.txt", "addon", "addon", 200, "def", 512, True),
            FileRow("c.txt", "addon", "addon", 200, "ghi", 256, True),
        ]
        rel = Relation.from_rows("files", rows)
        n = rel.update_cell(
            lambda r: r.source_type == "addon", "source_name", "override"
        )
        assert n == 2
        assert rel.rows[1].source_name == "override"
        assert rel.rows[2].source_name == "override"

    def test_update_cell_unknown_column_raises(self):
        rel = Relation.from_rows("files", [])
        with pytest.raises(KeyError, match="not in"):
            rel.update_cell(lambda r: True, "nonexistent", 1)

    def test_iteration(self):
        rows = [
            FileRow("a.txt", "base", "game", 100, "abc", 1024, True),
            FileRow("b.txt", "addon", "addon", 200, "def", 512, True),
        ]
        rel = Relation.from_rows("files", rows)
        assert [r.virtual_path for r in rel] == ["a.txt", "b.txt"]


class TestResultStore:
    def test_empty_store(self):
        store = ResultStore()
        assert store.files is None
        d = store.to_dict()
        assert d["files"] == []

    def test_descendants(self):
        store = ResultStore()
        rows = [
            FileRow("a.txt", "base", "game", 100, "abc", 1024, True),
            FileRow("b.txt", "addon", "addon", 200, "def", 512, True),
        ]
        store.files = Relation.from_rows("files", rows)
        g = nx.DiGraph()
        g.add_edge("a.txt", "b.txt")
        store.graph = g
        desc = store.descendants("a.txt")
        assert len(desc) == 1
        assert desc.rows[0].virtual_path == "b.txt"

    def test_descendants_nonexistent_node(self):
        store = ResultStore()
        store.files = Relation.from_rows("files", [])
        g = nx.DiGraph()
        store.graph = g
        desc = store.descendants("nonexistent.txt")
        assert len(desc) == 0

    def test_descendants_no_graph(self):
        store = ResultStore()
        desc = store.descendants("a.txt")
        assert len(desc) == 0

    def test_ancestors(self):
        store = ResultStore()
        rows = [
            FileRow("a.txt", "base", "game", 100, "abc", 1024, True),
            FileRow("b.txt", "addon", "addon", 200, "def", 512, True),
        ]
        store.files = Relation.from_rows("files", rows)
        g = nx.DiGraph()
        g.add_edge("a.txt", "b.txt")
        store.graph = g
        anc = store.ancestors("b.txt")
        assert len(anc) == 1
        assert anc.rows[0].virtual_path == "a.txt"

    def test_ancestors_no_graph(self):
        store = ResultStore()
        anc = store.ancestors("a.txt")
        assert len(anc) == 0

    def test_to_dict(self):
        store = ResultStore()
        rows = [FileRow("a.txt", "base", "game", 100, "abc", 1024, True)]
        store.files = Relation.from_rows("files", rows)
        store.hash_conflicts = Relation.from_rows(
            "hash_conflicts",
            [HashConflictRow("a.txt", "base", "addon", "aaa", "bbb")],
        )
        d = store.to_dict()
        assert len(d["files"]) == 1
        assert d["files"][0]["virtual_path"] == "a.txt"
        assert len(d["hash_conflicts"]) == 1
        assert d["dependencies"] == []
        assert d["isolated"] == []
