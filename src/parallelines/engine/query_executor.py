"""Execute a validated Query AST against a ResultStore."""

from __future__ import annotations

import fnmatch
from typing import Callable

import icontract
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
    @icontract.ensure(lambda result: result is not None)
    def execute(query: Query, store: ResultStore) -> Relation:
        """Execute a validated query and return a Relation."""
        # 1. Resolve source → base Relation
        relation = QueryExecutor._resolve_source(query.source, store)

        # 2. Apply joins if present (multi-join, left-deep tree)
        for join_clause in query.joins:
            relation = QueryExecutor._apply_join(relation, join_clause, store)

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

        # 6. Apply limit / offset if present
        if query.limit is not None or query.offset is not None:
            start = query.offset or 0
            end = (start + query.limit) if query.limit is not None else None
            relation = Relation(
                name=relation.name,
                columns=relation.columns,
                rows=relation.rows[start:end],
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
        """Apply a join clause using hash join (equi) or theta join (non-equi).

        Automatically selects hash join when the ON predicate contains
        equi-column conditions; falls back to nested-loop theta join otherwise.
        """
        right_rel = QueryExecutor._resolve_source(join_clause.with_source, store)
        join_type = join_clause.type
        on_pred = join_clause.on

        # 1. Extract equi pairs for hash join optimization
        equi_pairs = QueryExecutor._extract_equi_pairs(on_pred)

        if equi_pairs:
            return QueryExecutor._apply_hash_join(
                relation, right_rel, join_type, equi_pairs, on_pred, store,
            )

        # 2. No equi conditions — theta join (nested-loop)
        return QueryExecutor._apply_theta_join(
            relation, right_rel, join_type, on_pred, store,
        )

    @staticmethod
    def _apply_hash_join(
        relation: Relation,
        right_rel: Relation,
        join_type: str,
        equi_pairs: list[tuple[str, str]],
        on_pred: Predicate,
        store: ResultStore,
    ) -> Relation:
        """Equi-join via hash index (inner / left / right / full).

        When equi column names differ between left and right, the right
        relation is temporarily renamed before the hash join.
        """
        left_cols = tuple(p[0] for p in equi_pairs)
        right_cols = tuple(p[1] for p in equi_pairs)

        # Determine the ON key (str for single, tuple for composite)
        def _on_key(cols: tuple[str, ...]) -> str | tuple[str, ...]:
            return cols[0] if len(cols) == 1 else cols

        if join_type == "right":
            # Right join: swap left/right, do a left join
            if right_cols != left_cols:
                relation = relation.rename(dict(zip(left_cols, right_cols)))
            result = right_rel.join_left(relation, on=_on_key(right_cols))
        else:
            if left_cols == right_cols:
                on_key = _on_key(left_cols)
            else:
                rename_map = dict(zip(right_cols, left_cols))
                right_rel = right_rel.rename(rename_map)
                on_key = _on_key(left_cols)

            if join_type == "inner":
                result = relation.join(right_rel, on=on_key)
            elif join_type == "left":
                result = relation.join_left(right_rel, on=on_key)
            elif join_type == "full":
                result = relation.join_full(right_rel, on=on_key)
            else:
                raise ValueError(f"Unknown join type: {join_type}")

        # 3. Apply remaining non-equi predicates on the join result
        remaining = QueryExecutor._remove_equi_from_pred(on_pred, equi_pairs)
        if remaining is not None:
            compiled = QueryExecutor._compile_predicate(
                remaining, result.columns, graph=store.graph, store=store,
            )
            if compiled is not None:
                result = result.select(compiled)
            else:
                def _pred_fn(row, _p=remaining, _cols=result.columns):
                    return QueryExecutor._eval_predicate(
                        _p, row, _cols, graph=store.graph, store=store,
                    )
                result = result.select(_pred_fn)

        return result

    @staticmethod
    def _apply_theta_join(
        relation: Relation,
        right_rel: Relation,
        join_type: str,
        on_pred: Predicate,
        store: ResultStore,
    ) -> Relation:
        """Non-equi join via nested-loop theta join.

        Evaluates the predicate against each (left, right) row pair by
        constructing a combined row object that resolves columns from both
        relations.
        """
        def _theta_fn(l_row, r_row):
            combined_cols = relation.columns + right_rel.columns

            class _CombinedRow:
                """Adapter: resolves getattr from either left or right row."""

                def __getattr__(self, name):
                    if name in relation.columns:
                        idx = relation.columns.index(name)
                        if isinstance(l_row, tuple):
                            return l_row[idx]
                        return getattr(l_row, name)
                    if name in right_rel.columns:
                        idx = right_rel.columns.index(name)
                        if isinstance(r_row, tuple):
                            return r_row[idx]
                        return getattr(r_row, name)
                    raise AttributeError(name)

            return QueryExecutor._eval_predicate(
                on_pred, _CombinedRow(), combined_cols,
                graph=store.graph, store=store,
            )

        return relation.join_theta(right_rel, _theta_fn, how=join_type)

    # ── Equi-pair extraction ────────────────────────────────────

    @staticmethod
    def _extract_equi_pairs(pred: Predicate) -> list[tuple[str, str]]:
        """Extract all equi-column pairs ``(left_col, right_col)`` from a predicate.

        Only collects within AND trees.  Returns [] for OR / NOT (conservative).
        Both sides must be ``ColumnRef`` for a pair to qualify.
        """
        if isinstance(pred, CompoundPred) and pred.op == "and":
            pairs: list[tuple[str, str]] = []
            for op in pred.operands:
                pairs.extend(QueryExecutor._extract_equi_pairs(op))
            return pairs
        if isinstance(pred, BinaryPred) and pred.op == "eq":
            if isinstance(pred.left, ColumnRef) and isinstance(pred.right, ColumnRef):
                return [(pred.left.column, pred.right.column)]
            return []
        if isinstance(pred, CompoundPred) and pred.op in ("or", "not"):
            return []
        return []

    @staticmethod
    def _remove_equi_from_pred(
        pred: Predicate,
        equi_pairs: list[tuple[str, str]],
    ) -> Predicate | None:
        """Remove already-extracted equi conditions, returning the remainder.

        Returns ``None`` when the predicate has been fully consumed.
        """
        if isinstance(pred, CompoundPred) and pred.op == "and":
            remaining: list[Predicate] = []
            for op in pred.operands:
                result = QueryExecutor._remove_equi_from_pred(op, equi_pairs)
                if result is not None:
                    remaining.append(result)
            if len(remaining) > 1:
                return CompoundPred("and", remaining)
            if len(remaining) == 1:
                return remaining[0]
            return None
        if (
            isinstance(pred, BinaryPred)
            and pred.op == "eq"
            and isinstance(pred.left, ColumnRef)
            and isinstance(pred.right, ColumnRef)
            and (pred.left.column, pred.right.column) in equi_pairs
        ):
            return None
        return pred

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
                if pred.op == "descendant_is_any":
                    descendants = nx.descendants(graph, str(path))
                    exts = pred.params.get("extensions", [".nut"]) if pred.params else [".nut"]
                    return any(d.lower().endswith(tuple(exts)) for d in descendants)
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
            if op in ("gt", "gte", "lt", "lte"):
                def _cmp_fn(row, _idx=col_idx, _v=val, _op=op, _col=pred.left.column):
                    x = row[_idx] if isinstance(row, tuple) else getattr(row, _col)
                    if x is None or _v is None:
                        return False
                    if _op == "gt":
                        return x > _v
                    if _op == "gte":
                        return x >= _v
                    if _op == "lt":
                        return x < _v
                    if _op == "lte":
                        return x <= _v
                    return False

                return _cmp_fn

        # StringPred compilation
        if isinstance(pred, StringPred):
            col_name = pred.column.column
            if col_name not in columns:
                return None
            col_idx = columns.index(col_name)
            pattern = pred.pattern
            _str_op = pred.op

            def _get_str(row, _idx=col_idx, _c=col_name):
                val = row[_idx] if isinstance(row, tuple) else getattr(row, _c)
                return None if val is None else str(val)

            if _str_op == "ends_with":
                return lambda row, _idx=col_idx, _p=pattern, _fn=_get_str: (
                    False if _fn(row) is None else _fn(row).endswith(_p)
                )
            if _str_op == "starts_with":
                return lambda row, _idx=col_idx, _p=pattern, _fn=_get_str: (
                    False if _fn(row) is None else _fn(row).startswith(_p)
                )
            if _str_op == "contains":
                return lambda row, _idx=col_idx, _p=pattern, _fn=_get_str: (
                    False if _fn(row) is None else _p in _fn(row)
                )
            if _str_op == "not_contains":
                return lambda row, _idx=col_idx, _p=pattern, _fn=_get_str: (
                    False if _fn(row) is None else _p not in _fn(row)
                )

        # LikePred compilation
        if isinstance(pred, LikePred):
            col_name = pred.column.column
            if col_name not in columns:
                return None
            col_idx = columns.index(col_name)
            pattern = pred.pattern
            return lambda row, _idx=col_idx, _p=pattern: (
                False
                if (row[_idx] if isinstance(row, tuple) else getattr(row, col_name)) is None
                else fnmatch.fnmatch(
                    str(
                        row[_idx] if isinstance(row, tuple) else getattr(row, col_name)
                    ),
                    _p,
                )
            )

        # InPred compilation
        if isinstance(pred, InPred):
            col_name = pred.column.column
            if col_name not in columns:
                return None
            col_idx = columns.index(col_name)
            values = {lit.value for lit in pred.values}
            negated = pred.negated
            if negated:
                return lambda row, _idx=col_idx, _v=values, _c=col_name: (
                    row[_idx] if isinstance(row, tuple) else getattr(row, _c)
                ) not in _v
            return lambda row, _idx=col_idx, _v=values, _c=col_name: (
                row[_idx] if isinstance(row, tuple) else getattr(row, _c)
            ) in _v

        # Fallback: return None (caller uses interpreter)
        return None


# Import at module level for _apply_group_by count_where support
from parallelines.engine.query_parser import QueryParser  # noqa: E402
