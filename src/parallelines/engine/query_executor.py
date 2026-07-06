"""Execute a validated Query AST against a ResultStore."""

from __future__ import annotations

import fnmatch
from typing import Callable

from parallelines.engine.query_ast import (
    BinaryPred,
    ColumnRef,
    CompoundPred,
    InPred,
    IsNullPred,
    LikePred,
    Literal,
    Predicate,
    Query,
    Source,
)
from parallelines.engine.store import Relation, ResultStore


class QueryExecutor:
    """Execute a validated Query against a ResultStore → Relation."""

    @staticmethod
    def execute(query: Query, store: ResultStore) -> Relation:
        """Execute a validated query and return a Relation."""
        # 1. Resolve source → base Relation
        relation = QueryExecutor._resolve_source(query.source, store)

        # 2. Apply join if present
        if query.join is not None:
            relation = QueryExecutor._apply_join(relation, query.join, store)

        # 3. Apply where if present
        if query.where is not None:
            pred = query.where
            cols = relation.columns

            def _where_fn(row) -> bool:  # type: ignore[no-untyped-def]
                return QueryExecutor._eval_predicate(pred, row, cols)

            relation = relation.select(_where_fn)

        # 4. Apply group_by if present
        if query.group_by is not None:
            relation = QueryExecutor._apply_group_by(relation, query.group_by)

        # 5. Apply order_by if present
        if query.order_by is not None:
            relation = QueryExecutor._apply_order_by(relation, query.order_by)

        # 6. Apply limit if present
        if query.limit is not None:
            relation = Relation(
                name=relation.name,
                columns=relation.columns,
                rows=relation.rows[: query.limit],
            )

        # 7. Apply select (projection)
        relation = QueryExecutor._apply_select(relation, query.select)

        return relation

    # ── Internal helpers ─────────────────────────────────────

    @staticmethod
    def _resolve_source(source: Source, store: ResultStore) -> Relation:
        if source.relation is not None:
            rel = getattr(store, source.relation, None)
            if rel is None:
                raise ValueError(f"Relation '{source.relation}' not found in store")
            return rel
        if source.subquery is not None:
            return QueryExecutor.execute(source.subquery, store)
        raise ValueError("Source has neither relation nor subquery")

    @staticmethod
    def _apply_join(relation: Relation, join_clause, store: ResultStore) -> Relation:
        """Apply a join clause using the store's join method on the join key."""
        with_rel = QueryExecutor._resolve_source(join_clause.with_source, store)

        # Extract the join column name from the predicate (assumes eq on a single column)
        on_col = QueryExecutor._extract_join_column(join_clause.on)
        if on_col is None:
            msg = "Join predicate must be a simple eq on a single column"
            raise ValueError(msg)

        join_type = join_clause.type

        if join_type == "inner":
            return relation.join(with_rel, on=on_col)
        if join_type == "left":
            return relation.join_left(with_rel, on=on_col)
        if join_type == "right":
            return with_rel.join_left(relation, on=on_col)
        if join_type == "full":
            left = relation.join_left(with_rel, on=on_col)
            right = with_rel.join_left(relation, on=on_col)

            rel_on_idx = relation.columns.index(on_col)
            rel_on_values: set = set()
            for row in relation.rows:
                v = row[rel_on_idx] if isinstance(row, tuple) else getattr(row, on_col)
                if v is not None:
                    rel_on_values.add(v)

            # Only append right rows whose join key doesn't appear in relation
            with_rel_on_idx = with_rel.columns.index(on_col)
            merged: list = list(left.rows)
            for row in right.rows:
                on_val = (
                    row[with_rel_on_idx]
                    if isinstance(row, tuple)
                    else getattr(row, on_col)
                )
                if on_val not in rel_on_values:
                    merged.append(row)
            return Relation(
                name=f"{relation.name}⟗{with_rel.name}",
                columns=left.columns,
                rows=merged,
            )
        raise ValueError(f"Unknown join type: {join_type}")

    @staticmethod
    def _extract_join_column(pred: Predicate) -> str | None:
        """Extract the column name from a binary eq predicate used in a join on clause."""
        if isinstance(pred, BinaryPred) and pred.op == "eq":
            return pred.left.column
        if isinstance(pred, CompoundPred):
            for op in pred.operands:
                result = QueryExecutor._extract_join_column(op)
                if result is not None:
                    return result
        return None

    @staticmethod
    def _apply_group_by(relation: Relation, group_clause) -> Relation:
        """Apply group by with aggregations.

        The aggregation dict maps output column name → aggregation type.
        For sum/avg/min/max, the key is the column to aggregate.
        For count, the key is just a label.
        """
        group_col = group_clause.columns[0].column
        agg_spec = group_clause.aggregations

        agg_fns: dict[str, Callable] = {}
        for agg_name, agg_spec_val in agg_spec.items():
            # Two formats:
            #   "count"             → simple count
            #   ["sum", "file_size"] → aggregation with source column
            if isinstance(agg_spec_val, str):
                agg_fns[agg_name] = len  # count
            elif isinstance(agg_spec_val, list):
                agg_type, source_col = agg_spec_val[0], agg_spec_val[1]
                if agg_type == "sum":
                    agg_fns[agg_name] = lambda rows, _col=source_col: sum(
                        float(getattr(r, _col)) if hasattr(r, _col) else 0.0
                        for r in rows
                    )
                elif agg_type == "avg":
                    agg_fns[agg_name] = lambda rows, _col=source_col: (
                        sum(
                            float(getattr(r, _col)) if hasattr(r, _col) else 0.0
                            for r in rows
                        )
                        / len(rows)
                        if rows
                        else 0.0
                    )
                elif agg_type == "min":
                    agg_fns[agg_name] = lambda rows, _col=source_col: min(
                        getattr(r, _col) if hasattr(r, _col) else 0 for r in rows
                    )
                elif agg_type == "max":
                    agg_fns[agg_name] = lambda rows, _col=source_col: max(
                        getattr(r, _col) if hasattr(r, _col) else 0 for r in rows
                    )

        return relation.group_by(group_col, agg_fns)

    @staticmethod
    def _apply_order_by(relation: Relation, order_clause) -> Relation:
        """Apply ordering to a relation."""
        col_name = order_clause.column.column
        direction = order_clause.direction
        reverse = direction == "desc"

        if col_name not in relation.columns:
            return relation  # column not found, skip

        col_idx = relation.columns.index(col_name)

        def sort_key(row):
            if isinstance(row, tuple):
                return row[col_idx]
            return getattr(row, col_name)

        sorted_rows = sorted(relation.rows, key=sort_key, reverse=reverse)
        return Relation(
            name=relation.name,
            columns=relation.columns,
            rows=sorted_rows,
        )

    @staticmethod
    def _apply_select(relation: Relation, select: list) -> Relation:
        """Apply column projection from the select clause."""
        # If select is [Literal("*")], return all columns
        if (
            len(select) == 1
            and isinstance(select[0], Literal)
            and select[0].value == "*"
        ):
            return relation

        col_names: list[str] = []
        for item in select:
            if isinstance(item, ColumnRef):
                col_names.append(item.column)
            elif isinstance(item, Literal) and item.value == "*":
                return relation  # wildcard in multi-select

        try:
            return relation.project(*col_names)
        except KeyError as e:
            raise ValueError(f"Select column not found: {e}")

    @staticmethod
    def _eval_predicate(pred: Predicate, row, columns: tuple[str, ...]) -> bool:
        """Recursively evaluate a predicate against a single row."""
        if isinstance(pred, BinaryPred):
            left = QueryExecutor._get_col_value(pred.left, row, columns)
            if isinstance(pred.right, Literal):
                right = pred.right.value
            else:
                right = QueryExecutor._get_col_value(pred.right, row, columns)
            if pred.op == "eq":
                return left == right
            if pred.op == "neq":
                return left != right
            if pred.op == "gt":
                return bool(left is not None and right is not None and left > right)
            if pred.op == "gte":
                return bool(left is not None and right is not None and left >= right)
            if pred.op == "lt":
                return bool(left is not None and right is not None and left < right)
            if pred.op == "lte":
                return bool(left is not None and right is not None and left <= right)
            return False

        if isinstance(pred, CompoundPred):
            results = [
                QueryExecutor._eval_predicate(p, row, columns) for p in pred.operands
            ]
            if pred.op == "and":
                return all(results)
            if pred.op == "or":
                return any(results)
            if pred.op == "not":
                return not results[0]
            return False

        if isinstance(pred, LikePred):
            val = QueryExecutor._get_col_value(pred.column, row, columns)
            return fnmatch.fnmatch(str(val), pred.pattern)

        if isinstance(pred, InPred):
            val = QueryExecutor._get_col_value(pred.column, row, columns)
            return val in [lit.value for lit in pred.values]

        if isinstance(pred, IsNullPred):
            val = QueryExecutor._get_col_value(pred.column, row, columns)
            return val is None if not pred.not_null else val is not None

        return False

    @staticmethod
    def _get_col_value(ref: ColumnRef, row, columns: tuple[str, ...]):
        """Extract a column value from a row by ColumnRef."""
        idx = columns.index(ref.column)
        if isinstance(row, tuple):
            return row[idx]
        return getattr(row, ref.column)
