"""AST node construction tests (AST-01 ~ AST-15)."""
from __future__ import annotations

import pytest
from parallelines.engine.query_ast import (
    BinaryPred,
    ColumnRef,
    CompoundPred,
    GroupByClause,
    InPred,
    Literal,
    OrderByClause,
    Query,
    Source,
)


class TestColumnRef:
    def test_single_column(self):
        """AST-01: ColumnRef with only column name."""
        ref = ColumnRef(column="foo")
        assert ref.relation is None
        assert ref.column == "foo"

    def test_qualified_column(self):
        """AST-02: ColumnRef with relation prefix."""
        ref = ColumnRef(column="bar", relation="foo")
        assert ref.relation == "foo"
        assert ref.column == "bar"


class TestLiteral:
    def test_all_types(self):
        """AST-03: Literal stores str/int/float/bool/None."""
        assert Literal("hello").value == "hello"
        assert Literal(42).value == 42
        assert Literal(3.14).value == 3.14
        assert Literal(True).value is True
        assert Literal(None).value is None


class TestBinaryPred:
    def test_eq(self):
        """AST-04: BinaryPred with eq op."""
        pred = BinaryPred("eq", ColumnRef("col"), Literal("val"))
        assert pred.op == "eq"
        assert pred.left.column == "col"
        assert pred.right.value == "val"


class TestCompoundPred:
    def test_and_valid(self):
        """AST-05: CompoundPred and with >=2 operands."""
        pred = CompoundPred("and", [
            BinaryPred("eq", ColumnRef("a"), Literal(1)),
            BinaryPred("eq", ColumnRef("b"), Literal(2)),
        ])
        assert pred.op == "and"
        assert len(pred.operands) == 2

    def test_not_wrong_arity(self):
        """AST-06: 'not' with >1 operand raises."""
        with pytest.raises(ValueError, match="exactly 1"):
            CompoundPred("not", [
                BinaryPred("eq", ColumnRef("a"), Literal(1)),
                BinaryPred("eq", ColumnRef("b"), Literal(2)),
            ])

    def test_and_wrong_arity(self):
        """AST-07: 'and' with <2 operands raises."""
        with pytest.raises(ValueError, match="at least 2"):
            CompoundPred("and", [BinaryPred("eq", ColumnRef("a"), Literal(1))])


class TestSource:
    def test_valid_relation(self):
        """AST-08: Source with only relation."""
        s = Source(relation="files")
        assert s.relation == "files"
        assert s.subquery is None
        assert s.graph_fn is None

    def test_conflict_relation_subquery(self):
        """AST-09: Source with relation+subquery raises."""
        q = Query([ColumnRef("x")], Source(relation="inner"))
        with pytest.raises(ValueError, match="exactly one"):
            Source(relation="files", subquery=q)

    def test_conflict_all_three(self):
        """AST-10: Source with all three raises."""
        q = Query([ColumnRef("x")], Source(relation="inner"))
        with pytest.raises(ValueError, match="exactly one"):
            Source(relation="files", subquery=q, graph_fn="descendants_of")

    def test_no_source(self):
        """AST-11: Source with nothing raises."""
        with pytest.raises(ValueError, match="exactly one"):
            Source()

    def test_valid_graph_fn(self):
        """AST-12: Source with graph_fn."""
        s = Source(graph_fn="descendants_of", graph_fn_arg="maps/c1m1.bsp")
        assert s.graph_fn == "descendants_of"
        assert s.graph_fn_arg == "maps/c1m1.bsp"
        assert s.relation is None
        assert s.subquery is None


class TestQuery:
    def test_all_fields(self):
        """AST-13: Query with all optional fields."""
        q = Query(
            select=[ColumnRef("a"), ColumnRef("b")],
            source=Source(relation="files"),
            where=BinaryPred("gt", ColumnRef("pri"), Literal(100)),
            group_by=GroupByClause(
                columns=[ColumnRef("source_name")],
                aggregations={"cnt": "count"},
            ),
            having=BinaryPred("gt", ColumnRef("cnt"), Literal(1)),
            order_by=OrderByClause(ColumnRef("cnt"), "desc"),
            limit=10,
        )
        assert q.having is not None
        assert q.order_by is not None
        assert q.limit == 10

    def test_minimal(self):
        """AST-14: Query with only select and source."""
        q = Query([ColumnRef("x")], Source(relation="t"))
        assert q.where is None
        assert q.join is None
        assert q.group_by is None
        assert q.having is None
        assert q.order_by is None
        assert q.limit is None


class TestInPred:
    def test_negated(self):
        """AST-15: InPred with negated=True."""
        pred = InPred(ColumnRef("col"), [Literal(1), Literal(2)], negated=True)
        assert pred.negated is True
        assert [lit.value for lit in pred.values] == [1, 2]
