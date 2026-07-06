"""Tests for S8 DSL extensions — StringPred, ExistsPred, GraphPred, not_in,
graph function sources, cross-column comparison, HAVING, multi-column GROUP BY."""

from __future__ import annotations

import pytest
import networkx as nx

from parallelines.engine import ResultStore
from parallelines.engine.schema import (
    DependencyCycleRow,
    ExternalFileRow,
    FileRow,
)
from parallelines.engine.store import Relation


# ── Fixture ──────────────────────────────────────────────────


@pytest.fixture
def store() -> ResultStore:
    """ResultStore with files, graph, external_files, and dependency_cycles."""
    store = ResultStore()

    # ── 7 files with diverse paths ──────────────────────────
    file_rows = [
        FileRow("maps/c1m1_hotel.bsp", "map_vpk", "vpk", 100, "aaa", 1024, True),
        FileRow("materials/test.vmt", "map_vpk", "vpk", 100, "bbb", 512, True),
        FileRow("scripts/vscripts/test.nut", "script_vpk", "vpk", 200, "ccc", 256, True),
        FileRow("maps/c1m2_streets.bsp", "base", "game", 50, "ddd", 2048, True),
        FileRow("scripts/vscripts/global.nut", "base", "game", 50, "eee", 128, True),
        FileRow("sounds/ambience.wav", "base", "game", 50, "fff", 4096, True),
        FileRow("unused_file.txt", "dead_vpk", "vpk", 300, "ggg", 64, True),
    ]
    store.files = Relation[FileRow].from_rows("files", file_rows)

    # ── Dependency graph ────────────────────────────────────
    g = nx.DiGraph()
    g.add_edge("maps/c1m1_hotel.bsp", "materials/test.vmt")
    g.add_edge("maps/c1m1_hotel.bsp", "scripts/vscripts/test.nut")
    g.add_edge("maps/c1m2_streets.bsp", "scripts/vscripts/global.nut")
    g.add_edge("materials/test.vmt", "unused_file.txt")
    store.graph = g

    # ── External files ──────────────────────────────────────
    store.external_files = Relation[ExternalFileRow].from_rows("external_files", [
        ExternalFileRow("materials/test.vmt", "ref:new", 2000, "xxx", 512),
        ExternalFileRow("sounds/new_sound.wav", "ref:new", 2000, "yyy", 1024),
        ExternalFileRow("scripts/vscripts/test.nut", "ref:new", 2000, "zzz", 256),
    ])
    store.external_files.build_index("virtual_path")

    # ── Dependency cycles ───────────────────────────────────
    store.dependency_cycles = Relation[DependencyCycleRow].from_rows(
        "dependency_cycles",
        [
            DependencyCycleRow(["cycle_a.txt", "cycle_b.txt", "cycle_c.txt"], 3),
        ],
    )

    return store


# ================================================================
#  StringPred  tests
# ================================================================


class TestStringPred:
    def test_starts_with(self, store: ResultStore):
        result = store.execute({
            "select": ["virtual_path"],
            "from": "files",
            "where": {"starts_with": ["virtual_path", "maps/"]},
        })
        assert len(result) == 2
        assert all(r[0].startswith("maps/") for r in result.rows)

    def test_ends_with(self, store: ResultStore):
        result = store.execute({
            "select": ["virtual_path"],
            "from": "files",
            "where": {"ends_with": ["virtual_path", ".nut"]},
        })
        assert len(result) == 2
        assert all(r[0].endswith(".nut") for r in result.rows)

    def test_contains(self, store: ResultStore):
        result = store.execute({
            "select": ["virtual_path"],
            "from": "files",
            "where": {"contains": ["virtual_path", "scripts/"]},
        })
        assert len(result) == 2
        assert all("scripts/" in r[0] for r in result.rows)

    def test_not_contains(self, store: ResultStore):
        result = store.execute({
            "select": ["virtual_path"],
            "from": "files",
            "where": {"not_contains": ["virtual_path", "maps/"]},
        })
        assert len(result) == 5
        assert all("maps/" not in r[0] for r in result.rows)

    def test_no_match(self, store: ResultStore):
        result = store.execute({
            "select": ["virtual_path"],
            "from": "files",
            "where": {"starts_with": ["virtual_path", "zzz_"]},
        })
        assert len(result) == 0

    def test_all_match(self, store: ResultStore):
        """Empty string is contained in every value."""
        result = store.execute({
            "select": ["virtual_path"],
            "from": "files",
            "where": {"contains": ["virtual_path", ""]},
        })
        assert len(result) == 7


