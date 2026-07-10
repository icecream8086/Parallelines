"""Query optimizer — predicate pushdown, simplification, join ordering.

This module provides a pure-function AST-to-AST optimizer with four passes,
applied in the following order:

1. _simplify_predicates  — algebraic rewrite of predicate trees
2. _unnest_subqueries    — flatten ``SELECT * FROM R WHERE p`` wrappers
3. _pushdown_predicates  — push single-table filters closer to data sources
4. _optimize_join_order  — greedy reorder of inner joins (when store stats available)

Unnesting runs **before** pushdown so that the query structure is flattened first;
subsequent passes then push predicates into whatever subqueries remain (which are
assumed to be intentional or introduced by an earlier pass).
"""

from __future__ import annotations

import copy

from parallelines.engine.query_ast import (
    BinaryPred,
    ColumnRef,
    CompoundPred,
    ExistsPred,
    GraphPred,
    InPred,
    IsNullPred,
    LikePred,
    Literal,
    Predicate,
    Query,
    Source,
    StringPred,
    JoinClause,
)
from parallelines.engine.store import ResultStore


class QueryOptimizer:
    """查询优化器 — 在 AST 层面做 Query → Query 变换。纯函数。"""

    @staticmethod
    def optimize(query: Query, store: ResultStore | None = None) -> Query:
        """Run all optimization passes. Returns a new (or mutated) Query AST.

        Pass order: simplify → unnest → pushdown iterated to fixpoint,
        then join order (single pass, deterministic).
        """
        # Iterate simplify → unnest → pushdown to fixpoint (max 3 iterations)
        for _ in range(3):
            prev = copy.deepcopy(query)
            query = QueryOptimizer._simplify_predicates(query)
            query = QueryOptimizer._unnest_subqueries(query)
            if store is not None:
                query = QueryOptimizer._pushdown_predicates(query, store)
            if query == prev:
                break
        if store is not None:
            query = QueryOptimizer._optimize_join_order(query, store)
        return query

    # ── Utilities ────────────────────────────────────────────────────────────────

    @staticmethod
    def _deep_copy_query(query: Query) -> Query:
        """Return a fully independent copy of a Query AST."""
        return copy.deepcopy(query)

    @staticmethod
    def _preds_equal(a: Predicate, b: Predicate) -> bool:
        """Structural comparison of two predicates using dataclass equality."""
        return type(a) is type(b) and a == b

    # ── Predicate Simplification ─────────────────────────────────────────────────

    @staticmethod
    def _simplify_predicates(query: Query) -> Query:
        """Simplify all predicates (where, having, join.on) in the query."""
        query = copy.deepcopy(query)
        if query.where is not None:
            query.where = QueryOptimizer._simp(query.where)
        if query.having is not None:
            query.having = QueryOptimizer._simp(query.having)
        for join in query.joins:
            join.on = QueryOptimizer._simp(join.on)

        # Recurse into subqueries
        if query.source.subquery is not None:
            query.source.subquery = QueryOptimizer._simplify_predicates(
                query.source.subquery
            )
        for join in query.joins:
            if join.with_source.subquery is not None:
                join.with_source.subquery = QueryOptimizer._simplify_predicates(
                    join.with_source.subquery
                )
        return query

    @staticmethod
    def _simp(pred: Predicate) -> Predicate:
        """Recursive predicate simplification, bottom-up.

        Applies:

        * AND / OR flattening       — AND(a, AND(b, c)) → AND(a, b, c)
        * Single-operand reduction  — AND([p]) → p
        * Idempotent dedup          — AND(p, p) → p
        * Double negation           — NOT(NOT(p)) → p
        * De Morgan's laws          — NOT(AND(x,y)) → OR(NOT(x), NOT(y))
                                     — NOT(OR(x,y))  → AND(NOT(x), NOT(y))
        """
        if not isinstance(pred, CompoundPred):
            return pred

        # Bottom-up: simplify operands first
        simplified = [QueryOptimizer._simp(op) for op in pred.operands]

        # ── NOT simplification ──────────────────────────────────────────────
        if pred.op == "not":
            inner = simplified[0]

            # Double negation: NOT(NOT(p)) → p
            if isinstance(inner, CompoundPred) and inner.op == "not":
                return inner.operands[0]

            # De Morgan's (only for binary AND/OR)
            if isinstance(inner, CompoundPred) and len(inner.operands) == 2:
                if inner.op == "and":
                    return QueryOptimizer._simp(
                        CompoundPred(
                            "or",
                            [
                                CompoundPred("not", [inner.operands[0]]),
                                CompoundPred("not", [inner.operands[1]]),
                            ],
                        )
                    )
                if inner.op == "or":
                    return QueryOptimizer._simp(
                        CompoundPred(
                            "and",
                            [
                                CompoundPred("not", [inner.operands[0]]),
                                CompoundPred("not", [inner.operands[1]]),
                            ],
                        )
                    )

            return CompoundPred("not", simplified)

        # ── AND / OR simplification ─────────────────────────────────────────
        if pred.op in ("and", "or"):
            # Flatten: AND(a, AND(b, c)) → AND(a, b, c)
            flattened: list[Predicate] = []
            for op in simplified:
                if isinstance(op, CompoundPred) and op.op == pred.op:
                    flattened.extend(op.operands)
                else:
                    flattened.append(op)

            # Dedup by structural equality
            deduped: list[Predicate] = []
            for op in flattened:
                if not any(
                    QueryOptimizer._preds_equal(op, existing) for existing in deduped
                ):
                    deduped.append(op)

            # Single-operand reduction
            if len(deduped) == 1:
                return deduped[0]

            return CompoundPred(pred.op, deduped)

        # Fallback (should not be reachable for valid CompoundPred)
        return CompoundPred(pred.op, simplified)

    # ── Predicate Pushdown ────────────────────────────────────────────────────────

    @staticmethod
    def _pushdown_predicates(query: Query, store: ResultStore) -> Query:
        """Push single-table predicates from WHERE closer to their data source.

        The core optimisation is ``sigma_p(R JOIN S) → sigma_p1(R) JOIN sigma_p2(S)``.
        Only activates when there is at least one join; otherwise there is nothing
        to push down to.
        """
        query = copy.deepcopy(query)

        if not query.joins:
            return query

        atoms = QueryOptimizer._decompose_conjunction(query.where)
        if not atoms:
            return query

        base_name = QueryOptimizer._resolve_source_name(query.source, store)
        if base_name is None:
            return query

        # Build a name → index mapping for joins
        join_names: dict[str, int] = {}
        for i, join in enumerate(query.joins):
            rname = QueryOptimizer._resolve_source_name(join.with_source, store)
            if rname is not None:
                join_names[rname] = i

        # Classify each atomic predicate by resolving its relation
        left_preds: list[Predicate] = []
        right_preds: dict[int, list[Predicate]] = {}
        mixed_preds: list[Predicate] = []

        for atom in atoms:
            target = QueryOptimizer._resolve_predicate_relation(
                atom, base_name, join_names, store
            )
            if target == base_name:
                left_preds.append(atom)
            elif target in join_names:
                idx = join_names[target]
                right_preds.setdefault(idx, []).append(atom)
            else:
                mixed_preds.append(atom)

        # Push left predicates into base source
        if left_preds:
            query.source = QueryOptimizer._wrap_source_with_filter(
                query.source, QueryOptimizer._make_conjunction(left_preds)
            )

        # Push right predicates into join sources
        for i, preds in right_preds.items():
            if preds:
                join = query.joins[i]
                join.with_source = QueryOptimizer._wrap_source_with_filter(
                    join.with_source, QueryOptimizer._make_conjunction(preds)
                )

        # Rebuild outer WHERE with remaining (mixed) predicates
        if mixed_preds:
            query.where = QueryOptimizer._make_conjunction(mixed_preds)
        else:
            query.where = None

        return query

    @staticmethod
    def _resolve_source_name(
        source: Source, store: ResultStore | None = None
    ) -> str | None:
        """Resolve a Source to the underlying relation name (if possible).

        * Named relation    → the relation name
        * ``SELECT *`` subquery → recurse into inner source
        * ``graph_fn``      → ``"files"``
        * Otherwise         → ``None`` (unknown)
        """
        if source.relation is not None:
            return source.relation
        if source.subquery is not None:
            inner = source.subquery
            if (
                len(inner.select) == 1
                and isinstance(inner.select[0], Literal)
                and inner.select[0].value == "*"
            ):
                return QueryOptimizer._resolve_source_name(inner.source, store)
            return None
        if source.graph_fn is not None:
            return "files"
        return None

    @staticmethod
    def _get_relation_columns(name: str, store: ResultStore) -> set[str]:
        """Return the column names of a named relation from the store.

        Returns an empty set if the relation is not present or has no columns.
        """
        rel = getattr(store, name, None)
        if rel is not None and hasattr(rel, "columns"):
            return set(rel.columns)
        return set()

    @staticmethod
    def _collect_column_refs_from_pred(pred: Predicate) -> list[ColumnRef]:
        """Yield every ``ColumnRef`` appearing in a predicate tree."""
        if isinstance(pred, BinaryPred):
            refs: list[ColumnRef] = [pred.left]
            if isinstance(pred.right, ColumnRef):
                refs.append(pred.right)
            return refs
        if isinstance(pred, (LikePred, InPred, IsNullPred, GraphPred, StringPred)):
            return [pred.column]
        if isinstance(pred, ExistsPred):
            return [pred.column]
        if isinstance(pred, CompoundPred):
            refs = []
            for op in pred.operands:
                refs.extend(QueryOptimizer._collect_column_refs_from_pred(op))
            return refs
        return []

    @staticmethod
    def _belongs_to(col_ref: ColumnRef, relation_name: str, store: ResultStore) -> bool:
        """Check whether *col_ref* refers to a column of *relation_name*.

        When ``ColumnRef.relation`` is set it is checked first; otherwise a
        best-effort column-name membership test is used.
        """
        if col_ref.relation is not None:
            # Exact match on qualified reference
            if col_ref.relation == relation_name:
                return True
            # relation is set to an alias — fall through to column-name check
        columns = QueryOptimizer._get_relation_columns(relation_name, store)
        return col_ref.column in columns

    @staticmethod
    def _resolve_predicate_relation(
        pred: Predicate,
        base_name: str | None,
        join_names: dict[str, int],
        store: ResultStore,
    ) -> str | None:
        """Determine which single relation an atomic predicate belongs to.

        For each ``ColumnRef`` in the predicate, we compute the set of
        candidate relations (by qualified name match or by column-name
        membership).  The intersection across all refs yields the target
        relation.  If the intersection contains **exactly one** relation the
        predicate is pushed to that relation; otherwise ``None`` is returned
        (mixed or unresolvable).

        This avoids the ambiguity of column names (e.g. ``virtual_path``)
        that appear in multiple relations.
        """
        refs = QueryOptimizer._collect_column_refs_from_pred(pred)
        if not refs:
            return None

        # Pre-compute column sets for all involved relations
        all_columns: dict[str, set[str]] = {}
        if base_name is not None:
            all_columns[base_name] = QueryOptimizer._get_relation_columns(
                base_name, store
            )
        for rname in join_names:
            if rname not in all_columns:
                all_columns[rname] = QueryOptimizer._get_relation_columns(rname, store)

        # Intersect candidate relations across all ColumnRefs
        common: set[str] | None = None

        for ref in refs:
            candidates: set[str] = set()
            if ref.relation is not None:
                # Qualified reference — exact match only
                if ref.relation in all_columns:
                    candidates.add(ref.relation)
            else:
                # Unqualified reference — match by column-name membership
                for rname, cols in all_columns.items():
                    if ref.column in cols:
                        candidates.add(rname)

            if not candidates:
                return None  # unresolvable

            if common is None:
                common = candidates
            else:
                common &= candidates
                if not common:
                    return None  # no single relation

        if common is None or len(common) != 1:
            return None
        return next(iter(common))

    @staticmethod
    def _decompose_conjunction(pred: Predicate | None) -> list[Predicate]:
        """Break a ``CompoundPred('and', ...)`` into flat list of atoms.

        Non-AND predicates are returned as a single-element list.
        ``None`` produces an empty list.
        """
        if pred is None:
            return []
        if isinstance(pred, CompoundPred) and pred.op == "and":
            result: list[Predicate] = []
            for op in pred.operands:
                result.extend(QueryOptimizer._decompose_conjunction(op))
            return result
        return [pred]

    @staticmethod
    def _make_conjunction(preds: list[Predicate]) -> Predicate:
        """Build a ``CompoundPred('and', ...)`` from a list.

        Returns the single element directly when *preds* has length 1.
        """
        if not preds:
            raise ValueError("Cannot make conjunction from an empty list")
        if len(preds) == 1:
            return preds[0]
        return CompoundPred("and", list(preds))

    @staticmethod
    def _wrap_source_with_filter(source: Source, predicate: Predicate) -> Source:
        """Wrap a Source in a ``SELECT *`` filter subquery.

        When *source* is already a subquery the predicate is merged into the
        inner ``WHERE`` instead of creating yet another nesting layer.
        """
        if source.subquery is not None:
            inner = source.subquery
            if inner.where is not None:
                inner.where = CompoundPred("and", [inner.where, predicate])
            else:
                inner.where = predicate
            return source
        # Wrap in a new subquery
        return Source(
            subquery=Query(
                select=[Literal("*")],
                source=copy.deepcopy(source),
                where=predicate,
            )
        )

    # ── Subquery Unnesting ───────────────────────────────────────────────────────

    @staticmethod
    def _unnest_subqueries(query: Query) -> Query:
        """Unnest simple subqueries that are pure filters.

        A subquery is unnestable when it is of the form
        ``SELECT * FROM R WHERE p`` (no joins, group-by, having, ordering or
        limit).
        """
        query = copy.deepcopy(query)
        return QueryOptimizer._unnest_subqueries_internal(query)

    @staticmethod
    def _unnest_subqueries_internal(query: Query) -> Query:
        """Recursive subquery unnesting.  Mutates *query* in-place (safe after
        copy)."""
        # ── Main source ──────────────────────────────────────────────────
        if query.source.subquery is not None:
            # Recursively unnest the inner query first
            query.source.subquery = QueryOptimizer._unnest_subqueries_internal(
                query.source.subquery
            )
            if QueryOptimizer._is_unnestable(query.source.subquery):
                inner = query.source.subquery
                new_source = copy.deepcopy(inner.source)
                inner_where = copy.deepcopy(inner.where)
                query.source = new_source
                if inner_where is not None:
                    if query.where is not None:
                        query.where = CompoundPred("and", [inner_where, query.where])
                    else:
                        query.where = inner_where
                # Source replaced; try again (the new source may itself be
                # unnestable)
                return QueryOptimizer._unnest_subqueries_internal(query)

        # ── Join sources ─────────────────────────────────────────────────
        for join in query.joins:
            if join.with_source.subquery is not None:
                join.with_source.subquery = QueryOptimizer._unnest_subqueries_internal(
                    join.with_source.subquery
                )
                if QueryOptimizer._is_unnestable(join.with_source.subquery):
                    inner = join.with_source.subquery
                    join.with_source = copy.deepcopy(inner.source)
                    if inner.where is not None:
                        if query.where is not None:
                            query.where = CompoundPred(
                                "and", [inner.where, query.where]
                            )
                        else:
                            query.where = inner.where

        return query

    @staticmethod
    def _is_unnestable(query: Query) -> bool:
        """Check whether *query* is a simple filter that can be flattened.

        Conditions (all must hold):
        * ``SELECT`` is exactly ``[*]`` (one Literal with value ``"*"``)
        * ``source`` is a named relation (not another subquery or graph_fn)
        * No ``joins``, ``group_by``, ``having``, ``order_by``, or ``limit``
        """
        if len(query.select) != 1:
            return False
        if not isinstance(query.select[0], Literal):
            return False
        if query.select[0].value != "*":
            return False
        if query.source is None or query.source.relation is None:
            return False
        if query.joins:
            return False
        if query.group_by is not None:
            return False
        if query.having is not None:
            return False
        if query.order_by is not None:
            return False
        if query.limit is not None:
            return False
        return True

    # ── Join Order Optimization ──────────────────────────────────────────────────

    @staticmethod
    def _optimize_join_order(query: Query, store: ResultStore) -> Query:
        """Greedy join-order optimisation for inner joins.

        Only queries with at least two inner joins are reordered.  Non-inner
        joins (LEFT / RIGHT / FULL) are left in their original relative order
        since swapping them changes semantics.
        """
        query = copy.deepcopy(query)

        if len(query.joins) < 2:
            return query

        # Separate inner from non-inner joins
        inner_joins: list[JoinClause] = []
        non_inner_joins: list[JoinClause] = []

        for join in query.joins:
            if join.type == "inner":
                inner_joins.append(join)
            else:
                non_inner_joins.append(join)

        if len(inner_joins) < 2:
            return query

        # ── Greedy reorder ───────────────────────────────────────────────
        current_cardinality = QueryOptimizer._resolve_source_cardinality(
            query.source, store
        )

        remaining = list(inner_joins)
        ordered: list[JoinClause] = []

        while remaining:
            best_idx = 0
            best_cost = float("inf")

            for j, join in enumerate(remaining):
                right_card = QueryOptimizer._resolve_source_cardinality(
                    join.with_source, store
                )
                is_equi = QueryOptimizer._is_equi_join(join)
                cost = (
                    current_cardinality + max(right_card, 1)
                    if is_equi
                    else current_cardinality * max(right_card, 1)
                )
                if cost < best_cost:
                    best_cost = cost
                    best_idx = j

            best_join = remaining.pop(best_idx)
            ordered.append(best_join)

            # Update estimated cardinality using NDV-based selectivity
            right_card = QueryOptimizer._resolve_source_cardinality(
                best_join.with_source, store
            )
            if QueryOptimizer._is_equi_join(best_join):
                ndv = QueryOptimizer._estimate_join_ndv(best_join, store)
                selectivity = 1.0 / max(ndv, 1)
                current_cardinality = max(
                    1, int(current_cardinality * max(right_card, 1) * selectivity)
                )
            else:
                current_cardinality = int(
                    current_cardinality * max(right_card, 1) * 0.1
                )

        # Reordered inner joins first, then non-inner joins (preserving
        # original relative order).
        query.joins = ordered + non_inner_joins
        return query

    @staticmethod
    def _resolve_source_cardinality(source: Source, store: ResultStore) -> int:
        """Estimate the number of rows for a *source*.

        Uses the store's relation length when available; falls back to a
        conservative estimate of 100 rows.
        """
        if source.relation is not None:
            rel = getattr(store, source.relation, None)
            if rel is not None and hasattr(rel, "__len__"):
                return len(rel)
        elif source.subquery is not None:
            # Cardinality of a simple subquery is the same as its inner source
            return QueryOptimizer._resolve_source_cardinality(
                source.subquery.source, store
            )
        elif source.graph_fn is not None:
            rel = getattr(store, "files", None)
            if rel is not None and hasattr(rel, "__len__"):
                return len(rel)
        return 100  # fallback

    @staticmethod
    def _extract_equi_pairs(pred: Predicate) -> list[tuple[str, str]]:
        """Extract all equi-column pairs ``(left_col, right_col)`` from a predicate.

        Only collects within AND trees.  Returns [] for OR / NOT (conservative).
        Both sides must be ``ColumnRef`` for a pair to qualify.
        """
        if isinstance(pred, CompoundPred) and pred.op == "and":
            pairs: list[tuple[str, str]] = []
            for op in pred.operands:
                pairs.extend(QueryOptimizer._extract_equi_pairs(op))
            return pairs
        if isinstance(pred, BinaryPred) and pred.op == "eq":
            if isinstance(pred.left, ColumnRef) and isinstance(pred.right, ColumnRef):
                return [(pred.left.column, pred.right.column)]
            return []
        if isinstance(pred, CompoundPred) and pred.op in ("or", "not"):
            return []
        return []

    @staticmethod
    def _estimate_join_ndv(join: JoinClause, store: ResultStore) -> int:
        """Estimate the NDV (number of distinct values) for the join key.

        Uses the right-side column(s) from the equi pairs of the join.
        Falls back to 10 (heuristic default) when NDV cannot be determined.
        """
        pairs = QueryOptimizer._extract_equi_pairs(join.on)
        if not pairs:
            return 10
        right_cols = [p[1] for p in pairs]
        source_name = QueryOptimizer._resolve_source_name(join.with_source, store)
        if source_name is None:
            return 10
        rel = getattr(store, source_name, None)
        if rel is None or not hasattr(rel, "distinct_count"):
            return 10
        try:
            if len(right_cols) == 1:
                return rel.distinct_count(right_cols[0])
            # 多列 NDV 取各列 NDV 最大值（保守估算）
            ndvs = []
            for col in right_cols:
                try:
                    ndvs.append(rel.distinct_count(col))
                except KeyError:
                    ndvs.append(10)
            return max(ndvs) if ndvs else 10
        except KeyError:
            return 10

    @staticmethod
    def _is_equi_join(join: JoinClause) -> bool:
        """Return ``True`` when *join* is an equi-join (all ON conditions are eq
        with ColumnRef on both sides).

        Handles both single ``eq(a, b)`` and compound ``AND(eq(a,b), eq(c,d))``.
        """
        return len(QueryOptimizer._extract_equi_pairs(join.on)) > 0
