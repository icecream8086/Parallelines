"""Test QueryOptimizer passes — AST structure + metamorphic semantic equivalence.

MR1 — For ANY query q on a store, optimize(q) preserves the result set.
MR2 — Predicate pushdown (sigma_{pR ^ pS}(R ⋈ S) -> sigma_{pR}(R) ⋈ sigma_{pS}(S))
      preserves result sets.
"""
from __future__ import annotations

import copy

import pytest

from parallelines.engine import Relation, ResultStore
from parallelines.engine.query_ast import (
    BinaryPred,
    ColumnRef,
    CompoundPred,
    JoinClause,
    Literal as Lit,
    Predicate,
    Query,
    Source,
    StringPred,
)
from parallelines.engine.query_executor import QueryExecutor
from parallelines.engine.query_optimizer import QueryOptimizer
from parallelines.engine.schema import AddonRow, ExternalFileRow, FileRow


# ── Helper factories ────────────────────────────────────────


def _eq(col: str, val) -> BinaryPred:
    return BinaryPred("eq", ColumnRef(col), Lit(val))


def _gt(col: str, val) -> BinaryPred:
    return BinaryPred("gt", ColumnRef(col), Lit(val))


def _lt(col: str, val) -> BinaryPred:
    return BinaryPred("lt", ColumnRef(col), Lit(val))


def _and(*preds: Predicate) -> CompoundPred:
    return CompoundPred("and", list(preds))


def _or(*preds: Predicate) -> CompoundPred:
    return CompoundPred("or", list(preds))


def _not(pred: Predicate) -> CompoundPred:
    return CompoundPred("not", [pred])


# ── Store & helpers ─────────────────────────────────────────


def _make_basic_store() -> ResultStore:
    """Standard store for optimizer metamorphic tests."""
    s = ResultStore()
    s.files = Relation[FileRow].from_rows("files", [
        FileRow("a.txt", "base", "game", 100, "abc", 1024, True, False, False),
        FileRow("b.txt", "addon_x", "addon", 200, "def", 512, True, False, False),
        FileRow("c.txt", "addon_y", "addon", 300, "ghi", 256, False, False, True),
    ])
    s.addons = Relation[AddonRow].from_rows("addons", [
        AddonRow("base", "Base Game", True, 100),
        AddonRow("addon_x", "Addon X", True, 200),
        AddonRow("addon_y", "Addon Y", False, 300),
    ])
    s.external_files = Relation[ExternalFileRow].from_rows("external_files", [
        ExternalFileRow("a.txt", "ref:ext", 2000, "xyz", 1024),
        ExternalFileRow("b.txt", "ref:ext", 2000, "uvw", 512),
    ])
    s.external_files.build_index("virtual_path")
    return s


@pytest.fixture
def store() -> ResultStore:
    return _make_basic_store()


def _row_set(rel: Relation) -> set[tuple]:
    """Convert Relation rows to a set of tuples for order-independent comparison."""
    if not rel.rows:
        return set()
    if isinstance(rel.rows[0], tuple):
        return set(rel.rows)
    return {tuple(getattr(r, c) for c in rel.columns) for r in rel.rows}


def _assert_equivalent(q: Query, store: ResultStore) -> None:
    """MR1 metamorphic relation: optimize(q) must produce the same result set as q.

    Compares row sets after projecting to the intersection of column names
    (sorted canonically) so that join reordering does not cause spurious failures.
    """
    unopt = QueryExecutor.execute(q, store)
    opt = QueryOptimizer.optimize(copy.deepcopy(q), store)
    opt_result = QueryExecutor.execute(opt, store)
    # Project to common columns in canonical (sorted) order so that join
    # reordering (which changes column order) does not cause false negatives.
    cols = tuple(sorted(set(unopt.columns) & set(opt_result.columns)))
    if not cols:
        # Both results are empty relations — nothing to compare
        assert _row_set(unopt) == _row_set(opt_result)
    else:
        assert _row_set(unopt.project(*cols)) == _row_set(opt_result.project(*cols))


# ── Test classes ────────────────────────────────────────────


