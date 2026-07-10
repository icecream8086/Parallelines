"""Test S7a — SQL-like declarative query language."""

from __future__ import annotations

import pytest

from parallelines.engine import ResultStore
from parallelines.engine.query_ast import (
    BinaryPred,
    ColumnRef,
    CompoundPred,
    GroupByClause,
    InPred,
    IsNullPred,
    JoinClause,
    LikePred,
    Literal as LiteralNode,
    OrderByClause,
    Query,
    Source,
)
from parallelines.engine.query_executor import QueryExecutor
from parallelines.engine.query_parser import QueryParseError, QueryParser
from parallelines.engine.query_validator import (
    QueryValidationError,
    QueryValidator,
)
from parallelines.engine.schema import FileRow, HashConflictRow
from parallelines.engine.store import Relation


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def store() -> ResultStore:
    """ResultStore populated with test data."""
    store = ResultStore()
    file_rows = [
        FileRow("a.txt", "base", "game", 100, "abc", 1024, True),
        FileRow("b.txt", "addon_x", "addon", 200, "def", 512, True, True, False),
        FileRow("c.txt", "addon_y", "addon", 300, "ghi", 256, True, False, True),
        FileRow("d.txt", "base", "game", 100, "jkl", 2048, False),
    ]
    store.files = Relation[FileRow].from_rows("files", file_rows)

    conflict_rows = [
        HashConflictRow("a.txt", "base", "addon_x", "abc", "xyz"),
        HashConflictRow("b.txt", "addon_x", "addon_y", "def", "ghi"),
    ]
    store.hash_conflicts = Relation[HashConflictRow].from_rows(
        "hash_conflicts", conflict_rows
    )
    return store


# ── AST Tests ──────────────────────────────────────────────────


class TestAstNodes:
    def test_column_ref_default(self):
        ref = ColumnRef("col")
        assert ref.column == "col"
        assert ref.relation is None

    def test_column_ref_with_relation(self):
        ref = ColumnRef("col", "rel")
        assert ref.column == "col"
        assert ref.relation == "rel"

    def test_literal_values(self):
        assert LiteralNode("hello").value == "hello"
        assert LiteralNode(42).value == 42
        assert LiteralNode(3.14).value == 3.14
        assert LiteralNode(True).value is True
        assert LiteralNode(None).value is None

    def test_binary_pred(self):
        pred = BinaryPred("eq", ColumnRef("x"), LiteralNode(1))
        assert pred.op == "eq"
        assert pred.left.column == "x"
        assert pred.right.value == 1

    def test_compound_pred(self):
        pred = CompoundPred("and", [
            BinaryPred("eq", ColumnRef("x"), LiteralNode(1)),
            BinaryPred("eq", ColumnRef("y"), LiteralNode(2)),
        ])
        assert pred.op == "and"
        assert len(pred.operands) == 2

    def test_source_relation(self):
        s = Source(relation="files")
        assert s.relation == "files"
        assert s.subquery is None

    def test_source_subquery(self):
        sub = Query([ColumnRef("x")], Source(relation="inner"))
        s = Source(subquery=sub)
        assert s.relation is None
        assert s.subquery is not None

    def test_source_both_raises(self):
        """Source with both relation and subquery raises ValueError."""
        sub = Query([ColumnRef("x")], Source(relation="inner"))
        with pytest.raises(ValueError, match="exactly one"):
            Source(relation="files", subquery=sub)

    def test_source_neither_raises(self):
        """Source with neither relation nor subquery raises ValueError."""
        with pytest.raises(ValueError, match="exactly one"):
            Source()

    def test_compound_pred_not_wrong_arity_raises(self):
        """'not' with != 1 operand raises ValueError."""
        with pytest.raises(ValueError, match="exactly 1"):
            CompoundPred("not", [])

    def test_compound_pred_and_wrong_arity_raises(self):
        """'and' with < 2 operands raises ValueError."""
        with pytest.raises(ValueError, match="at least 2"):
            CompoundPred("and", [
                BinaryPred("eq", ColumnRef("x"), LiteralNode(1)),
            ])

    def test_query_defaults(self):
        q = Query([ColumnRef("x")], Source(relation="t"))
        assert q.where is None
        assert q.join is None
        assert q.group_by is None
        assert q.order_by is None
        assert q.limit is None


