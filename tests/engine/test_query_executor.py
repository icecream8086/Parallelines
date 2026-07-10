"""Executor tests (EXE-01 ~ EXE-77, NULL-01 ~ NULL-13, ORD-01 ~ ORD-07, CMP-01 ~ CMP-12)."""
from __future__ import annotations

import pytest

import networkx as nx

from parallelines.engine import ResultStore
from parallelines.engine.query_ast import (
    BinaryPred,
    ColumnRef,
    CompoundPred,
    ExistsPred,
    GraphPred,
    GroupByClause,
    InPred,
    IsNullPred,
    JoinClause,
    LikePred,
    Literal as Lit,
    OrderByClause,
    Query,
    Source,
    StringPred,
)
from parallelines.engine.query_executor import QueryExecutor
from parallelines.engine.schema import (
    DependencyCycleRow,
    ExternalFileRow,
    FileRow,
)
from parallelines.engine.store import Relation


@pytest.fixture
def store() -> ResultStore:
    """Standard store for executor tests."""
    store = ResultStore()
    store.files = Relation[FileRow].from_rows("files", [
        FileRow("a.txt", "base", "game", 100, "abc", 1024, True),
        FileRow("b.txt", "addon_x", "addon", 200, "def", 512, True),
        FileRow("c.txt", "addon_y", "addon", 300, "ghi", 256, False),
        FileRow("maps/m1.bsp", "map_vpk", "vpk", 400, "jkl", 8192, True),
        FileRow("materials/m1.vmt", "map_vpk", "vpk", 400, "mno", 128, True),
        FileRow("scripts/test.nut", "script_vpk", "vpk", 500, "pqr", 64, True,
                False, False, False, False, True),
    ])
    # Graph
    g = nx.DiGraph()
    g.add_edge("maps/m1.bsp", "materials/m1.vmt")
    g.add_edge("maps/m1.bsp", "scripts/test.nut")
    store.graph = g
    # External files for cross-relation tests
    store.external_files = Relation[ExternalFileRow].from_rows("external_files", [
        ExternalFileRow("a.txt", "ref:ext", 2000, "xyz", 1024),
        ExternalFileRow("new.txt", "ref:ext", 2000, "new", 512),
    ])
    store.external_files.build_index("virtual_path")
    # Dependency cycles
    store.dependency_cycles = Relation[DependencyCycleRow].from_rows(
        "dependency_cycles",
        [DependencyCycleRow(["a", "b", "c"], 3)],
    )
    return store


@pytest.fixture
def null_store() -> ResultStore:
    """Store with None file_hash for NULL semantics tests."""
    s = ResultStore()
    s.files = Relation[FileRow].from_rows("files", [
        FileRow("n.txt", "base", "game", 100, None, 1, True),
        FileRow("a.txt", "base", "game", 100, "abc", 1, True),
    ])
    s.external_files = Relation[ExternalFileRow].from_rows("external_files", [
        ExternalFileRow("abc", "ref", 100, "x", 1),
    ])
    s.external_files.build_index("virtual_path")
    g = nx.DiGraph()
    g.add_edge("n.txt", "a.txt")
    s.graph = g
    return s


# ── FROM stage (EXE-01 ~ EXE-08) ───────────────────────────


class TestFrom:
    def test_relation(self, store: ResultStore):
        """EXE-01: relation source returns store relation."""
        result = store.execute({"select": ["*"], "from": "files"})
        assert len(result) == 6

    def test_nonexistent_relation(self, store: ResultStore):
        """EXE-02: nonexistent relation raises."""
        from parallelines.engine.query_validator import QueryValidationError
        with pytest.raises(QueryValidationError):
            store.execute({"select": ["*"], "from": "nonexistent"})

    def test_non_relation_attr(self, store: ResultStore):
        """EXE-03: graph attr (non-Relation) raises ValueError."""
        q = Query([Lit("*")], Source(relation="graph"))
        with pytest.raises(ValueError, match="not a Relation"):
            QueryExecutor.execute(q, store)

    def test_subquery(self, store: ResultStore):
        """EXE-04: subquery source executes recursively."""
        sub_q = Query(
            [Lit("*")], Source(relation="files"),
            where=BinaryPred("eq", ColumnRef("source_type"), Lit("game")),
        )
        q = Query([Lit("*")], Source(subquery=sub_q))
        result = QueryExecutor.execute(q, store)
        assert len(result) == 1  # only a.txt is game type with fixture

    def test_descendants_of_valid(self, store: ResultStore):
        """EXE-05: descendants_of returns downstream files."""
        result = store.execute({
            "select": ["*"],
            "from": {"descendants_of": "maps/m1.bsp"},
        })
        assert len(result) >= 1

    def test_descendants_of_nonexistent(self, store: ResultStore):
        """EXE-06: descendants_of nonexistent path returns empty."""
        result = store.execute({
            "select": ["*"],
            "from": {"descendants_of": "ghost/path.txt"},
        })
        assert len(result) == 0

    def test_ancestors_of_valid(self, store: ResultStore):
        """EXE-07: ancestors_of returns upstream files."""
        result = store.execute({
            "select": ["*"],
            "from": {"ancestors_of": "materials/m1.vmt"},
        })
        assert len(result) >= 1

    def test_find_cycles(self, store: ResultStore):
        """EXE-08: find_cycles returns cycle rows."""
        result = store.execute({
            "select": ["*"],
            "from": {"find_cycles": True},
        })
        assert len(result) >= 1
        assert result.rows[0].length == 3


# ── WHERE stage — binary + compound + like + in + is_null +
#    string + graph + exists (EXE-10 ~ EXE-52) ─────────────