# ================================================================
#  ExistsPred  tests
# ================================================================


class TestExistsPred:
    def test_exists_in(self, store: ResultStore):
        """Files that also appear in external_files."""
        result = store.execute({
            "select": ["virtual_path"],
            "from": "files",
            "where": {"exists_in": ["virtual_path", "external_files"]},
        })
        assert len(result) == 2
        paths = {r[0] for r in result.rows}
        assert "materials/test.vmt" in paths
        assert "scripts/vscripts/test.nut" in paths

    def test_not_exists_in_from_external(self, store: ResultStore):
        """External files that are brand new (not in files)."""
        result = store.execute({
            "select": ["virtual_path"],
            "from": "external_files",
            "where": {"not_exists_in": ["virtual_path", "files"]},
        })
        assert len(result) == 1
        assert result.rows[0][0] == "sounds/new_sound.wav"

    def test_not_exists_in_from_files(self, store: ResultStore):
        """Files that are *not* in external_files."""
        result = store.execute({
            "select": ["virtual_path"],
            "from": "files",
            "where": {"not_exists_in": ["virtual_path", "external_files"]},
        })
        assert len(result) == 5
        assert "materials/test.vmt" not in {r[0] for r in result.rows}

    def test_exists_in_empty_target(self):
        """ExistsPred against an empty relation returns no matches."""
        store = ResultStore()
        store.files = Relation[FileRow].from_rows("files", [
            FileRow("a.txt", "base", "game", 100, "abc", 1024, True),
        ])
        store.external_files = Relation(
            "external_files",
            ("virtual_path", "ext_source_name", "ext_priority",
             "ext_file_hash", "ext_file_size"),
            [],
        )
        result = store.execute({
            "select": ["virtual_path"],
            "from": "files",
            "where": {"exists_in": ["virtual_path", "external_files"]},
        })
        assert len(result) == 0

    def test_not_exists_in_no_match(self, store: ResultStore):
        """not_exists_in that filters everything out."""
        result = store.execute({
            "select": ["virtual_path"],
            "from": "files",
            "where": {"not_exists_in": ["virtual_path", "files"]},
        })
        # Every file in files exists in files → no match
        assert len(result) == 0


# ================================================================
#  GraphPred  tests
# ================================================================


class TestGraphPred:
    def test_ancestor_is_map(self, store: ResultStore):
        """Files that have a .bsp in their ancestor chain."""
        result = store.execute({
            "select": ["virtual_path"],
            "from": "files",
            "where": {"ancestor_is_map": "virtual_path"},
        })
        # 4 files have map ancestors:
        #   materials/test.vmt, scripts/vscripts/test.nut,
        #   scripts/vscripts/global.nut, unused_file.txt
        assert len(result) == 4
        paths = {r[0] for r in result.rows}
        assert "materials/test.vmt" in paths
        assert "scripts/vscripts/test.nut" in paths
        assert "scripts/vscripts/global.nut" in paths
        assert "unused_file.txt" in paths

    def test_descendant_is_script(self, store: ResultStore):
        """Files that have a .nut descendant."""
        result = store.execute({
            "select": ["virtual_path"],
            "from": "files",
            "where": {"descendant_is_script": "virtual_path"},
        })
        # 2 files have .nut descendants:
        #   maps/c1m1_hotel.bsp, maps/c1m2_streets.bsp
        assert len(result) == 2
        paths = {r[0] for r in result.rows}
        assert "maps/c1m1_hotel.bsp" in paths
        assert "maps/c1m2_streets.bsp" in paths

    def test_graph_pred_no_graph(self):
        """When graph is None, GraphPred returns no matches."""
        store = ResultStore()
        store.files = Relation[FileRow].from_rows("files", [
            FileRow("maps/a.bsp", "base", "game", 50, "abc", 1024, True),
        ])
        store.graph = None  # explicitly no graph
        result = store.execute({
            "select": ["virtual_path"],
            "from": "files",
            "where": {"ancestor_is_map": "virtual_path"},
        })
        assert len(result) == 0

    def test_graph_pred_path_not_in_graph(self, store: ResultStore):
        """Files not present in the graph should not match graph predicates."""
        result = store.execute({
            "select": ["virtual_path"],
            "from": "files",
            "where": {
                "and": [
                    {"eq": ["virtual_path", "sounds/ambience.wav"]},
                    {"ancestor_is_map": "virtual_path"},
                ]
            },
        })
        assert len(result) == 0