class TestSimplifyPredicates:
    """AST-structure unit tests + MR1 semantic equivalence for each simplification."""

    def test_flatten_and(self):
        """AND(a, AND(b, c)) -> AND(a, b, c)."""
        q = Query(select=[Lit("*")], source=Source(relation="files"),
                  where=_and(_eq("a", 1), _and(_eq("b", 2), _eq("c", 3))))
        result = QueryOptimizer.optimize(q, store=None)
        w = result.where
        assert isinstance(w, CompoundPred) and w.op == "and"
        assert len(w.operands) == 3

    def test_double_negation(self):
        """NOT(NOT(p)) -> p."""
        q = Query(select=[Lit("*")], source=Source(relation="files"),
                  where=_not(_not(_eq("a", 1))))
        result = QueryOptimizer.optimize(q, store=None)
        w = result.where
        assert isinstance(w, BinaryPred) and w.op == "eq" and w.left.column == "a"

    def test_demorgan_and(self):
        """NOT(AND(x, y)) -> OR(NOT(x), NOT(y))."""
        q = Query(select=[Lit("*")], source=Source(relation="files"),
                  where=_not(_and(_eq("a", 1), _gt("b", 2))))
        result = QueryOptimizer.optimize(q, store=None)
        w = result.where
        assert isinstance(w, CompoundPred) and w.op == "or"

    def test_idempotent(self):
        """optimize(optimize(q)) == optimize(q) — AST-structure idempotence."""
        q = Query(select=[Lit("*")], source=Source(relation="files"),
                  where=_not(_not(_and(_eq("a", 1), _and(_eq("b", 2), _eq("c", 3))))))
        once = QueryOptimizer.optimize(q, store=None)
        twice = QueryOptimizer.optimize(once, store=None)
        assert type(once.where) == type(twice.where)

    # ── MR1: semantic equivalence for each simplification type ──

    def test_flatten_and_mr1(self, store: ResultStore):
        """MR1: AND flattening preserves result set."""
        q = Query(
            select=[Lit("*")], source=Source(relation="files"),
            where=_and(_eq("source_type", "game"),
                       _and(_eq("is_active", True), _gt("priority", 50))),
        )
        _assert_equivalent(q, store)

    def test_double_negation_mr1(self, store: ResultStore):
        """MR1: double negation elimination preserves result set."""
        q = Query(
            select=[Lit("*")], source=Source(relation="files"),
            where=_not(_not(_eq("source_name", "base"))),
        )
        _assert_equivalent(q, store)

    def test_demorgan_and_mr1(self, store: ResultStore):
        """MR1: De Morgan transformation preserves result set."""
        q = Query(
            select=[Lit("*")], source=Source(relation="files"),
            where=_not(_and(_eq("source_type", "game"), _eq("is_active", True))),
        )
        _assert_equivalent(q, store)

    def test_idempotent_mr1(self, store: ResultStore):
        """MR1: optimize(optimize(q)) == optimize(q) in result-set terms."""
        q = Query(
            select=[Lit("*")], source=Source(relation="files"),
            where=_not(_not(
                _and(_eq("source_type", "game"),
                     _and(_eq("is_active", True), _eq("priority", 100)))
            )),
        )
        once = QueryOptimizer.optimize(copy.deepcopy(q), store)
        twice = QueryOptimizer.optimize(copy.deepcopy(once), store)
        r1 = QueryExecutor.execute(once, store)
        r2 = QueryExecutor.execute(twice, store)
        assert _row_set(r1) == _row_set(r2)


class TestUnnestSubqueries:
    """AST-structure tests + MR1 semantic equivalence for subquery unnesting."""

    def test_unnest_simple(self):
        """SELECT * FROM (SELECT * FROM R WHERE p1) WHERE p2 -> SELECT * FROM R WHERE p1 AND p2."""
        inner_source = Source(relation="files")
        inner_query = Query(select=[Lit("*")], source=inner_source, where=_eq("is_active", True))
        outer_source = Source(subquery=inner_query)
        outer_query = Query(
            select=[Lit("*")], source=outer_source,
            where=_eq("source_name", "base"),
        )
        result = QueryOptimizer.optimize(outer_query, store=None)
        assert result.source.relation == "files"
        assert result.where is not None
        # WHERE should be AND(is_active=True, source_name="base")
        w = result.where
        assert isinstance(w, CompoundPred) and w.op == "and"
        assert len(w.operands) == 2

    def test_non_star_not_unnested(self):
        """Non ["*"] projection is not unnested."""
        inner_query = Query(select=[ColumnRef("a")], source=Source(relation="files"),
                            where=_eq("is_active", True))
        outer_source = Source(subquery=inner_query)
        outer_query = Query(select=[Lit("*")], source=outer_source)
        result = QueryOptimizer.optimize(outer_query, store=None)
        assert result.source.subquery is not None

    # ── MR1 ──

    def test_unnest_simple_mr1(self, store: ResultStore):
        """MR1: subquery unnesting preserves result set."""
        inner = Query(select=[Lit("*")], source=Source(relation="files"),
                      where=_eq("is_active", True))
        outer = Query(select=[Lit("*")], source=Source(subquery=inner),
                      where=_eq("source_name", "base"))
        _assert_equivalent(outer, store)