# ── Parser Tests ──────────────────────────────────────────────


class TestParserBasics:
    def test_parse_simple_select_from(self):
        d = {
            "select": ["virtual_path", "source_name"],
            "from": "files",
        }
        q = QueryParser.parse(d)
        assert len(q.select) == 2
        assert isinstance(q.select[0], ColumnRef)
        assert q.select[0].column == "virtual_path"
        assert q.select[1].column == "source_name"
        assert q.source.relation == "files"

    def test_parse_select_star(self):
        d = {"select": ["*"], "from": "files"}
        q = QueryParser.parse(d)
        assert len(q.select) == 1
        assert isinstance(q.select[0], LiteralNode)
        assert q.select[0].value == "*"

    def test_parse_with_where_eq(self):
        d = {
            "select": ["*"],
            "from": "files",
            "where": {"eq": ["source_name", "base"]},
        }
        q = QueryParser.parse(d)
        assert q.where is not None
        assert isinstance(q.where, BinaryPred)
        assert q.where.op == "eq"
        assert q.where.left.column == "source_name"
        assert q.where.right.value == "base"

    def test_parse_with_where_neq(self):
        d = {
            "select": ["*"],
            "from": "files",
            "where": {"neq": ["is_dead", True]},
        }
        q = QueryParser.parse(d)
        assert isinstance(q.where, BinaryPred)
        assert q.where.op == "neq"
        assert q.where.left.column == "is_dead"
        assert q.where.right.value is True

    def test_parse_with_where_gt(self):
        d = {
            "select": ["*"],
            "from": "files",
            "where": {"gt": ["priority", 100]},
        }
        q = QueryParser.parse(d)
        assert isinstance(q.where, BinaryPred)
        assert q.where.op == "gt"
        assert q.where.left.column == "priority"
        assert q.where.right.value == 100

    def test_parse_with_where_gte_lt_lte(self):
        for op in ("gte", "lt", "lte"):
            d = {"select": ["*"], "from": "files", "where": {op: ["priority", 200]}}
            q = QueryParser.parse(d)
            assert isinstance(q.where, BinaryPred)
            assert q.where.op == op  # type: ignore[comparison-overlap]

    def test_parse_with_limit(self):
        d = {"select": ["*"], "from": "files", "limit": 10}
        q = QueryParser.parse(d)
        assert q.limit == 10


class TestParserCompoundPredicates:
    def test_parse_and(self):
        d = {
            "select": ["*"],
            "from": "files",
            "where": {
                "and": [
                    {"eq": ["source_type", "game"]},
                    {"eq": ["is_active", True]},
                ]
            },
        }
        q = QueryParser.parse(d)
        assert isinstance(q.where, CompoundPred)
        assert q.where.op == "and"
        assert len(q.where.operands) == 2

    def test_parse_or(self):
        d = {
            "select": ["*"],
            "from": "files",
            "where": {
                "or": [
                    {"eq": ["source_name", "base"]},
                    {"eq": ["source_name", "addon_x"]},
                ]
            },
        }
        q = QueryParser.parse(d)
        assert isinstance(q.where, CompoundPred)
        assert q.where.op == "or"
        assert len(q.where.operands) == 2

    def test_parse_not(self):
        d = {
            "select": ["*"],
            "from": "files",
            "where": {"not": {"eq": ["is_active", True]}},
        }
        q = QueryParser.parse(d)
        assert isinstance(q.where, CompoundPred)
        assert q.where.op == "not"
        assert len(q.where.operands) == 1

    def test_parse_nested_and_or(self):
        d = {
            "select": ["*"],
            "from": "files",
            "where": {
                "and": [
                    {"eq": ["source_type", "game"]},
                    {
                        "or": [
                            {"eq": ["is_active", True]},
                            {"eq": ["is_dead", True]},
                        ]
                    },
                ]
            },
        }
        q = QueryParser.parse(d)
        assert isinstance(q.where, CompoundPred)
        assert q.where.op == "and"
        assert len(q.where.operands) == 2
        second = q.where.operands[1]
        assert isinstance(second, CompoundPred)
        assert second.op == "or"