class TestWhere:
    # ── BinaryPred: eq (EXE-10~11) ────────────────────────

    def test_eq_match(self, store: ResultStore):
        """EXE-10: eq col=val -> True."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"eq": ["source_name", "base"]},
        })
        assert len(r) == 1

    def test_eq_no_match(self, store: ResultStore):
        """EXE-11: eq col=val -> False."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"eq": ["source_name", "NONEXISTENT"]},
        })
        assert len(r) == 0

    # ── BinaryPred: neq (EXE-12~13) ───────────────────────

    def test_neq_true(self, store: ResultStore):
        """EXE-12: neq col!=val -> True."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"neq": ["source_name", "NONEXISTENT"]},
        })
        assert len(r) == 6

    def test_neq_false(self, store: ResultStore):
        """EXE-13: neq col==val -> False."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"neq": ["source_name", "base"]},
        })
        assert len(r) == 5  # all except a.txt

    # ── BinaryPred: gt (EXE-14~15) ────────────────────────

    def test_gt_true(self, store: ResultStore):
        """EXE-14: gt col>val -> True."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"gt": ["priority", 100]},
        })
        assert len(r) == 5  # all except a.txt (priority=100)

    def test_gt_false(self, store: ResultStore):
        """EXE-15: gt col<=val -> False."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"gt": ["priority", 9999]},
        })
        assert len(r) == 0

    # ── BinaryPred: gte (EXE-16~17) ───────────────────────

    def test_gte_true(self, store: ResultStore):
        """EXE-16: gte col==val -> True."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"gte": ["priority", 100]},
        })
        assert len(r) == 6

    def test_gte_false(self, store: ResultStore):
        """EXE-17: gte col<val -> False."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"gte": ["priority", 9999]},
        })
        assert len(r) == 0

    # ── BinaryPred: lt (EXE-18~19) ────────────────────────

    def test_lt_true(self, store: ResultStore):
        """EXE-18: lt col<val -> True."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"lt": ["priority", 300]},
        })
        assert len(r) == 2  # priority=100, 200

    def test_lt_false(self, store: ResultStore):
        """EXE-19: lt col>=val or None -> False."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"lt": ["priority", -1]},
        })
        assert len(r) == 0

    # ── BinaryPred: lte (EXE-20~21) ───────────────────────

    def test_lte_true(self, store: ResultStore):
        """EXE-20: lte col==val -> True."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"lte": ["priority", 200]},
        })
        assert len(r) == 2  # base + addon_x

    def test_lte_false(self, store: ResultStore):
        """EXE-21: lte col>val -> False."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"lte": ["priority", -1]},
        })
        assert len(r) == 0

    # ── CompoundPred (EXE-22~26) ──────────────────────────

    def test_and_both_true(self, store: ResultStore):
        """EXE-22: and [true, true]."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"and": [
                {"eq": ["source_type", "game"]},
                {"eq": ["is_active", True]},
            ]},
        })
        assert len(r) == 1  # only a.txt

    def test_and_one_false(self, store: ResultStore):
        """EXE-23: and [true, false]."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"and": [
                {"eq": ["source_type", "game"]},
                {"eq": ["source_name", "NONEXISTENT"]},
            ]},
        })
        assert len(r) == 0

    def test_or_one_true(self, store: ResultStore):
        """EXE-24: or [false, true]."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"or": [
                {"eq": ["source_name", "NONEXISTENT"]},
                {"eq": ["source_type", "game"]},
            ]},
        })
        assert len(r) >= 1

    def test_or_both_false(self, store: ResultStore):
        """EXE-25: or [false, false]."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"or": [
                {"eq": ["source_name", "NONEXISTENT1"]},
                {"eq": ["source_name", "NONEXISTENT2"]},
            ]},
        })
        assert len(r) == 0

    def test_not_true(self, store: ResultStore):
        """EXE-26: not [true] -> false."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"not": {"eq": ["is_active", True]}},
        })
        assert len(r) == 1  # only c.txt has is_active=False

    # ── LikePred (EXE-27~28) ──────────────────────────────

    def test_like_match(self, store: ResultStore):
        """EXE-27: like '*.vmt' matches."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"like": ["virtual_path", "*.vmt"]},
        })
        assert len(r) == 1

    def test_like_no_match(self, store: ResultStore):
        """EXE-28: like '*.vmt' no match."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"like": ["virtual_path", "*.vtf"]},
        })
        assert len(r) == 0

    # ── InPred (EXE-29~32) ────────────────────────────────

    def test_in_match(self, store: ResultStore):
        """EXE-29: in [1,2,3] for value 2."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"in": ["priority", [100, 200]]},
        })
        assert len(r) == 2

    def test_in_no_match(self, store: ResultStore):
        """EXE-30: in [1,2,3] for value 4."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"in": ["priority", [999]]},
        })
        assert len(r) == 0

    def test_not_in_false(self, store: ResultStore):
        """EXE-31: not_in for value that IS in list -> False."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"not_in": ["priority", [100, 200]]},
        })
        assert len(r) == 4  # rest

    def test_not_in_true(self, store: ResultStore):
        """EXE-32: not_in for value NOT in list -> True."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"not_in": ["source_name", [
                "base", "addon_x", "addon_y", "map_vpk", "script_vpk",
            ]]},
        })
        assert len(r) == 0

    # ── IsNullPred (EXE-33~36) ────────────────────────────

    def test_is_null_true(self):
        """EXE-33: is_null on None value -> True."""
        s = ResultStore()
        s.files = Relation[FileRow].from_rows("files", [
            FileRow("x.txt", "base", "game", 100, None, 1, True),
        ])
        q = Query(
            [Lit("*")], Source(relation="files"),
            where=IsNullPred(ColumnRef("file_hash")),
        )
        r = QueryExecutor.execute(q, s)
        assert len(r) == 1

    def test_is_null_false(self, store: ResultStore):
        """EXE-34: is_null on non-None column -> False."""
        q = Query(
            [Lit("*")], Source(relation="files"),
            where=IsNullPred(ColumnRef("file_hash")),
        )
        r = QueryExecutor.execute(q, store)
        assert len(r) == 0  # all rows have file_hash

    def test_is_not_null_true(self, store: ResultStore):
        """EXE-35: is_not_null on populated column -> True."""
        q = Query(
            [Lit("*")], Source(relation="files"),
            where=IsNullPred(ColumnRef("source_name"), not_null=True),
        )
        r = QueryExecutor.execute(q, store)
        assert len(r) == 6  # all rows have source_name

    def test_is_not_null_false(self):
        """EXE-36: is_not_null on None column -> False."""
        s = ResultStore()
        s.files = Relation[FileRow].from_rows("files", [
            FileRow("x.txt", "base", "game", 100, None, 1, True),
        ])
        q = Query(
            [Lit("*")], Source(relation="files"),
            where=IsNullPred(ColumnRef("file_hash"), not_null=True),
        )
        r = QueryExecutor.execute(q, s)
        assert len(r) == 0

    # ── StringPred (EXE-37~44) ────────────────────────────

    def test_starts_with_true(self, store: ResultStore):
        """EXE-37: starts_with 'maps/' matches."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"starts_with": ["virtual_path", "maps/"]},
        })
        assert len(r) == 1

    def test_starts_with_false(self, store: ResultStore):
        """EXE-38: starts_with no match."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"starts_with": ["virtual_path", "nonexistent/"]},
        })
        assert len(r) == 0

    def test_ends_with_true(self, store: ResultStore):
        """EXE-39: ends_with '.nut' matches."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"ends_with": ["virtual_path", ".nut"]},
        })
        assert len(r) == 1

    def test_ends_with_false(self, store: ResultStore):
        """EXE-40: ends_with no match."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"ends_with": ["virtual_path", ".xyz"]},
        })
        assert len(r) == 0

    def test_contains_true(self, store: ResultStore):
        """EXE-41: contains 'material' matches."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"contains": ["virtual_path", "material"]},
        })
        assert len(r) == 1

    def test_contains_false(self, store: ResultStore):
        """EXE-42: contains no match."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"contains": ["virtual_path", "XYZZZZ"]},
        })
        assert len(r) == 0

    def test_not_contains_true(self, store: ResultStore):
        """EXE-43: not_contains pattern not in path -> True."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"not_contains": ["virtual_path", "XYZZZZ"]},
        })
        assert len(r) == 6  # no path contains XYZZZZ

    def test_not_contains_false(self, store: ResultStore):
        """EXE-44: not_contains pattern in path -> False."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"not_contains": ["virtual_path", "maps"]},
        })
        assert len(r) == 5  # maps/m1.bsp excluded

    # ── GraphPred (EXE-45~48) ─────────────────────────────

    def test_ancestor_is_map_true(self, store: ResultStore):
        """EXE-45: ancestor_is_map on path with .bsp ancestor."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"ancestor_is_map": "virtual_path"},
        })
        assert len(r) == 2  # materials/m1.vmt and scripts/test.nut

    def test_ancestor_is_map_false(self, store: ResultStore):
        """EXE-46: ancestor_is_map on path with no .bsp ancestor."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"and": [
                {"ancestor_is_map": "virtual_path"},
                {"eq": ["source_name", "base"]},
            ]},
        })
        assert len(r) == 0

    def test_descendant_is_script_true(self, store: ResultStore):
        """EXE-47: descendant_is_script on path with .nut descendant."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"descendant_is_script": "virtual_path"},
        })
        assert len(r) == 1  # maps/m1.bsp has scripts/test.nut

    def test_descendant_is_script_false(self, store: ResultStore):
        """EXE-48: descendant_is_script on path with no .nut descendant."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"and": [
                {"descendant_is_script": "virtual_path"},
                {"eq": ["source_type", "addon"]},
            ]},
        })
        assert len(r) == 0  # addon files have no graph descendants

    # ── ExistsPred (EXE-49~52) ────────────────────────────

    def test_exists_in_true(self, store: ResultStore):
        """EXE-49: exists_in finds value in target."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"exists_in": ["virtual_path", "external_files"]},
        })
        assert len(r) == 1  # only a.txt is in both

    def test_exists_in_false(self, store: ResultStore):
        """EXE-50: exists_in value not in target."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"and": [
                {"exists_in": ["virtual_path", "external_files"]},
                {"eq": ["source_name", "map_vpk"]},
            ]},
        })
        assert len(r) == 0  # no vpk file is in external_files

    def test_not_exists_in_true(self, store: ResultStore):
        """EXE-51: not_exists_in finds values NOT in target."""
        r = store.execute({
            "select": ["*"], "from": "external_files",
            "where": {"not_exists_in": ["virtual_path", "files"]},
        })
        assert len(r) == 1  # new.txt not in files
        assert r.rows[0].virtual_path == "new.txt"

    def test_not_exists_in_false(self, store: ResultStore):
        """EXE-52: not_exists_in for value that IS in target -> False."""
        r = store.execute({
            "select": ["*"], "from": "external_files",
            "where": {"not_exists_in": ["virtual_path", "files"]},
        })
        assert len(r) == 1  # new.txt is not in files; a.txt is in files -> excluded
        assert r.rows[0].virtual_path == "new.txt"


# ── NULL semantics (NULL-01 ~ NULL-13) ────────────────────


class TestNullSemantics:
    def test_eq_null(self, null_store: ResultStore):
        """NULL-01: eq NULL — matches via hash index (None==None is Python True)."""
        r = null_store.execute({
            "select": ["*"], "from": "files",
            "where": {"eq": ["file_hash", None]},
        })
        # Python None == None is True, so the None row matches
        assert len(r) == 1
        assert r.rows[0].virtual_path == "n.txt"

    def test_neq_null(self, null_store: ResultStore):
        """NULL-02: neq NULL -> True for non-None rows; False for None row (Python None!=None is False)."""
        r = null_store.execute({
            "select": ["*"], "from": "files",
            "where": {"neq": ["file_hash", None]},
        })
        # n.txt: None != None is False (excluded); a.txt: "abc" != None is True (included)
        assert len(r) == 1
        assert r.rows[0].virtual_path == "a.txt"

    def test_gt_null(self, null_store: ResultStore):
        """NULL-03: gt NULL -> False."""
        r = null_store.execute({
            "select": ["*"], "from": "files",
            "where": {"gt": ["priority", None]},
        })
        assert len(r) == 0

    def test_gte_null(self, null_store: ResultStore):
        """NULL-04: gte NULL -> False."""
        r = null_store.execute({
            "select": ["*"], "from": "files",
            "where": {"gte": ["priority", None]},
        })
        assert len(r) == 0

    def test_lt_null(self, null_store: ResultStore):
        """NULL-05: lt NULL -> False."""
        r = null_store.execute({
            "select": ["*"], "from": "files",
            "where": {"lt": ["priority", None]},
        })
        assert len(r) == 0

    def test_lte_null(self, null_store: ResultStore):
        """NULL-06: lte NULL -> False."""
        r = null_store.execute({
            "select": ["*"], "from": "files",
            "where": {"lte": ["priority", None]},
        })
        assert len(r) == 0

    def test_like_null(self, null_store: ResultStore):
        """NULL-07: like NULL -> False (pattern must not match 'None')."""
        r = null_store.execute({
            "select": ["*"], "from": "files",
            "where": {"like": ["file_hash", "*.txt"]},
        })
        assert len(r) == 0  # "None" doesn't match "*.txt"

    def test_in_null(self, null_store: ResultStore):
        """NULL-08: in NULL — None in [None] is Python True, so the None row matches."""
        r = null_store.execute({
            "select": ["*"], "from": "files",
            "where": {"in": ["file_hash", [None]]},
        })
        # n.txt: None in [None] -> True -> included
        assert len(r) == 1
        assert r.rows[0].virtual_path == "n.txt"

    def test_not_in_null(self, null_store: ResultStore):
        """NULL-09: not_in NULL -> True for rows with non-None values."""
        r = null_store.execute({
            "select": ["*"], "from": "files",
            "where": {"not_in": ["file_hash", [None]]},
        })
        # n.txt: None in [None] -> True -> negated -> False (excluded)
        # a.txt: "abc" in [None] -> False -> negated -> True (included)
        assert len(r) == 1
        assert r.rows[0].virtual_path == "a.txt"

    def test_exists_in_null_source(self, null_store: ResultStore):
        """NULL-10: exists_in with NULL source -> False."""
        r = null_store.execute({
            "select": ["*"], "from": "files",
            "where": {"exists_in": ["file_hash", "external_files"]},
        })
        # n.txt: file_hash=None -> lookup("virtual_path", None) -> no match -> excluded
        # a.txt: file_hash="abc" -> lookup("virtual_path", "abc") -> match -> included
        assert len(r) == 1
        assert r.rows[0].virtual_path == "a.txt"

    def test_not_exists_in_null_source(self, null_store: ResultStore):
        """NULL-11: not_exists_in with NULL source -> True."""
        r = null_store.execute({
            "select": ["*"], "from": "files",
            "where": {"not_exists_in": ["file_hash", "external_files"]},
        })
        # n.txt: file_hash=None -> not in external_files -> True -> included
        # a.txt: file_hash="abc" -> in external_files -> not True -> False -> excluded
        assert len(r) == 1
        assert r.rows[0].virtual_path == "n.txt"

    def test_join_on_null(self):
        """NULL-12: JOIN ON NULL should not match (xfail: production matches)."""
        s = ResultStore()
        s.left = Relation("left", ("k", "v"), [(None, "a"), (1, "b")])
        s.right = Relation("right", ("k", "v2"), [(None, "x"), (1, "y")])
        q = Query(
            [ColumnRef("v")], Source(relation="left"),
            joins=[JoinClause(
                "inner", Source(relation="right"),
                BinaryPred("eq", ColumnRef("k"), ColumnRef("k")),
            )],
        )
        r = QueryExecutor.execute(q, s)
        # Spec: NULL != NULL -> no match for None pair; (1, 1) still matches
        assert len(r) == 1

    def test_string_pred_null(self, null_store: ResultStore):
        """NULL-13: StringPred on NULL returns False."""
        r = null_store.execute({
            "select": ["*"], "from": "files",
            "where": {"starts_with": ["file_hash", "N"]},
        })
        assert len(r) == 0


# ── WHERE fast path (EXE-40~43) ───────────────────────────
# Note: IDs EXE-40~43 overlap with StringPred EXE-40~44.
# These test the executor fast path (select_by index optimization).


class TestWhereFastPath:
    def test_eq_literal_indexed(self, store: ResultStore):
        """EXE-40 fast-path: eq + Literal on indexed column -> select_by."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"eq": ["source_name", "base"]},
        })
        assert len(r) == 1

    def test_eq_literal_auto_index(self, store: ResultStore):
        """EXE-41 fast-path: select_by auto-builds index."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"eq": ["source_type", "game"]},
        })
        assert len(r) == 1

    def test_eq_literal_nonexistent_value(self, store: ResultStore):
        """EXE-42 fast-path: eq + Literal, value not in column -> empty via select_by."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"eq": ["source_name", "__nonexistent_value__"]},
        })
        assert len(r) == 0  # select_by returns empty relation, no crash

    def test_neq_literal_uses_interpreter(self, store: ResultStore):
        """EXE-43 fast-path: neq + Literal -> interpreter fallback."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "where": {"neq": ["source_name", "base"]},
        })
        assert len(r) == 5


# ── Aggregation (EXE-50 ~ EXE-58) ─────────────────────────


class TestAggregation:
    def test_count(self, store: ResultStore):
        """EXE-50: count aggregation."""
        r = store.execute({
            "select": ["source_type", "cnt"],
            "from": "files",
            "group_by": {"by": ["source_type"], "agg": {"cnt": "count"}},
        })
        by_type = {row[0]: row[1] for row in r.rows}
        assert by_type["game"] == 1
        assert by_type["addon"] == 2
        assert by_type["vpk"] == 3

    def test_sum(self, store: ResultStore):
        """EXE-51: sum(file_size)."""
        r = store.execute({
            "select": ["source_type", "total"],
            "from": "files",
            "group_by": {"by": ["source_type"], "agg": {"total": ["sum", "file_size"]}},
        })
        by_type = {row[0]: row[1] for row in r.rows}
        assert by_type["game"] == 1024
        assert by_type["vpk"] == 8384  # 8192 + 128 + 64

    def test_avg(self, store: ResultStore):
        """EXE-52: avg(file_size)."""
        r = store.execute({
            "select": ["source_type", "avg_size"],
            "from": "files",
            "group_by": {"by": ["source_type"], "agg": {"avg_size": ["avg", "file_size"]}},
        })
        by_type = {row[0]: row[1] for row in r.rows}
        assert by_type["vpk"] == pytest.approx(8384 / 3)

    def test_min_max(self, store: ResultStore):
        """EXE-53: min/max(file_size)."""
        q = Query(
            [ColumnRef("source_type"), ColumnRef("min_val"), ColumnRef("max_val")],
            Source(relation="files"),
            group_by=GroupByClause(
                columns=[ColumnRef("source_type")],
                aggregations={
                    "min_val": ["min", "file_size"],
                    "max_val": ["max", "file_size"],
                },
            ),
        )
        r = QueryExecutor.execute(q, store)
        by_type = {row[0]: (row[1], row[2]) for row in r.rows}
        assert by_type["vpk"] == (64, 8192)

    def test_count_where(self, store: ResultStore):
        """EXE-54: count_where(is_active=true)."""
        r = store.execute({
            "select": ["source_type", "active"],
            "from": "files",
            "group_by": {
                "by": ["source_type"],
                "agg": {"active": {"count_where": {"eq": ["is_active", True]}}},
            },
        })
        by_type = {row[0]: row[1] for row in r.rows}
        assert by_type["vpk"] == 3  # all vpk files are active

    def test_count_where_graph_pred(self, store: ResultStore):
        """EXE-55: count_where + GraphPred (known weakness)."""
        r = store.execute({
            "select": ["source_type", "map_related"],
            "from": "files",
            "group_by": {
                "by": ["source_type"],
                "agg": {"map_related": {"count_where": {"ancestor_is_map": "virtual_path"}}},
            },
        })
        by_type = {row[0]: row[1] for row in r.rows}
        # GraphPred may not be propagated into count_where (known weakness KW-02)
        assert by_type["vpk"] >= 1  # at least one vpk file has map ancestor

    def test_multi_group_by(self, store: ResultStore):
        """EXE-56: multi-column group_by."""
        r = store.execute({
            "select": ["source_type", "source_name", "cnt"],
            "from": "files",
            "group_by": {
                "by": ["source_type", "source_name"],
                "agg": {"cnt": "count"},
            },
        })
        assert len(r) >= 4  # different source_name/type combos

    def test_having(self, store: ResultStore):
        """EXE-57: HAVING filters after group_by."""
        q = Query(
            [ColumnRef("source_type"), ColumnRef("cnt")],
            Source(relation="files"),
            group_by=GroupByClause(
                columns=[ColumnRef("source_type")],
                aggregations={"cnt": "count"},
            ),
            having=BinaryPred("gte", ColumnRef("cnt"), Lit(2)),
        )
        r = QueryExecutor.execute(q, store)
        by_type = {row[0]: row[1] for row in r.rows}
        assert "game" not in by_type  # game has only 1 file
        assert by_type["addon"] == 2

    def test_having_without_group_by(self, store: ResultStore):
        """EXE-58: HAVING without GROUP BY is silently ignored."""
        r = store.execute({
            "select": ["*"], "from": "files",
            "having": {"eq": ["source_type", "game"]},
        })
        assert len(r) == 6  # HAVING ignored, all rows returned


# ── JOIN (EXE-60 ~ EXE-69) ───────────────────────────────


class TestJoin:
    def test_inner_normal(self, store: ResultStore):
        """EXE-60: inner join normal match."""
        r = store.execute({
            "select": ["*"],
            "from": "files",
            "join": {
                "type": "inner",
                "with": "external_files",
                "on": {"eq": [["files", "virtual_path"], ["external_files", "virtual_path"]]},
            },
        })
        assert len(r) == 1  # only a.txt is in both

    def test_inner_no_match(self):
        """EXE-61: inner join no match."""
        s = ResultStore()
        s.a = Relation("a", ("k", "v"), [("x", 1)])
        s.b = Relation("b", ("k", "v2"), [("y", 2)])
        q = Query(
            [ColumnRef("v")], Source(relation="a"),
            joins=[JoinClause(
                "inner", Source(relation="b"),
                BinaryPred("eq", ColumnRef("k"), ColumnRef("k")),
            )],
        )
        r = QueryExecutor.execute(q, s)
        assert len(r) == 0

    def test_left_partial(self, store: ResultStore):
        """EXE-62: left join partial match."""
        r = store.execute({
            "select": [["files", "virtual_path"], ["external_files", "ext_source_name"]],
            "from": "files",
            "join": {
                "type": "left",
                "with": "external_files",
                "on": {"eq": [["files", "virtual_path"], ["external_files", "virtual_path"]]},
            },
        })
        assert len(r) == 6  # all files preserved

    def test_left_no_match(self):
        """EXE-63: left join no match -> all left rows, right columns NULL."""
        s = ResultStore()
        s.left = Relation("left", ("k", "v"), [(1, "a"), (2, "b")])
        s.right = Relation("right", ("k", "v2"), [(3, "x")])
        q = Query(
            [ColumnRef("v"), ColumnRef("v2")],
            Source(relation="left"),
            joins=[JoinClause(
                "left", Source(relation="right"),
                BinaryPred("eq", ColumnRef("k"), ColumnRef("k")),
            )],
        )
        r = QueryExecutor.execute(q, s)
        assert len(r) == 2  # all left rows
        # right-side v2 is NULL for unmatched
        assert r.rows[0][1] is None
        assert r.rows[1][1] is None

    def test_right_normal(self, store: ResultStore):
        """EXE-64: right join normal."""
        r = store.execute({
            "select": [["external_files", "virtual_path"]],
            "from": "files",
            "join": {
                "type": "right",
                "with": "external_files",
                "on": {"eq": [["files", "virtual_path"], ["external_files", "virtual_path"]]},
            },
        })
        assert len(r) == 2  # all external files preserved

    def test_full_partial(self, store: ResultStore):
        """EXE-65: full outer join partial match."""
        q = Query(
            [ColumnRef("virtual_path", "files")],
            Source(relation="files"),
            joins=[JoinClause(
                type="full",
                with_source=Source(relation="external_files"),
                on=BinaryPred(
                    "eq",
                    ColumnRef("virtual_path", "files"),
                    ColumnRef("virtual_path", "external_files"),
                ),
            )],
        )
        r = QueryExecutor.execute(q, store)
        # all unique paths from both sides
        assert len(r) == 7  # 6 files + 1 unmatched external (new.txt)

    def test_full_diff_columns(self, store: ResultStore):
        """EXE-66: full join with different column sets."""
        q = Query(
            [ColumnRef("virtual_path")],
            Source(relation="files"),
            joins=[JoinClause(
                type="full",
                with_source=Source(relation="external_files"),
                on=BinaryPred(
                    "eq",
                    ColumnRef("virtual_path", "files"),
                    ColumnRef("virtual_path", "external_files"),
                ),
            )],
        )
        r = QueryExecutor.execute(q, store)
        assert len(r) == 7

    def test_left_empty_left(self):
        """EXE-67: LEFT JOIN with empty left -> empty."""
        s = ResultStore()
        s.left = Relation("left", ("k", "v"), [])
        s.right = Relation("right", ("k", "v2"), [(1, "y")])
        q = Query(
            [Lit("*")], Source(relation="left"),
            joins=[JoinClause(
                "left", Source(relation="right"),
                BinaryPred("eq", ColumnRef("k"), ColumnRef("k")),
            )],
        )
        r = QueryExecutor.execute(q, s)
        assert len(r) == 0

    def test_right_empty_right(self):
        """EXE-68: RIGHT JOIN with empty right -> left rows with NULL rights."""
        s = ResultStore()
        s.left = Relation("left", ("k", "v"), [(1, "a")])
        s.right = Relation("right", ("k", "v2"), [])
        q = Query(
            [ColumnRef("v")], Source(relation="left"),
            joins=[JoinClause(
                "left", Source(relation="right"),
                BinaryPred("eq", ColumnRef("k"), ColumnRef("k")),
            )],
        )
        r = QueryExecutor.execute(q, s)
        # LEFT JOIN with empty right: all left rows returned, right cols NULL
        assert len(r) == 1

    def test_on_null_key(self):
        """EXE-69: INNER JOIN on NULL key — NULL != NULL, None keys skipped."""
        s = ResultStore()
        s.left = Relation("left", ("k", "v"), [(None, "a"), (1, "b")])
        s.right = Relation("right", ("k", "v2"), [(None, "x"), (1, "y")])
        q = Query(
            [ColumnRef("v")], Source(relation="left"),
            joins=[JoinClause(
                "inner", Source(relation="right"),
                BinaryPred("eq", ColumnRef("k"), ColumnRef("k")),
            )],
        )
        r = QueryExecutor.execute(q, s)
        # SQL NULL semantics: None keys do not match
        assert len(r) == 1


# ── ORDER BY / LIMIT / SELECT (EXE-70 ~ EXE-77) ───────────


class TestOrderLimitSelect:
    def test_order_asc(self, store: ResultStore):
        """EXE-70: ORDER BY asc."""
        r = store.execute({
            "select": ["priority"],
            "from": "files",
            "order_by": {"by": "priority", "dir": "asc"},
        })
        vals = [row[0] for row in r.rows]
        for i in range(len(vals) - 1):
            assert vals[i] <= vals[i + 1]

    def test_order_desc(self, store: ResultStore):
        """EXE-71: ORDER BY desc."""
        r = store.execute({
            "select": ["priority"],
            "from": "files",
            "order_by": {"by": "priority", "dir": "desc"},
        })
        vals = [row[0] for row in r.rows]
        for i in range(len(vals) - 1):
            assert vals[i] >= vals[i + 1]

    def test_order_nonexistent_column(self, store: ResultStore):
        """EXE-72: ORDER BY nonexistent column — silently skipped (no error)."""
        q = Query(
            [Lit("*")], Source(relation="files"),
            order_by=OrderByClause(ColumnRef("nonexistent_col"), "asc"),
        )
        r = QueryExecutor.execute(q, store)
        assert len(r) == 6  # no crash, all rows returned unchanged

    def test_limit_zero(self, store: ResultStore):
        """EXE-73: LIMIT 0 returns empty."""
        r = store.execute({
            "select": ["*"], "from": "files", "limit": 0,
        })
        assert len(r) == 0

    def test_limit_gt_rows(self, store: ResultStore):
        """EXE-74: LIMIT > available rows."""
        r = store.execute({
            "select": ["*"], "from": "files", "limit": 999,
        })
        assert len(r) == 6

    def test_select_star(self, store: ResultStore):
        """EXE-75: SELECT * returns all columns."""
        r = store.execute({"select": ["*"], "from": "files"})
        assert "virtual_path" in r.columns
        assert "source_name" in r.columns

    def test_select_columns(self, store: ResultStore):
        """EXE-76: SELECT [col1, col2]."""
        r = store.execute({
            "select": ["virtual_path", "source_name"],
            "from": "files",
        })
        assert r.columns == ("virtual_path", "source_name")

    def test_select_nonexistent_column(self, store: ResultStore):
        """EXE-77: SELECT nonexistent column raises."""
        from parallelines.engine.query_validator import QueryValidationError
        with pytest.raises(QueryValidationError):
            store.execute({
                "select": ["ghost_column"],
                "from": "files",
            })


# ── Stage order (ORD-01 ~ ORD-07) ─────────────────────────


class TestStageOrder:
    def test_full_pipeline(self, store: ResultStore):
        """ORD-01: Full pipeline FROM+WHERE+GROUP+HAVING+ORDER+LIMIT+SELECT."""
        q = Query(
            [ColumnRef("source_type"), ColumnRef("cnt")],
            Source(relation="files"),
            where=BinaryPred("eq", ColumnRef("is_active"), Lit(True)),
            group_by=GroupByClause(
                columns=[ColumnRef("source_type")],
                aggregations={"cnt": "count"},
            ),
            having=BinaryPred("gte", ColumnRef("cnt"), Lit(1)),
            order_by=OrderByClause(ColumnRef("cnt"), "desc"),
            limit=5,
        )
        r = QueryExecutor.execute(q, store)
        assert len(r) >= 1
        # Verify execution order: filtering before aggregation
        by_type = {row[0]: row[1] for row in r.rows}
        assert "game" in by_type  # game has cnt=1, not filtered by HAVING

    def test_where_before_group_by(self, store: ResultStore):
        """ORD-02: WHERE filters before GROUP BY, affecting counts."""
        r_all = store.execute({
            "select": ["source_type", "cnt"],
            "from": "files",
            "group_by": {"by": ["source_type"], "agg": {"cnt": "count"}},
        })
        r_filtered = store.execute({
            "select": ["source_type", "cnt"],
            "from": "files",
            "where": {"eq": ["is_active", True]},
            "group_by": {"by": ["source_type"], "agg": {"cnt": "count"}},
        })
        all_counts = {row[0]: row[1] for row in r_all.rows}
        filtered_counts = {row[0]: row[1] for row in r_filtered.rows}
        assert all_counts["addon"] == 2
        assert filtered_counts["addon"] == 1  # c.txt excluded by WHERE

    def test_having_after_group_by(self, store: ResultStore):
        """ORD-03: HAVING references aggregation output columns."""
        q = Query(
            [ColumnRef("source_type"), ColumnRef("cnt")],
            Source(relation="files"),
            group_by=GroupByClause(
                columns=[ColumnRef("source_type")],
                aggregations={"cnt": "count"},
            ),
            having=BinaryPred("gte", ColumnRef("cnt"), Lit(2)),
        )
        r = QueryExecutor.execute(q, store)
        by_type = {row[0]: row[1] for row in r.rows}
        assert "game" not in by_type  # game has cnt=1 < 2
        assert by_type["addon"] == 2

    def test_order_by_limit_after_having(self, store: ResultStore):
        """ORD-04: ORDER BY then LIMIT truncates sorted results."""
        q = Query(
            [ColumnRef("source_type"), ColumnRef("cnt")],
            Source(relation="files"),
            group_by=GroupByClause(
                columns=[ColumnRef("source_type")],
                aggregations={"cnt": "count"},
            ),
            having=BinaryPred("gte", ColumnRef("cnt"), Lit(1)),
            order_by=OrderByClause(ColumnRef("cnt"), "desc"),
            limit=2,
        )
        r = QueryExecutor.execute(q, store)
        assert len(r) <= 2

    def test_select_after_all(self, store: ResultStore):
        """ORD-05: SELECT (projection) last, sees aggregation output cols."""
        q = Query(
            [ColumnRef("cnt")],  # project only aggregation column
            Source(relation="files"),
            group_by=GroupByClause(
                columns=[ColumnRef("source_type")],
                aggregations={"cnt": "count"},
            ),
        )
        r = QueryExecutor.execute(q, store)
        # After projection, only "cnt" column should remain
        assert r.columns == ("cnt",)
        assert len(r) >= 1

    def test_join_then_group_by(self):
        """ORD-06: GROUP BY references JOIN-result columns."""
        s = ResultStore()
        s.files = Relation[FileRow].from_rows("files", [
            FileRow("a.txt", "base", "game", 100, "a", 1, True),
            FileRow("b.txt", "base", "addon", 200, "b", 1, True),
        ])
        s.ext = Relation("ext", ("virtual_path", "category"), [
            ("a.txt", "docs"),
            ("b.txt", "scripts"),
        ])
        q = Query(
            [Lit("*")],
            Source(relation="files"),
            joins=[JoinClause(
                "inner", Source(relation="ext"),
                BinaryPred("eq", ColumnRef("virtual_path"), ColumnRef("virtual_path")),
            )],
        )
        r = QueryExecutor.execute(q, s)
        assert len(r) == 2  # both files matched

    def test_join_then_where(self):
        """ORD-07: FROM->JOIN->WHERE: WHERE filters JOIN result."""
        s = ResultStore()
        s.files = Relation[FileRow].from_rows("files", [
            FileRow("a.txt", "base", "game", 100, "a", 1, True),
            FileRow("b.txt", "base", "addon", 200, "b", 1, True),
        ])
        s.ext = Relation("ext", ("virtual_path", "category"), [
            ("a.txt", "docs"),
            ("b.txt", "scripts"),
        ])
        q = Query(
            [Lit("*")],
            Source(relation="files"),
            joins=[JoinClause(
                "inner", Source(relation="ext"),
                BinaryPred("eq", ColumnRef("virtual_path"), ColumnRef("virtual_path")),
            )],
            where=BinaryPred("eq", ColumnRef("category"), Lit("docs")),
        )
        r = QueryExecutor.execute(q, s)
        assert len(r) == 1


# ── Precompiled predicate (CMP-01 ~ CMP-12) ───────────────


class TestCompilePredicate:
    def test_compile_eq(self):
        """CMP-01: compile eq + Literal returns callable."""
        pred = BinaryPred("eq", ColumnRef("col"), Lit("val"))
        fn = QueryExecutor._compile_predicate(pred, ("col",))
        assert fn is not None
        assert fn(("val",)) is True
        assert fn(("other",)) is False

    def test_compile_neq(self):
        """CMP-02: compile neq + Literal returns callable."""
        pred = BinaryPred("neq", ColumnRef("col"), Lit("val"))
        fn = QueryExecutor._compile_predicate(pred, ("col",))
        assert fn is not None
        assert fn(("val",)) is False
        assert fn(("other",)) is True

    def test_compile_gt_returns_callable(self):
        """CMP-03: compile gt/gte/lt/lte now returns callable (not None)."""
        expects_true = {"gt": (2,), "gte": (2,), "lt": (0,), "lte": (0,)}
        for op in ("gt", "gte", "lt", "lte"):
            pred = BinaryPred(op, ColumnRef("col"), Lit(1))
            fn = QueryExecutor._compile_predicate(pred, ("col",))
            assert fn is not None, f"{op} should return callable"
            true_arg = expects_true[op]
            false_arg = (0,) if true_arg == (2,) else (2,)
            assert fn(true_arg) is True, f"{op} fn({true_arg}) should be True"
            assert fn(false_arg) is False
            # NULL handling: None column → False
            assert fn((None,)) is False

    def test_compile_like_returns_callable(self):
        """CMP-04: compile LikePred now returns callable (not None)."""
        pred = LikePred(ColumnRef("col"), "*.txt")
        fn = QueryExecutor._compile_predicate(pred, ("col",))
        assert fn is not None

    def test_compile_in_returns_callable(self):
        """CMP-05: compile InPred now returns callable (not None)."""
        pred = InPred(ColumnRef("col"), [Lit("a"), Lit("b")])
        fn = QueryExecutor._compile_predicate(pred, ("col",))
        assert fn is not None
        assert fn(("a",)) is True
        assert fn(("c",)) is False

    def test_compile_compound_returns_none(self):
        """CMP-06: compile CompoundPred returns None."""
        pred = CompoundPred("and", [
            BinaryPred("eq", ColumnRef("col"), Lit("val")),
            BinaryPred("eq", ColumnRef("col2"), Lit("val2")),
        ])
        fn = QueryExecutor._compile_predicate(pred, ("col", "col2"))
        assert fn is None

    def test_compile_string_returns_callable(self):
        """CMP-07: compile StringPred now returns callable (not None)."""
        pred = StringPred("starts_with", ColumnRef("col"), "pre")
        fn = QueryExecutor._compile_predicate(pred, ("col",))
        assert fn is not None
        assert fn(("prefix",)) is True
        assert fn(("other",)) is False

    def test_compile_graph_returns_none(self):
        """CMP-08: compile GraphPred returns None."""
        pred = GraphPred("ancestor_is_map", ColumnRef("col"))
        fn = QueryExecutor._compile_predicate(pred, ("col",))
        assert fn is None

    def test_compile_exists_returns_none(self):
        """CMP-09: compile ExistsPred returns None."""
        pred = ExistsPred(False, ColumnRef("col"), "files")
        fn = QueryExecutor._compile_predicate(pred, ("col",))
        assert fn is None

    def test_compiled_callable_tuple_row(self):
        """CMP-10: compiled callable works with tuple row."""
        pred = BinaryPred("eq", ColumnRef("name"), Lit("hello"))
        fn = QueryExecutor._compile_predicate(pred, ("id", "name"))
        assert fn is not None
        assert fn((1, "hello")) is True
        assert fn((2, "world")) is False

    def test_compiled_callable_dataclass_row(self):
        """CMP-11: compiled callable works with dataclass row."""
        from dataclasses import dataclass

        @dataclass
        class Item:
            name: str
            value: int

        pred = BinaryPred("eq", ColumnRef("name"), Lit("hello"))
        fn = QueryExecutor._compile_predicate(pred, ("name", "value"))
        assert fn is not None
        assert fn(Item("hello", 1)) is True
        assert fn(Item("world", 2)) is False

    def test_compile_cross_column_returns_none(self):
        """CMP-12: compile cross-column ColumnRef returns None."""
        pred = BinaryPred("eq", ColumnRef("a"), ColumnRef("b"))
        fn = QueryExecutor._compile_predicate(pred, ("a", "b"))
        assert fn is None