class TestJoinOrder:
    """MR1 metamorphic test for join reordering."""

    def test_smallest_first(self, store: ResultStore):
        """MR1: 3-table inner JOIN — optimizer reorder preserves result set.

        files (3 rows) JOIN addons (3 rows) JOIN external_files (2 rows).
        Greedy reorder should place external_files first (cardinality 2).
        Semantics must be unchanged.
        """
        q = Query(
            select=[Lit("*")],
            source=Source(relation="files"),
            joins=[
                JoinClause(
                    "inner", Source(relation="addons"),
                    on=BinaryPred("eq", ColumnRef("source_name"), ColumnRef("addon_id")),
                ),
                JoinClause(
                    "inner", Source(relation="external_files"),
                    on=BinaryPred("eq", ColumnRef("virtual_path"), ColumnRef("virtual_path")),
                ),
            ],
        )
        _assert_equivalent(q, store)


class TestOptimizeIntegration:
    """Broader integration tests + MR1 coverage for remaining query shapes."""

    def test_optimize_preserves_select(self):
        """Optimized select list is unchanged."""
        q = Query(select=[ColumnRef("virtual_path"), ColumnRef("source_name")],
                  source=Source(relation="files"),
                  where=_not(_not(_eq("is_active", True))))
        result = QueryOptimizer.optimize(q, store=None)
        assert len(result.select) == 2
        assert result.select[0].column == "virtual_path"
        assert result.select[1].column == "source_name"

    def test_no_where_unchanged(self):
        """No WHERE -> optimizer does not change the query."""
        q = Query(select=[Lit("*")], source=Source(relation="files"))
        result = QueryOptimizer.optimize(q, store=None)
        assert result.where is None
        assert result.source.relation == "files"

    # ── MR1: broad coverage across all query shapes ──────────

    def test_mr1_simple_where(self, store: ResultStore):
        """MR1: simple WHERE query preserves result set."""
        q = Query(select=[Lit("*")], source=Source(relation="files"),
                  where=_eq("source_name", "base"))
        _assert_equivalent(q, store)

    def test_mr1_single_join_with_where(self, store: ResultStore):
        """MR1: single JOIN + WHERE preserves result set (pushdown fires)."""
        q = Query(
            select=[Lit("*")],
            source=Source(relation="files"),
            joins=[JoinClause(
                "inner", Source(relation="addons"),
                on=BinaryPred("eq", ColumnRef("source_name"), ColumnRef("addon_id")),
            )],
            where=_eq("is_active", True),
        )
        _assert_equivalent(q, store)


class TestPredicatePushdown:
    """MR2: Predicate pushdown preserves result sets."""

    def test_mr2_pushdown_single_join(self, store: ResultStore):
        """MR2: sigma_{pR ^ pS}(R ⋈ S) == sigma_{pR}(R) ⋈ sigma_{pS}(S).

        WHERE predicates on both sides of the join are pushed to the
        appropriate table; result set must be unchanged.
        """
        q = Query(
            select=[Lit("*")],
            source=Source(relation="files"),
            joins=[JoinClause(
                "inner", Source(relation="addons"),
                on=BinaryPred("eq", ColumnRef("source_name"), ColumnRef("addon_id")),
            )],
            where=_and(_eq("source_type", "game"), _eq("enabled", True)),
        )
        # Semantic: result sets must match
        _assert_equivalent(q, store)
        # Structural: verify that pushdown wrapped at least one source in a subquery
        opt = QueryOptimizer.optimize(copy.deepcopy(q), store)
        has_pushdown = (
            opt.source.subquery is not None
            or any(j.with_source.subquery is not None for j in opt.joins)
        )
        assert has_pushdown, (
            "Expected predicate pushdown to wrap at least one source in a subquery"
        )

    def test_mr2_pushdown_multi_join(self, store: ResultStore):
        """MR2: predicate pushdown on a 3-table join preserves result set."""
        q = Query(
            select=[Lit("*")],
            source=Source(relation="files"),
            joins=[
                JoinClause(
                    "inner", Source(relation="addons"),
                    on=BinaryPred("eq", ColumnRef("source_name"), ColumnRef("addon_id")),
                ),
                JoinClause(
                    "inner", Source(relation="external_files"),
                    on=BinaryPred("eq", ColumnRef("virtual_path"), ColumnRef("virtual_path")),
                ),
            ],
            where=_and(
                _eq("source_type", "game"),
                _and(_eq("enabled", True), _eq("ext_source_name", "ref:ext")),
            ),
        )
        _assert_equivalent(q, store)