class TestParserSpecialPredicates:
    def test_parse_like(self):
        d = {
            "select": ["*"],
            "from": "files",
            "where": {"like": ["virtual_path", "*.txt"]},
        }
        q = QueryParser.parse(d)
        assert isinstance(q.where, LikePred)
        assert q.where.column.column == "virtual_path"
        assert q.where.pattern == "*.txt"

    def test_parse_in(self):
        d = {
            "select": ["*"],
            "from": "files",
            "where": {"in": ["source_name", ["base", "addon_x"]]},
        }
        q = QueryParser.parse(d)
        assert isinstance(q.where, InPred)
        assert q.where.column.column == "source_name"
        assert [v.value for v in q.where.values] == ["base", "addon_x"]

    def test_parse_is_null(self):
        d = {
            "select": ["*"],
            "from": "files",
            "where": {"is_null": ["is_dead"]},
        }
        q = QueryParser.parse(d)
        assert isinstance(q.where, IsNullPred)
        assert q.where.column.column == "is_dead"
        assert q.where.not_null is False

    def test_parse_is_not_null(self):
        d = {
            "select": ["*"],
            "from": "files",
            "where": {"is_not_null": ["source_name"]},
        }
        q = QueryParser.parse(d)
        assert isinstance(q.where, IsNullPred)
        assert q.where.column.column == "source_name"
        assert q.where.not_null is True


class TestParserAdvancedClauses:
    def test_parse_join(self):
        d = {
            "select": ["*"],
            "from": "files",
            "join": {
                "type": "inner",
                "with": "hash_conflicts",
                "on": {"eq": ["virtual_path", "virtual_path"]},
            },
        }
        q = QueryParser.parse(d)
        assert q.join is not None
        assert q.join.type == "inner"
        assert q.join.with_source.relation == "hash_conflicts"
        assert isinstance(q.join.on, BinaryPred)

    def test_parse_join_right(self):
        d = {
            "select": ["*"],
            "from": "files",
            "join": {
                "type": "right",
                "with": "hash_conflicts",
                "on": {"eq": ["virtual_path", "virtual_path"]},
            },
        }
        q = QueryParser.parse(d)
        assert q.join is not None
        assert q.join.type == "right"

    def test_parse_group_by(self):
        d = {
            "select": ["source_type", "count"],
            "from": "files",
            "group_by": {
                "by": ["source_type"],
                "agg": {"count": "count"},
            },
        }
        q = QueryParser.parse(d)
        assert q.group_by is not None
        assert len(q.group_by.columns) == 1
        assert q.group_by.columns[0].column == "source_type"
        assert q.group_by.aggregations == {"count": "count"}

    def test_parse_order_by_asc(self):
        d = {
            "select": ["*"],
            "from": "files",
            "order_by": {"by": "priority", "dir": "asc"},
        }
        q = QueryParser.parse(d)
        assert q.order_by is not None
        assert q.order_by.column.column == "priority"
        assert q.order_by.direction == "asc"

    def test_parse_order_by_desc_default(self):
        d = {
            "select": ["*"],
            "from": "files",
            "order_by": {"by": "priority"},
        }
        q = QueryParser.parse(d)
        assert q.order_by is not None
        assert q.order_by.column.column == "priority"
        assert q.order_by.direction == "asc"

    def test_parse_column_ref_with_relation(self):
        d = {
            "select": [["files", "virtual_path"]],
            "from": "files",
        }
        q = QueryParser.parse(d)
        assert len(q.select) == 1
        ref = q.select[0]
        assert isinstance(ref, ColumnRef)
        assert ref.column == "virtual_path"
        assert ref.relation == "files"

    def test_parse_subquery_source(self):
        d = {
            "select": ["*"],
            "from": {
                "query": {
                    "select": ["*"],
                    "from": "files",
                    "where": {"eq": ["source_type", "game"]},
                }
            },
        }
        q = QueryParser.parse(d)
        assert q.source.relation is None
        assert q.source.subquery is not None
        assert q.source.subquery.source.relation == "files"

    def test_parse_unknown_predicate_raises(self):
        d = {
            "select": ["*"],
            "from": "files",
            "where": {"unknown_op": ["x", 1]},
        }
        with pytest.raises(QueryParseError, match="Unknown predicate"):
            QueryParser.parse(d)

    def test_parse_missing_select_raises(self):
        d = {"from": "files"}
        with pytest.raises(QueryParseError):
            QueryParser.parse(d)