# ================================================================
#  InPred.negated  (not_in)  tests
# ================================================================


class TestNotIn:
    def test_not_in(self, store: ResultStore):
        result = store.execute({
            "select": ["source_name"],
            "from": "files",
            "where": {"not_in": ["source_name", ["base"]]},
        })
        assert all(r[0] != "base" for r in result.rows)

    def test_not_in_empty_list(self, store: ResultStore):
        """not_in with [] matches everything (nothing is excluded)."""
        result = store.execute({
            "select": ["virtual_path"],
            "from": "files",
            "where": {"not_in": ["source_name", []]},
        })
        assert len(result) == 7

    def test_not_in_matches_nothing(self, store: ResultStore):
        """not_in covering all possible source_names yields empty."""
        result = store.execute({
            "select": ["source_name"],
            "from": "files",
            "where": {"not_in": [
                "source_name",
                ["map_vpk", "script_vpk", "base", "dead_vpk"],
            ]},
        })
        assert len(result) == 0


# ================================================================
#  Graph function source  tests
# ================================================================


class TestGraphSource:
    def test_descendants_of_source(self, store: ResultStore):
        result = store.execute({
            "select": ["virtual_path"],
            "from": {"descendants_of": "maps/c1m1_hotel.bsp"},
        })
        # materials/test.vmt, scripts/vscripts/test.nut, unused_file.txt
        assert len(result) == 3
        assert all(isinstance(r, tuple) for r in result.rows)

    def test_ancestors_of_source(self, store: ResultStore):
        result = store.execute({
            "select": ["virtual_path"],
            "from": {"ancestors_of": "materials/test.vmt"},
        })
        # maps/c1m1_hotel.bsp
        assert len(result) == 1
        assert result.rows[0][0] == "maps/c1m1_hotel.bsp"

    def test_find_cycles_source(self, store: ResultStore):
        result = store.execute({
            "select": ["*"],
            "from": {"find_cycles": True},
        })
        assert len(result) == 1
        assert result.columns == ("cycle", "length")
        # Rows are DependencyCycleRow objects (not tuples) with select=["*"]
        assert result.rows[0].length == 3

    def test_graph_source_nonexistent_path(self, store: ResultStore):
        result = store.execute({
            "select": ["*"],
            "from": {"descendants_of": "nonexistent/path.txt"},
        })
        assert len(result) == 0

    def test_graph_source_no_graph(self):
        store = ResultStore()
        store.files = Relation[FileRow].from_rows("files", [
            FileRow("a.txt", "base", "game", 100, "abc", 1024, True),
        ])
        result = store.execute({
            "select": ["*"],
            "from": {"descendants_of": "a.txt"},
        })
        assert len(result) == 0

    def test_graph_source_no_cycles(self):
        """find_cycles when dependency_cycles is empty returns empty."""
        store = ResultStore()
        store.files = Relation[FileRow].from_rows("files", [
            FileRow("a.txt", "base", "game", 100, "abc", 1024, True),
        ])
        store.graph = nx.DiGraph()
        store.graph.add_edge("a.txt", "b.txt")
        store.dependency_cycles = Relation[DependencyCycleRow].from_rows(
            "dependency_cycles", []
        )
        result = store.execute({
            "select": ["*"],
            "from": {"find_cycles": True},
        })
        assert len(result) == 0


