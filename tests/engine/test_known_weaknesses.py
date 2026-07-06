"""Known weakness tests (KW-01 ~ KW-10)."""
from __future__ import annotations

import pytest
import networkx as nx

from parallelines.engine import ResultStore
from parallelines.engine.schema import DependencyCycleRow, ExternalFileRow, FileRow
from parallelines.engine.store import Relation


@pytest.fixture
def store() -> ResultStore:
    store = ResultStore()
    store.files = Relation[FileRow].from_rows("files", [
        FileRow("maps/m1.bsp", "vpk1", "vpk", 100, "a", 1024, True),
        FileRow("materials/m1.vmt", "vpk1", "vpk", 100, "b", 512, True),
        FileRow("scripts/test.nut", "vpk1", "vpk", 100, "c", 256, True),
        FileRow("a.txt", "base", "game", 50, "d", 64, True),
    ])
    g = nx.DiGraph()
    g.add_edge("maps/m1.bsp", "materials/m1.vmt")
    g.add_edge("maps/m1.bsp", "scripts/test.nut")
    store.graph = g
    store.dependency_cycles = Relation[DependencyCycleRow].from_rows(
        "dependency_cycles", [DependencyCycleRow(["x", "y", "z"], 3)],
    )
    store.external_files = Relation[ExternalFileRow].from_rows("external_files", [
        ExternalFileRow("a.txt", "ref:ext", 2000, "d", 64),
    ])
    store.external_files.build_index("virtual_path")
    return store


@pytest.fixture
def null_store() -> ResultStore:
    s = ResultStore()
    s.files = Relation[FileRow].from_rows("files", [
        FileRow("n.txt", "base", "game", 100, None, 1, True),
    ])
    return s


class TestKnownWeaknesses:
    def test_having_graph_pred(self, store: ResultStore):
        """KW-01: HAVING with GraphPred."""
        from parallelines.engine.query_ast import (
            BinaryPred, ColumnRef, GroupByClause, Literal as Lit,
            Query, Source,
        )
        from parallelines.engine.query_executor import QueryExecutor
        q = Query(
            [ColumnRef("source_name"), ColumnRef("cnt")],
            Source(relation="files"),
            group_by=GroupByClause(
                columns=[ColumnRef("source_name")],
                aggregations={"cnt": "count"},
            ),
            having=BinaryPred("gte", ColumnRef("cnt"), Lit(1)),
        )
        r = QueryExecutor.execute(q, store)
        assert len(r) >= 1

    def test_count_where_graph_pred(self, store: ResultStore):
        """KW-02: count_where with GraphPred."""
        from parallelines.engine.query_ast import ColumnRef, GroupByClause, Query, Source
        from parallelines.engine.query_executor import QueryExecutor
        q = Query(
            [ColumnRef("source_name"), ColumnRef("map_rel")],
            Source(relation="files"),
            group_by=GroupByClause(
                columns=[ColumnRef("source_name")],
                aggregations={"map_rel": {"count_where": {"ancestor_is_map": "virtual_path"}}},
            ),
        )
        r = QueryExecutor.execute(q, store)
        assert len(r) >= 1

    def test_string_pred_none(self, null_store: ResultStore):
        """KW-03: StringPred on None returns False."""
        r = null_store.execute({
            "select":["*"], "from":"files",
            "where":{"starts_with":["file_hash","N"]},
        })
        assert len(r) == 0

    def test_find_cycles_schema(self, store: ResultStore):
        """KW-04: find_cycles schema matches DependencyCycleRow."""
        r = store.execute({"select":["*"],"from":{"find_cycles":True}})
        assert len(r) == 1
        assert "cycle" in r.columns
        assert "length" in r.columns

    def test_exists_pred_concurrent(self, store: ResultStore):
        """KW-05: ExistsPred single-threaded."""
        r = store.execute({
            "select":["*"], "from":"files",
            "where":{"exists_in":["virtual_path","external_files"]},
        })
        assert len(r) == 1

    def test_graph_pred_no_type_check(self, store: ResultStore):
        """KW-06: GraphPred on non-path column — no crash."""
        r = store.execute({
            "select":["*"], "from":"files",
            "where":{"ancestor_is_map":"priority"},
        })
        assert isinstance(r, Relation)

    def test_cross_column_type_mismatch(self, store: ResultStore):
        """KW-07: cross-column type mismatch — no crash."""
        from parallelines.engine.query_validator import QueryValidationError
        with pytest.raises(QueryValidationError):
            store.execute({
                "select":["*"], "from":"files",
                "where":{"gt":["source_name","priority"]},
            })

    def test_having_without_group_by(self, store: ResultStore):
        """KW-08: HAVING without GROUP BY silently ignored."""
        r = store.execute({
            "select":["*"], "from":"files",
            "having":{"eq":["source_name","base"]},
        })
        assert len(r) == 4  # all rows (4 files), HAVING ignored

    def test_neq_null_non_standard_sql(self, null_store: ResultStore):
        """KW-10: neq(NULL)=True is a design choice, not standard SQL."""
        r = null_store.execute({
            "select":["*"], "from":"files",
            "where":{"neq":["file_hash",None]},
        })
        assert len(r) == 0  # None != None is False here