# ── Validator Tests ────────────────────────────────────────────


class TestValidatorR1ColumnExistence:
    def test_valid_column_passes(self, store: ResultStore):
        q = Query([ColumnRef("virtual_path")], Source(relation="files"))
        errors = QueryValidator.validate(q, store)
        assert errors == []

    def test_nonexistent_column_fails(self, store: ResultStore):
        q = Query([ColumnRef("nonexistent")], Source(relation="files"))
        errors = QueryValidator.validate(q, store)
        assert any("R1" in e and "nonexistent" in e for e in errors)

    def test_nonexistent_relation(self, store: ResultStore):
        q = Query([ColumnRef("x")], Source(relation="ghost"))
        errors = QueryValidator.validate(q, store)
        assert any("ghost" in e for e in errors)

    def test_predicate_column_checked(self, store: ResultStore):
        q = Query(
            [ColumnRef("virtual_path")],
            Source(relation="files"),
            where=BinaryPred("eq", ColumnRef("bad_column"), LiteralNode(1)),
        )
        errors = QueryValidator.validate(q, store)
        assert any("R1" in e and "bad_column" in e for e in errors)


class TestValidatorR2TypeCompatibility:
    def test_gt_on_numeric_column_passes(self, store: ResultStore):
        q = Query(
            [ColumnRef("virtual_path")],
            Source(relation="files"),
            where=BinaryPred("gt", ColumnRef("priority"), LiteralNode(100)),
        )
        errors = QueryValidator.validate(q, store)
        assert errors == [] or all("R2" not in e for e in errors)

    def test_gt_on_string_warns(self, store: ResultStore):
        q = Query(
            [ColumnRef("virtual_path")],
            Source(relation="files"),
            where=BinaryPred("gt", ColumnRef("source_name"), LiteralNode("a")),
        )
        errors = QueryValidator.validate(q, store)
        assert any("R2" in e for e in errors)

    def test_like_on_string_passes(self, store: ResultStore):
        q = Query(
            [ColumnRef("virtual_path")],
            Source(relation="files"),
            where=LikePred(ColumnRef("virtual_path"), "*.txt"),
        )
        errors = QueryValidator.validate(q, store)
        assert errors == [] or all("R2" not in e for e in errors)

    def test_like_on_numeric_warns(self, store: ResultStore):
        q = Query(
            [ColumnRef("virtual_path")],
            Source(relation="files"),
            where=LikePred(ColumnRef("priority"), "*.txt"),
        )
        errors = QueryValidator.validate(q, store)
        assert any("R2" in e for e in errors)


class TestValidatorR4Aggregation:
    def test_group_by_legal_select(self, store: ResultStore):
        q = Query(
            [ColumnRef("source_type"), ColumnRef("count")],
            Source(relation="files"),
            group_by=GroupByClause(
                columns=[ColumnRef("source_type")],
                aggregations={"count": "count"},
            ),
        )
        errors = QueryValidator.validate(q, store)
        assert errors == [] or all("R4" not in e for e in errors)

    def test_group_by_illegal_select(self, store: ResultStore):
        q = Query(
            [ColumnRef("virtual_path"), ColumnRef("count")],
            Source(relation="files"),
            group_by=GroupByClause(
                columns=[ColumnRef("source_type")],
                aggregations={"count": "count"},
            ),
        )
        errors = QueryValidator.validate(q, store)
        assert any("R4" in e for e in errors)


