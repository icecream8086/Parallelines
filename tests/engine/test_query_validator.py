"""Validator tests (VAL-00 ~ VAL-15)."""
from __future__ import annotations

import pytest
from parallelines.engine import ResultStore
from parallelines.engine.query_ast import (
    BinaryPred,
    ColumnRef,
    ExistsPred,
    GroupByClause,
    InPred,
    JoinClause,
    LikePred,
    Literal,
    OrderByClause,
    Query,
    Source,
    StringPred,
)
from parallelines.engine.query_validator import QueryValidator
from parallelines.engine.schema import FileRow
from parallelines.engine.store import Relation


@pytest.fixture
def store() -> ResultStore:
    store = ResultStore()
    store.files = Relation[FileRow].from_rows(
        "files",
        [
            FileRow("a.txt", "base", "game", 100, "abc", 1024, True),
            FileRow(
                "b.txt",
                "addon",
                "addon",
                200,
                "def",
                512,
                True,
                False,
                False,
                False,
                False,
                True,
            ),
        ],
    )
    return store


class TestValidatorR0:
    def test_relation_source_valid(self, store: ResultStore):
        """VAL-00: R0 -- valid relation source."""
        q = Query([ColumnRef("virtual_path")], Source(relation="files"))
        errors = QueryValidator.validate(q, store)
        assert errors == []

    def test_graph_fn_source_valid(self, store: ResultStore):
        """VAL-00b: R0 -- valid graph_fn source."""
        q = Query(
            [ColumnRef("virtual_path")],
            Source(graph_fn="descendants_of", graph_fn_arg="maps/c1m1.bsp"),
        )
        errors = QueryValidator.validate(q, store)
        assert errors == []

    def test_subquery_source_valid(self, store: ResultStore):
        """VAL-00c: R0 -- valid subquery source (validator returns early for top-level subqueries)."""
        from parallelines.engine.query_ast import Query, ColumnRef
        q = Query(
            [ColumnRef("virtual_path")],
            Source(subquery=Query([ColumnRef("virtual_path")], Source(relation="files"))),
        )
        errors = QueryValidator.validate(q, store)
        # Top-level subquery cannot be validated; returns a descriptive message
        assert errors == ["Subquery sources cannot be validated at top level"]


class TestValidatorR1:
    def test_nonexistent_column(self, store: ResultStore):
        """VAL-01: R1 -- select nonexistent column."""
        q = Query([ColumnRef("ghost")], Source(relation="files"))
        errors = QueryValidator.validate(q, store)
        assert any("R1" in e and "ghost" in e for e in errors)

    def test_order_by_nonexistent(self, store: ResultStore):
        """VAL-02: R1 -- order_by nonexistent column."""
        q = Query(
            [ColumnRef("virtual_path")],
            Source(relation="files"),
            order_by=OrderByClause(ColumnRef("ghost_col"), "asc"),
        )
        errors = QueryValidator.validate(q, store)
        assert any("R1" in e for e in errors)

    def test_agg_column_valid(self, store: ResultStore):
        """VAL-03: R1 -- group_by col + agg output name valid."""
        q = Query(
            [ColumnRef("source_name"), ColumnRef("cnt")],
            Source(relation="files"),
            group_by=GroupByClause(
                columns=[ColumnRef("source_name")],
                aggregations={"cnt": "count"},
            ),
        )
        errors = QueryValidator.validate(q, store)
        assert errors == [] or all("R1" not in e for e in errors)

    def test_join_column_valid(self, store: ResultStore):
        """VAL-04: R1 -- join target columns accepted."""
        store.hash_conflicts = Relation(
            "hash_conflicts",
            (
                "virtual_path",
                "winner_source",
                "loser_source",
                "winner_hash",
                "loser_hash",
            ),
            [("a.txt", "x", "y", "a", "b")],
        )
        q = Query(
            [ColumnRef("virtual_path")],
            Source(relation="files"),
            joins=[
                JoinClause(
                    type="inner",
                    with_source=Source(relation="hash_conflicts"),
                    on=BinaryPred(
                        "eq", ColumnRef("virtual_path"), ColumnRef("virtual_path")
                    ),
                ),
            ],
        )
        errors = QueryValidator.validate(q, store)
        assert errors == [] or all("R1" not in e for e in errors)