# ================================================================
#  Cross-column comparison  tests
# ================================================================


class TestCrossColumnCompare:
    def test_gt_between_columns(self, store: ResultStore):
        """Compare ext_priority from external_files with priority from files after join."""
        result = store.execute({
            "select": [["external_files", "virtual_path"]],
            "from": "external_files",
            "join": {
                "type": "inner",
                "with": "files",
                "on": {"eq": [["external_files", "virtual_path"],
                              ["files", "virtual_path"]]},
            },
            "where": {"gt": [["external_files", "ext_priority"],
                             ["files", "priority"]]},
        })
        # Both overlapping files have ext_priority=2000 > current priority
        assert len(result) == 2
        paths = {r[0] for r in result.rows}
        assert "materials/test.vmt" in paths
        assert "scripts/vscripts/test.nut" in paths

    def test_eq_between_columns(self, store: ResultStore):
        """Compare ext_file_hash with file_hash after join — should match when same."""
        result = store.execute({
            "select": [["external_files", "virtual_path"]],
            "from": "external_files",
            "join": {
                "type": "inner",
                "with": "files",
                "on": {"eq": [["external_files", "virtual_path"],
                              ["files", "virtual_path"]]},
            },
            "where": {"eq": [["external_files", "ext_file_hash"],
                             ["files", "file_hash"]]},
        })
        # Hashes differ in our fixture (xxx vs bbb, zzz vs ccc) → 0 matches
        assert len(result) == 0


# ================================================================
#  HAVING clause  tests
# ================================================================


class TestHaving:
    def test_having(self, store: ResultStore):
        # Use a FileRow numeric column name as agg key to pass validator R2 check
        # (validator checks having columns against dataclass type map)
        result = store.execute({
            "select": ["source_name", "priority"],
            "from": "files",
            "group_by": {"by": ["source_name"], "agg": {"priority": "count"}},
            "having": {"gte": ["priority", 2]},
        })
        # map_vpk=2, base=3 pass; script_vpk=1, dead_vpk=1 filtered
        assert len(result) == 2
        for r in result.rows:
            assert r[1] >= 2

    def test_having_no_match(self, store: ResultStore):
        result = store.execute({
            "select": ["source_name", "priority"],
            "from": "files",
            "group_by": {"by": ["source_name"], "agg": {"priority": "count"}},
            "having": {"gte": ["priority", 100]},
        })
        assert len(result) == 0


# ================================================================
#  Multi-column GROUP BY  tests
# ================================================================


class TestGroupByMulti:
    def test_group_by_two_columns(self, store: ResultStore):
        result = store.execute({
            "select": ["source_type", "source_name", "file_count"],
            "from": "files",
            "group_by": {
                "by": ["source_type", "source_name"],
                "agg": {"file_count": "count"},
            },
        })
        # vpk/map_vpk=2, vpk/script_vpk=1, game/base=3, vpk/dead_vpk=1 → 4 groups
        assert len(result) == 4
        rows = {(r[0], r[1]): r[2] for r in result.rows}
        assert rows[("vpk", "map_vpk")] == 2
        assert rows[("vpk", "script_vpk")] == 1
        assert rows[("game", "base")] == 3
        assert rows[("vpk", "dead_vpk")] == 1

    def test_group_by_multi_sum(self, store: ResultStore):
        result = store.execute({
            "select": ["source_type", "source_name", "total_size"],
            "from": "files",
            "group_by": {
                "by": ["source_type", "source_name"],
                "agg": {"total_size": ["sum", "file_size"]},
            },
        })
        assert len(result) == 4
        rows = {(r[0], r[1]): r[2] for r in result.rows}
        assert rows[("vpk", "map_vpk")] == 1536  # 1024 + 512
        assert rows[("game", "base")] == 6272     # 2048 + 128 + 4096