class TestValidatorR6JoinTypeDegradation:
    def test_full_join_warns(self, store: ResultStore):
        q = Query(
            [ColumnRef("virtual_path")],
            Source(relation="files"),
            join=JoinClause(
                type="full",
                with_source=Source(relation="hash_conflicts"),
                on=BinaryPred(
                    "eq", ColumnRef("virtual_path"), ColumnRef("virtual_path")
                ),
            ),
        )
        errors = QueryValidator.validate(q, store)
        assert any("R6" in e for e in errors)

    def test_inner_join_no_warn(self, store: ResultStore):
        q = Query(
            [ColumnRef("virtual_path")],
            Source(relation="files"),
            join=JoinClause(
                type="inner",
                with_source=Source(relation="hash_conflicts"),
                on=BinaryPred(
                    "eq", ColumnRef("virtual_path"), ColumnRef("virtual_path")
                ),
            ),
        )
        errors = QueryValidator.validate(q, store)
        assert all("R6" not in e for e in errors)


class TestValidatorIntegration:
    def test_validate_valid_query(self, store: ResultStore):
        q = Query(
            [ColumnRef("virtual_path")],
            Source(relation="files"),
            where=BinaryPred("eq", ColumnRef("source_type"), LiteralNode("game")),
        )
        errors = QueryValidator.validate(q, store)
        assert errors == []

    def test_validate_raises_on_invalid(self, store: ResultStore):
        q = Query(
            [ColumnRef("bad_col")],
            Source(relation="files"),
        )
        errors = QueryValidator.validate(q, store)
        assert len(errors) > 0


# ── Executor Tests ─────────────────────────────────────────────


class TestExecutorSimple:
    def test_execute_select_star(self, store: ResultStore):
        q = Query([LiteralNode("*")], Source(relation="files"))
        result = QueryExecutor.execute(q, store)
        assert len(result) == 4
        assert result.columns == store.files.columns

    def test_execute_select_column(self, store: ResultStore):
        q = Query([ColumnRef("virtual_path")], Source(relation="files"))
        result = QueryExecutor.execute(q, store)
        assert len(result) == 4
        assert result.columns == ("virtual_path",)
        assert all(isinstance(r, tuple) for r in result.rows)

    def test_execute_where_eq(self, store: ResultStore):
        q = Query(
            [LiteralNode("*")],
            Source(relation="files"),
            where=BinaryPred("eq", ColumnRef("source_type"), LiteralNode("game")),
        )
        result = QueryExecutor.execute(q, store)
        assert len(result) == 2
        for row in result.rows:
            assert getattr(row, "source_type") == "game"

    def test_execute_where_neq(self, store: ResultStore):
        q = Query(
            [LiteralNode("*")],
            Source(relation="files"),
            where=BinaryPred("neq", ColumnRef("is_dead"), LiteralNode(True)),
        )
        result = QueryExecutor.execute(q, store)
        # a.txt (False), c.txt (False), d.txt (False) → 3
        assert len(result) == 3

    def test_execute_where_gt(self, store: ResultStore):
        q = Query(
            [ColumnRef("virtual_path")],
            Source(relation="files"),
            where=BinaryPred("gt", ColumnRef("priority"), LiteralNode(100)),
        )
        result = QueryExecutor.execute(q, store)
        # b.txt (200), c.txt (300) → 2
        assert len(result) == 2

    def test_execute_where_gte(self, store: ResultStore):
        q = Query(
            [LiteralNode("*")],
            Source(relation="files"),
            where=BinaryPred("gte", ColumnRef("priority"), LiteralNode(100)),
        )
        result = QueryExecutor.execute(q, store)
        assert len(result) == 4  # all have priority >= 100

    def test_execute_where_lt(self, store: ResultStore):
        q = Query(
            [LiteralNode("*")],
            Source(relation="files"),
            where=BinaryPred("lt", ColumnRef("priority"), LiteralNode(300)),
        )
        result = QueryExecutor.execute(q, store)
        assert len(result) == 3  # 100, 100, 200

    def test_execute_where_lte(self, store: ResultStore):
        q = Query(
            [LiteralNode("*")],
            Source(relation="files"),
            where=BinaryPred("lte", ColumnRef("priority"), LiteralNode(200)),
        )
        result = QueryExecutor.execute(q, store)
        assert len(result) == 3  # 100, 100, 200

    def test_execute_limit(self, store: ResultStore):
        q = Query(
            [LiteralNode("*")],
            Source(relation="files"),
            limit=2,
        )
        result = QueryExecutor.execute(q, store)
        assert len(result) == 2