class TestValidatorR2:
    def test_gt_on_string(self, store: ResultStore):
        """VAL-05: R2 -- gt on string column."""
        q = Query(
            [ColumnRef("virtual_path")],
            Source(relation="files"),
            where=BinaryPred("gt", ColumnRef("source_name"), Literal("a")),
        )
        errors = QueryValidator.validate(q, store)
        assert any("R2" in e for e in errors)

    def test_like_on_int(self, store: ResultStore):
        """VAL-06: R2 -- like on int column."""
        q = Query(
            [ColumnRef("virtual_path")],
            Source(relation="files"),
            where=LikePred(ColumnRef("priority"), "*"),
        )
        errors = QueryValidator.validate(q, store)
        assert any("R2" in e for e in errors)

    def test_in_type_mismatch(self, store: ResultStore):
        """VAL-07: R2 -- InPred non-primitive value."""
        q = Query(
            [ColumnRef("virtual_path")],
            Source(relation="files"),
            where=InPred(ColumnRef("virtual_path"), [Literal(b"bytes")]),
        )
        errors = QueryValidator.validate(q, store)
        assert any("R2" in e for e in errors)

    def test_stringpred_on_int(self, store: ResultStore):
        """VAL-08: R2 -- starts_with on int column."""
        q = Query(
            [ColumnRef("virtual_path")],
            Source(relation="files"),
            where=StringPred("starts_with", ColumnRef("priority"), "x"),
        )
        errors = QueryValidator.validate(q, store)
        assert any("R2" in e and "starts_with" in e for e in errors)

    def test_exists_pred_target_missing(self, store: ResultStore):
        """VAL-09: R2 -- ExistsPred target relation not found."""
        q = Query(
            [ColumnRef("virtual_path")],
            Source(relation="files"),
            where=ExistsPred(False, ColumnRef("virtual_path"), "ghost_rel"),
        )
        errors = QueryValidator.validate(q, store)
        assert any("R2" in e for e in errors)


class TestValidatorR3:
    def test_join_key_not_in_right(self, store: ResultStore):
        """VAL-10: R3 -- ON column not in join target."""
        store.hash_conflicts = Relation(
            "hash_conflicts",
            (
                "virtual_path",
                "winner_source",
                "loser_source",
                "winner_hash",
                "loser_hash",
            ),
            [("a.txt", "x", "y", "a", "b")],
        )
        q = Query(
            [ColumnRef("virtual_path")],
            Source(relation="files"),
            joins=[
                JoinClause(
                    type="inner",
                    with_source=Source(relation="hash_conflicts"),
                    on=BinaryPred(
                        "eq",
                        ColumnRef("ghost_col", relation="hash_conflicts"),
                        ColumnRef("virtual_path"),
                    ),
                ),
            ],
        )
        errors = QueryValidator.validate(q, store)
        assert any("R3" in e for e in errors)


class TestValidatorR4:
    def test_nongroup_column_in_select(self, store: ResultStore):
        """VAL-11: R4 -- select column not in group_by or agg."""
        q = Query(
            [ColumnRef("virtual_path")],
            Source(relation="files"),
            group_by=GroupByClause(
                columns=[ColumnRef("source_name")],
                aggregations={"cnt": "count"},
            ),
        )
        errors = QueryValidator.validate(q, store)
        assert any("R4" in e for e in errors)

    def test_agg_column_valid(self, store: ResultStore):
        """VAL-12: R4 -- agg output name in select is valid."""
        q = Query(
            [ColumnRef("source_name"), ColumnRef("cnt")],
            Source(relation="files"),
            group_by=GroupByClause(
                columns=[ColumnRef("source_name")],
                aggregations={"cnt": "count"},
            ),
        )
        errors = QueryValidator.validate(q, store)
        assert errors == [] or all("R4" not in e for e in errors)


class TestValidatorR5:
    def test_subquery_bad_relation(self, store: ResultStore):
        """VAL-13: R5 -- subquery in join references nonexistent relation."""
        store.hash_conflicts = Relation(
            "hash_conflicts",
            ("virtual_path", "winner_source"),
            [],
        )
        q = Query(
            [ColumnRef("virtual_path")],
            Source(relation="files"),
            joins=[
                JoinClause(
                    type="inner",
                    with_source=Source(
                        subquery=Query(
                            [ColumnRef("virtual_path")],
                            Source(relation="ghost_relation"),
                        ),
                    ),
                    on=BinaryPred(
                        "eq", ColumnRef("virtual_path"), ColumnRef("virtual_path")
                    ),
                ),
            ],
        )
        errors = QueryValidator.validate(q, store)
        assert any("R5" in e for e in errors)


class TestValidatorR6:
    def test_full_join_warning(self, store: ResultStore):
        """VAL-14: R6 -- full join warning."""
        store.hash_conflicts = Relation(
            "hash_conflicts",
            ("virtual_path", "winner_source"),
            [],
        )
        q = Query(
            [ColumnRef("virtual_path")],
            Source(relation="files"),
            joins=[
                JoinClause(
                    type="full",
                    with_source=Source(relation="hash_conflicts"),
                    on=BinaryPred(
                        "eq", ColumnRef("virtual_path"), ColumnRef("virtual_path")
                    ),
                ),
            ],
        )
        errors = QueryValidator.validate(q, store)
        assert any("R6" in e for e in errors)


class TestValidatorValid:
    def test_valid_query_passes(self, store: ResultStore):
        """VAL-15: Fully valid query produces 0 errors."""
        q = Query(
            [ColumnRef("virtual_path"), ColumnRef("source_name")],
            Source(relation="files"),
            where=BinaryPred("eq", ColumnRef("source_type"), Literal("game")),
        )
        errors = QueryValidator.validate(q, store)
        assert errors == []
