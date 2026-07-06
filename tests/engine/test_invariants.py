"""Immutability invariant tests (INV-01 ~ INV-12)."""
from __future__ import annotations

import pytest

from parallelines.engine import ResultStore
from parallelines.engine.schema import FileRow
from parallelines.engine.store import Relation
from parallelines.engine.query_validator import QueryValidationError


@pytest.fixture
def store() -> ResultStore:
    store = ResultStore()
    store.files = Relation[FileRow].from_rows("files", [
        FileRow("a.txt", "base", "game", 100, "abc", 1024, True),
        FileRow("b.txt", "addon", "addon", 200, "def", 512, True),
    ])
    return store


class TestInvariants:
    def test_select_does_not_mutate(self, store: ResultStore):
        """INV-01: select returns new Relation, original unchanged."""
        orig = list(store.files.rows)
        store.files.select(lambda r: r.source_name == "base")
        assert list(store.files.rows) == orig

    def test_project_does_not_mutate(self, store: ResultStore):
        """INV-02: project returns new Relation, original unchanged."""
        orig = list(store.files.rows)
        store.files.project("source_name")
        assert list(store.files.rows) == orig

    def test_join_does_not_mutate(self, store: ResultStore):
        """INV-03: join does not mutate left or right."""
        other = Relation("o", ("virtual_path", "extra"), [("a.txt", "x")])
        orig_left = list(store.files.rows)
        orig_right = list(other.rows)
        store.files.join(other, on="virtual_path")
        assert list(store.files.rows) == orig_left
        assert list(other.rows) == orig_right

    def test_group_by_does_not_mutate(self, store: ResultStore):
        """INV-04: group_by returns new Relation."""
        orig = list(store.files.rows)
        store.files.group_by("source_type", {"cnt": len})
        assert list(store.files.rows) == orig

    def test_execute_does_not_modify_store(self, store: ResultStore):
        """INV-05: store.execute() does not modify store contents."""
        orig_ids = [id(r) for r in store.files.rows]
        store.execute({
            "select": ["*"], "from": "files",
            "where": {"eq": ["source_name", "base"]},
        })
        assert [id(r) for r in store.files.rows] == orig_ids

    def test_failed_query_leaves_store_intact(self, store: ResultStore):
        """INV-06: failed query leaves store unchanged."""
        orig = list(store.files.rows)
        try:
            store.execute({
                "select": ["ghost_col"], "from": "files",
            })
        except QueryValidationError:
            pass
        assert list(store.files.rows) == orig

    def test_project_keeps_column_order(self, store: ResultStore):
        """INV-07: project column order matches parameter order."""
        r = store.files.project("source_name", "virtual_path")
        assert r.columns == ("source_name", "virtual_path")

    def test_select_preserves_row_order(self, store: ResultStore):
        """INV-08: select preserves original relative order."""
        r = store.files.select(lambda r: r.priority >= 100)
        orig_order = [(r.virtual_path, r.priority) for r in store.files.rows if r.priority >= 100]
        result_order = [(r.virtual_path, r.priority) for r in r.rows]
        assert result_order == orig_order

    def test_order_by_immutable(self, store: ResultStore):
        """INV-09: order_by returns new Relation, original unchanged."""
        from parallelines.engine.query_ast import OrderByClause, Query, ColumnRef, Source, Literal as Lit
        from parallelines.engine.query_executor import QueryExecutor
        orig = list(store.files.rows)
        q = Query([Lit("*")], Source(relation="files"),
                  order_by=OrderByClause(ColumnRef("priority"), "desc"))
        QueryExecutor.execute(q, store)
        assert list(store.files.rows) == orig

    def test_limit_immutable(self, store: ResultStore):
        """INV-10: limit returns new Relation, original unchanged."""
        orig = list(store.files.rows)
        store.execute({"select":["*"], "from":"files", "limit": 1})
        assert list(store.files.rows) == orig

    def test_select_by_immutable(self, store: ResultStore):
        """INV-11: select_by returns new Relation, original unchanged."""
        orig = list(store.files.rows)
        store.files.select_by("source_name", "base")
        assert list(store.files.rows) == orig

    def test_update_cell_semantics(self, store: ResultStore):
        """INV-12: update_cell modifies in place, select sees the change."""
        store.files.update_cell(lambda r: r.virtual_path == "a.txt", "source_name", "modified")
        # Original dataclass row was mutated
        assert store.files.rows[0].source_name == "modified"