class TestExecutorCompoundPredicates:
    def test_execute_and(self, store: ResultStore):
        q = Query(
            [LiteralNode("*")],
            Source(relation="files"),
            where=CompoundPred(
                "and",
                [
                    BinaryPred("eq", ColumnRef("source_type"), LiteralNode("addon")),
                    BinaryPred("eq", ColumnRef("is_active"), LiteralNode(True)),
                ],
            ),
        )
        result = QueryExecutor.execute(q, store)
        # b.txt (addon, True), c.txt (addon, True) → 2
        assert len(result) == 2

    def test_execute_or(self, store: ResultStore):
        q = Query(
            [LiteralNode("*")],
            Source(relation="files"),
            where=CompoundPred(
                "or",
                [
                    BinaryPred("eq", ColumnRef("source_name"), LiteralNode("base")),
                    BinaryPred("eq", ColumnRef("source_name"), LiteralNode("addon_x")),
                ],
            ),
        )
        result = QueryExecutor.execute(q, store)
        # a.txt (base), b.txt (addon_x), d.txt (base) → 3
        assert len(result) == 3

    def test_execute_not(self, store: ResultStore):
        q = Query(
            [LiteralNode("*")],
            Source(relation="files"),
            where=CompoundPred(
                "not",
                [
                    BinaryPred("eq", ColumnRef("is_active"), LiteralNode(True)),
                ],
            ),
        )
        result = QueryExecutor.execute(q, store)
        # Only d.txt has is_active=False → 1
        assert len(result) == 1
        assert getattr(result.rows[0], "virtual_path") == "d.txt"


class TestExecutorSpecialPredicates:
    def test_execute_like(self, store: ResultStore):
        q = Query(
            [LiteralNode("*")],
            Source(relation="files"),
            where=LikePred(ColumnRef("virtual_path"), "*.txt"),
        )
        result = QueryExecutor.execute(q, store)
        assert len(result) == 4  # all are .txt

    def test_execute_like_pattern(self, store: ResultStore):
        q = Query(
            [LiteralNode("*")],
            Source(relation="files"),
            where=LikePred(ColumnRef("virtual_path"), "a*"),
        )
        result = QueryExecutor.execute(q, store)
        assert len(result) == 1
        assert getattr(result.rows[0], "virtual_path") == "a.txt"

    def test_execute_in(self, store: ResultStore):
        q = Query(
            [LiteralNode("*")],
            Source(relation="files"),
            where=InPred(
                ColumnRef("source_name"),
                [LiteralNode("base"), LiteralNode("addon_x")],
            ),
        )
        result = QueryExecutor.execute(q, store)
        # a.txt (base), b.txt (addon_x), d.txt (base) → 3
        assert len(result) == 3

    def test_execute_is_null(self, store: ResultStore):
        # None of our rows have None for any non-id field
        q = Query(
            [LiteralNode("*")],
            Source(relation="files"),
            where=IsNullPred(ColumnRef("file_hash"), not_null=False),
        )
        result = QueryExecutor.execute(q, store)
        assert len(result) == 0

    def test_execute_is_not_null(self, store: ResultStore):
        q = Query(
            [ColumnRef("virtual_path")],
            Source(relation="files"),
            where=IsNullPred(ColumnRef("source_name"), not_null=True),
        )
        result = QueryExecutor.execute(q, store)
        assert len(result) == 4  # all have source_name


