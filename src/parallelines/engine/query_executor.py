"""Execute a validated Query AST against a ResultStore."""

from __future__ import annotations

import fnmatch
from typing import Callable

import networkx as nx

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

            # O1: Fast path — simple eq predicate uses hash index
            if (
                isinstance(pred, BinaryPred)
                and pred.op == "eq"
                and isinstance(pred.right, Literal)
            ):
                col_name = pred.left.column
                if col_name in relation.columns:
                    indexed = relation.select_by(col_name, pred.right.value)
                    if indexed.rows:
                        relation = Relation(
                            name=relation.name,
                            columns=relation.columns,
                            rows=indexed.rows,
                        )
                    else:
                        relation = indexed
                else:
                    compiled = QueryExecutor._compile_predicate(
                        pred, cols, graph=store.graph, store=store
                    )
                    if compiled is not None:
                        relation = relation.select(compiled)
                    else:

                        def _where_fn(row, _p=pred, _c=cols) -> bool:
                            return QueryExecutor._eval_predicate(
                                _p, row, _c, graph=store.graph, store=store
                            )

                        relation = relation.select(_where_fn)
            else:
                compiled = QueryExecutor._compile_predicate(
                    pred, cols, graph=store.graph, store=store
                )
                if compiled is not None:
                    relation = relation.select(compiled)
                else:

                    def _where_fn(row, _p=pred, _c=cols) -> bool:
                        return QueryExecutor._eval_predicate(
                            _p, row, _c, graph=store.graph, store=store
                        )

                    relation = relation.select(_where_fn)

        # 4. Apply group_by if present
        if query.group_by is not None:
            relation = QueryExecutor._apply_group_by(relation, query.group_by, store)

        # 4b. Apply having if present (after group_by, before order_by)
        if query.having is not None and query.group_by is not None:
            pred = query.having
            cols = relation.columns

            def _having_fn(row) -> bool:
                return QueryExecutor._eval_predicate(
                    pred, row, cols, graph=store.graph, store=store
                )

            relation = relation.select(_having_fn)

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
            if not isinstance(rel, Relation):
                raise ValueError(f"'{source.relation}' is not a Relation in the store")
            return rel
        if source.subquery is not None:
            return QueryExecutor.execute(source.subquery, store)
        if source.graph_fn is not None:
            if source.graph_fn == "descendants_of":
                return store.descendants(source.graph_fn_arg)  # type: ignore[arg-type]
            if source.graph_fn == "ancestors_of":
                return store.ancestors(source.graph_fn_arg)  # type: ignore[arg-type]
            if source.graph_fn == "find_cycles":
                if store.dependency_cycles is not None:
                    return store.dependency_cycles
                return Relation("cycles", ("cycle", "length"), [])
        raise ValueError("Source has neither relation, subquery, nor graph_fn")

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
            return relation.join_full(with_rel, on=on_col)
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
    def _apply_group_by(relation: Relation, group_clause, store=None) -> Relation:
        """Apply group by with aggregations.

        The aggregation dict maps output column name → aggregation type.
        For sum/avg/min/max, the key is the column to aggregate.
        For count, the key is just a label.
        For count_where, value is {"count_where": {"eq": ["col", true]}}
        """
        group_cols = tuple(c.column for c in group_clause.columns)
        agg_spec = group_clause.aggregations

        agg_fns: dict[str, Callable] = {}
        for agg_name, agg_spec_val in agg_spec.items():
            # count_where conditional aggregation
            if isinstance(agg_spec_val, dict) and "count_where" in agg_spec_val:
                where_pred = agg_spec_val["count_where"]
                pred_ast = QueryParser._parse_predicate(where_pred)
                col_names = relation.columns
                graph = getattr(store, "graph", None) if store else None
                agg_fns[agg_name] = lambda rows, _pred=pred_ast, _cols=col_names, _g=graph: sum(  # type: ignore[no-untyped-def]
                    1
                    for r in rows
                    if QueryExecutor._eval_predicate(_pred, r, _cols, graph=_g, store=store)
                )
            # Two formats:
            #   "count"             → simple count
            #   ["sum", "file_size"] → aggregation with source column
            elif isinstance(agg_spec_val, str):
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

        return relation.group_by(group_cols, agg_fns)

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
    def _eval_predicate(
        pred: Predicate,
        row,
        columns: tuple[str, ...],
        graph=None,
        store=None,
    ) -> bool:
        """Recursively evaluate a predicate against a single row."""
        if isinstance(pred, BinaryPred):
            left = QueryExecutor._get_col_value(pred.left, row, columns)
            if isinstance(pred.right, Literal):
                right = pred.right.value
            elif isinstance(pred.right, ColumnRef):
                right = QueryExecutor._get_col_value(pred.right, row, columns)
            else:
                right = pred.right
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
                QueryExecutor._eval_predicate(p, row, columns, graph=graph, store=store)
                for p in pred.operands
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
            if val is None:
                return False
            return fnmatch.fnmatch(str(val), pred.pattern)

        if isinstance(pred, InPred):
            val = QueryExecutor._get_col_value(pred.column, row, columns)
            result = val in [lit.value for lit in pred.values]
            return not result if pred.negated else result

        if isinstance(pred, IsNullPred):
            val = QueryExecutor._get_col_value(pred.column, row, columns)
            return val is None if not pred.not_null else val is not None

        if isinstance(pred, GraphPred):
            path = QueryExecutor._get_col_value(pred.column, row, columns)
            if graph is None:
                return False
            try:
                if pred.op == "ancestor_is_map":
                    ancestors = nx.ancestors(graph, str(path))
                    return any(a.endswith(".bsp") for a in ancestors)
                if pred.op == "descendant_is_script":
                    descendants = nx.descendants(graph, str(path))
                    return any(d.endswith(".nut") for d in descendants)
            except (nx.NetworkXError, KeyError):
                return False
            return False

        if isinstance(pred, StringPred):
            val = QueryExecutor._get_col_value(pred.column, row, columns)
            if val is None:
                return False
            sval = str(val)
            if pred.op == "starts_with":
                return sval.startswith(pred.pattern)
            if pred.op == "ends_with":
                return sval.endswith(pred.pattern)
            if pred.op == "contains":
                return pred.pattern in sval
            if pred.op == "not_contains":
                return pred.pattern not in sval
            return False

        if isinstance(pred, ExistsPred):
            val = QueryExecutor._get_col_value(pred.column, row, columns)
            if store is None:
                return False
            target_rel = getattr(store, pred.target_relation, None)
            if target_rel is None:
                return False
            # Use hash index for O(1) lookup
            if pred.target_column not in target_rel._index:
                target_rel.build_index(pred.target_column)
            matches = target_rel.lookup(pred.target_column, val)
            result = len(matches) > 0
            return not result if pred.not_exists else result

        return False

    @staticmethod
    def _get_col_value(ref: ColumnRef, row, columns: tuple[str, ...]):
        """Extract a column value from a row by ColumnRef."""
        if ref.column not in columns:
            # Try with relation qualifier
            qualified = f"{ref.relation}.{ref.column}" if ref.relation else ref.column
            if qualified in columns:
                idx = columns.index(qualified)
            else:
                raise ValueError(f"Column '{ref.column}' not found in {columns}")
        else:
            idx = columns.index(ref.column)
        if isinstance(row, tuple):
            return row[idx]
        return getattr(row, ref.column)

    @staticmethod
    def _compile_predicate(
        pred: Predicate,
        columns: tuple[str, ...],
        graph=None,
        store=None,
    ) -> Callable | None:
        """Compile a Predicate AST into a Callable for fast execution.

        Returns None if compilation is not supported (falls back to interpreter).
        """
        # For simple BinaryPred eq/neq on same-column with literal, fast path
        if isinstance(pred, BinaryPred) and isinstance(pred.right, Literal):
            if pred.left.column not in columns:
                return None  # column not found, fall back to interpreter
            col_idx = columns.index(pred.left.column)
            val = pred.right.value
            op = pred.op
            if op == "eq":
                return lambda row, _idx=col_idx, _v=val: (
                    (
                        row[_idx]
                        if isinstance(row, tuple)
                        else getattr(row, pred.left.column)
                    )
                    == _v
                )
            if op == "neq":
                return lambda row, _idx=col_idx, _v=val: (
                    (
                        row[_idx]
                        if isinstance(row, tuple)
                        else getattr(row, pred.left.column)
                    )
                    != _v
                )
        # Fallback: return None (caller uses interpreter)
        return None


# Import at module level for _apply_group_by count_where support
from parallelines.engine.query_parser import QueryParser  # noqa: E402