class TestExecutorJoin:
    def test_execute_inner_join(self, store: ResultStore):
        q = Query(
            [LiteralNode("*")],
            Source(relation="files"),
            join=JoinClause(
                type="inner",
                with_source=Source(relation="hash_conflicts"),
                on=BinaryPred(
                    "eq", ColumnRef("virtual_path"), ColumnRef("virtual_path")
                ),
            ),
        )
        result = QueryExecutor.execute(q, store)
        # a.txt and b.txt have conflicts → 2 rows
        assert len(result) == 2
        assert "virtual_path" in result.columns

    def test_execute_join_no_matches(self, store: ResultStore):
        empty_conflicts = Relation[HashConflictRow](
            "hash_conflicts",
            (
                "virtual_path",
                "winner_source",
                "loser_source",
                "winner_hash",
                "loser_hash",
            ),
            [],
        )
        local_store = ResultStore()
        local_store.files = store.files
        local_store.hash_conflicts = empty_conflicts
        q = Query(
            [LiteralNode("*")],
            Source(relation="files"),
            join=JoinClause(
                type="inner",
                with_source=Source(relation="hash_conflicts"),
                on=BinaryPred(
                    "eq", ColumnRef("virtual_path"), ColumnRef("virtual_path")
                ),
            ),
        )
        result = QueryExecutor.execute(q, local_store)
        assert len(result) == 0

    def test_execute_left_join(self, store: ResultStore):
        """LEFT JOIN should preserve all left-side rows, filling NULL for unmatched."""
        conflicts_rel = Relation.from_rows(
            "hash_conflicts",
            [HashConflictRow("b.txt", "addon_x", "base", "def", "abc")],
        )
        store.hash_conflicts = conflicts_rel
        q = Query(
            [ColumnRef("virtual_path"), ColumnRef("source_name"), ColumnRef("winner_source")],
            Source(relation="files"),
            join=JoinClause(
                type="left",
                with_source=Source(relation="hash_conflicts"),
                on=BinaryPred("eq", ColumnRef("virtual_path"), ColumnRef("virtual_path")),
            ),
        )
        result = QueryExecutor.execute(q, store)
        # 4 files, 1 hash conflict → 4 rows (3 with None winner_source)
        assert len(result) == 4
        by_path = {r[0]: r[2] for r in result.rows}
        assert by_path["b.txt"] == "addon_x"
        assert by_path["a.txt"] is None
        assert by_path["c.txt"] is None
        assert by_path["d.txt"] is None

    def test_execute_full_join(self, store: ResultStore):
        """FULL JOIN via executor — all rows from both sides, deduped on match."""
        conflicts_rel = Relation.from_rows(
            "hash_conflicts",
            [
                HashConflictRow("a.txt", "base", "addon_x", "abc", "xyz"),
                HashConflictRow("b.txt", "addon_x", "addon_y", "def", "ghi"),
            ],
        )
        store.hash_conflicts = conflicts_rel
        q = Query(
            [ColumnRef("virtual_path"), ColumnRef("winner_source")],
            Source(relation="files"),
            join=JoinClause(
                type="full",
                with_source=Source(relation="hash_conflicts"),
                on=BinaryPred("eq", ColumnRef("virtual_path"), ColumnRef("virtual_path")),
            ),
        )
        result = QueryExecutor.execute(q, store)
        # 4 files + 2 hash conflicts, but a.txt and b.txt matched → 4 rows total
        assert len(result) == 4
        by_path = {r[0]: r[1] for r in result.rows}
        assert by_path["a.txt"] == "base"   # matched, winner_source
        assert by_path["b.txt"] == "addon_x"
        assert by_path["c.txt"] is None     # unmatched file
        assert by_path["d.txt"] is None     # unmatched file


class TestExecutorGroupBy:
    def test_execute_group_by_count(self, store: ResultStore):
        q = Query(
            [ColumnRef("source_type"), ColumnRef("count")],
            Source(relation="files"),
            group_by=GroupByClause(
                columns=[ColumnRef("source_type")],
                aggregations={"count": "count"},
            ),
        )
        result = QueryExecutor.execute(q, store)
        # 2 game, 2 addon
        rows = {r[0]: r[1] for r in result.rows}
        assert rows["game"] == 2
        assert rows["addon"] == 2

    def test_execute_group_by_sum(self, store: ResultStore):
        """Group by with sum aggregation on file_size."""
        q = Query(
            [ColumnRef("source_type"), ColumnRef("total_size")],
            Source(relation="files"),
            group_by=GroupByClause(
                columns=[ColumnRef("source_type")],
                aggregations={"total_size": ["sum", "file_size"]},
            ),
        )
        result = QueryExecutor.execute(q, store)
        rows = {r[0]: r[1] for r in result.rows}
        assert rows["game"] == 3072  # 1024 + 2048
        assert rows["addon"] == 768  # 512 + 256


class TestExecutorOrderBy:
    def test_execute_order_by_asc(self, store: ResultStore):
        q = Query(
            [ColumnRef("priority")],
            Source(relation="files"),
            order_by=OrderByClause(ColumnRef("priority"), "asc"),
        )
        result = QueryExecutor.execute(q, store)
        # Deduplicated: 100, 200, 300
        assert len(result) >= 3
        vals = [
            r[0] if isinstance(r, tuple) else getattr(r, "priority")
            for r in result.rows
        ]
        for i in range(len(vals) - 1):
            assert vals[i] <= vals[i + 1]

    def test_execute_order_by_desc(self, store: ResultStore):
        q = Query(
            [ColumnRef("priority")],
            Source(relation="files"),
            order_by=OrderByClause(ColumnRef("priority"), "desc"),
        )
        result = QueryExecutor.execute(q, store)
        vals = [
            r[0] if isinstance(r, tuple) else getattr(r, "priority")
            for r in result.rows
        ]
        for i in range(len(vals) - 1):
            assert vals[i] >= vals[i + 1]


class TestExecutorEdgeCases:
    def test_execute_empty_result(self, store: ResultStore):
        q = Query(
            [LiteralNode("*")],
            Source(relation="files"),
            where=BinaryPred(
                "eq", ColumnRef("virtual_path"), LiteralNode("nonexistent.txt")
            ),
        )
        result = QueryExecutor.execute(q, store)
        assert len(result) == 0

    def test_execute_unknown_relation_raises(self, store: ResultStore):
        q = Query([LiteralNode("*")], Source(relation="ghost"))
        with pytest.raises(ValueError, match="not a Relation"):
            QueryExecutor.execute(q, store)

    def test_execute_select_column_ordering(self, store: ResultStore):
        q = Query(
            [ColumnRef("source_name"), ColumnRef("virtual_path")],
            Source(relation="files"),
        )
        result = QueryExecutor.execute(q, store)
        assert result.columns == ("source_name", "virtual_path")


# ── Integration: store.execute() ───────────────────────────────


class TestStoreExecute:
    def test_store_execute_simple(self, store: ResultStore):
        result = store.execute(
            {
                "select": ["virtual_path", "source_name"],
                "from": "files",
                "where": {"eq": ["source_type", "game"]},
            }
        )
        assert len(result) == 2
        assert all(r[0].endswith(".txt") for r in result.rows)

    def test_store_execute_star(self, store: ResultStore):
        result = store.execute(
            {
                "select": ["*"],
                "from": "files",
            }
        )
        assert len(result) == 4

    def test_store_execute_compound_where(self, store: ResultStore):
        result = store.execute(
            {
                "select": ["*"],
                "from": "files",
                "where": {
                    "and": [
                        {"eq": ["source_type", "addon"]},
                        {"eq": ["is_active", True]},
                    ]
                },
            }
        )
        assert len(result) == 2

    def test_store_execute_invalid_query_raises(self, store: ResultStore):
        with pytest.raises(QueryValidationError):
            store.execute(
                {
                    "select": ["nonexistent_column"],
                    "from": "files",
                }
            )

    def test_store_execute_with_limit(self, store: ResultStore):
        result = store.execute(
            {
                "select": ["*"],
                "from": "files",
                "limit": 1,
            }
        )
        assert len(result) == 1

    def test_store_execute_like(self, store: ResultStore):
        result = store.execute(
            {
                "select": ["virtual_path"],
                "from": "files",
                "where": {"like": ["virtual_path", "a*"]},
            }
        )
        assert len(result) == 1

    def test_store_execute_in_predicate(self, store: ResultStore):
        result = store.execute(
            {
                "select": ["*"],
                "from": "files",
                "where": {"in": ["source_name", ["base", "addon_x"]]},
            }
        )
        assert len(result) == 3

    def test_store_execute_order_by(self, store: ResultStore):
        result = store.execute(
            {
                "select": ["priority"],
                "from": "files",
                "order_by": {"by": "priority", "dir": "desc"},
            }
        )
        rows = result.rows
        vals = [r[0] for r in rows]
        for i in range(len(vals) - 1):
            assert vals[i] >= vals[i + 1]
