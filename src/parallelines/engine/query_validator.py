"""Query validation against a ResultStore schema."""

from __future__ import annotations

import dataclasses

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


def _type_name(tp: type | str) -> str:
    """Get the string name of a type annotation (type object or string)."""
    if isinstance(tp, str):
        return tp
    return tp.__name__


class QueryValidationError(Exception):
    """Raised when a query fails schema validation."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


class QueryValidator:
    """Validate a Query AST against a ResultStore schema."""

    @staticmethod
    def validate(query: Query, store: ResultStore) -> list[str]:
        """Run all 7 validation rules. Returns a list of error messages (empty = valid)."""
        errors: list[str] = []

        # Resolve the base relation name from the source
        source_name = QueryValidator._resolve_source_name(query.source)
        if source_name is None:
            errors.append("Subquery sources cannot be validated at top level")
            return errors

        schema = QueryValidator._get_relation_schema(source_name, store)
        if schema is None:
            errors.append(f"Relation '{source_name}' not found in store")
            return errors

        all_columns = set(schema)

        # Collect every ColumnRef in the query for R1/R2 checks
        refs: list[ColumnRef] = []
        QueryValidator._collect_column_refs(query, refs)

        # R0 — Source mutual exclusivity
        errors += QueryValidator._validate_source(query.source)

        # R1 — Column existence
        # When group_by is present, aggregation output names are also valid columns.
        r1_allowed = set(all_columns)
        if query.group_by is not None:
            r1_allowed.update(query.group_by.aggregations.keys())
        # When joins are present, join target columns are also valid.
        for jc in query.joins:
            join_source_name = QueryValidator._resolve_source_name(jc.with_source)
            if join_source_name is not None:
                join_schema = QueryValidator._get_relation_schema(join_source_name, store)
                if join_schema is not None:
                    r1_allowed.update(join_schema)
        for ref in refs:
            if ref.column not in r1_allowed:
                errors.append(
                    f"R1: Column '{ref.column}' does not exist in relation '{source_name}'"
                )

        # R2 — Type compatibility (check BinaryPred ops)
        # We use the store's schema to infer types from the dataclass fields.
        type_map = QueryValidator._build_type_map(source_name, store)
        for ref in refs:
            # Check binary predicates that involve this column
            pass  # handled by iterating predicates below

        # Walk predicates for R2 checks
        if query.where is not None:
            QueryValidator._check_predicate_types(
                query.where, type_map, source_name, errors, store
            )
        for jc in query.joins:
            QueryValidator._check_predicate_types(
                jc.on, type_map, source_name, errors, store
            )
        if query.having is not None:
            QueryValidator._check_predicate_types(
                query.having, type_map, source_name, errors, store
            )

        # R3 — Join key existence
        for jc in query.joins:
            join_on_cols: list[ColumnRef] = []
            QueryValidator._collect_predicate_refs(jc.on, join_on_cols)
            join_source_name = QueryValidator._resolve_source_name(
                jc.with_source
            )
            if join_source_name is not None:
                join_schema = QueryValidator._get_relation_schema(
                    join_source_name, store
                )
                if join_schema is not None:
                    join_columns = set(join_schema)
                    for ref in join_on_cols:
                        if ref.relation is not None and ref.relation != source_name:
                            # refers to the join side
                            if ref.column not in join_columns:
                                errors.append(
                                    f"R3: Join column '{ref.column}' not found in relation '{join_source_name}'"
                                )
                        elif ref.column not in all_columns:
                            # refers to the main side
                            pass  # already caught by R1
                else:
                    errors.append(
                        f"R3: Join target relation '{join_source_name}' not found in store"
                    )
            else:
                errors.append("R3: Cannot validate join against subquery source")

        # R4 — Aggregation legality
        if query.group_by is not None:
            group_col_names = {c.column for c in query.group_by.columns}
            agg_keys = set(query.group_by.aggregations.keys())
            for item in query.select:
                if isinstance(item, Literal):
                    continue  # literal "*" is always valid in grouped context
                if item.column not in group_col_names and item.column not in agg_keys:
                    errors.append(
                        f"R4: Column '{item.column}' must be in group_by columns or aggregation keys"
                    )

        # R5 — Subquery visibility
        QueryValidator._check_subquery_visibility(
            query.source, store, errors, context="source"
        )
        for jc in query.joins:
            QueryValidator._check_subquery_visibility(
                jc.with_source, store, errors, context="join"
            )

        # R6 — Join type degradation (warn)
        for jc in query.joins:
            if jc.type == "full":
                errors.append(
                    "R6: Full outer join is not natively supported; will be emulated as left ∪ right union"
                )

        return errors

    # ── Internal helpers ─────────────────────────────────────

    @staticmethod
    def _resolve_source_name(source: Source) -> str | None:
        if source.relation is not None:
            return source.relation
        if source.graph_fn is not None:
            if source.graph_fn == "find_cycles":
                return "dependency_cycles"
            return "files"  # descendants_of/ancestors_of return FileRow-like rows
        return None  # subquery

    @staticmethod
    def _get_relation_schema(name: str, store: ResultStore) -> tuple[str, ...] | None:
        rel = getattr(store, name, None)
        if rel is not None and isinstance(rel, Relation):
            return rel.columns if rel.columns else tuple(
                f.name for f in dataclasses.fields(rel._row_type)
            ) if rel._row_type else ()
        return None

    @staticmethod
    def _build_type_map(name: str, store: ResultStore) -> dict[str, str]:
        """Build a {column_name: type_name} map from the store relation's dataclass."""
        rel = getattr(store, name, None)
        if rel is None:
            return {}
        row_type = rel._row_type or (type(rel.rows[0]) if rel.rows else None)
        if row_type is None:
            return {}
        if dataclasses.is_dataclass(row_type):
            return {f.name: _type_name(f.type) for f in dataclasses.fields(row_type)}
        return {}

    @staticmethod
    def _collect_column_refs(query: Query, refs: list[ColumnRef]) -> None:
        """Collect all ColumnRefs from a query into *refs*."""
        for item in query.select:
            if isinstance(item, ColumnRef):
                refs.append(item)
        if query.where is not None:
            QueryValidator._collect_predicate_refs(query.where, refs)
        for jc in query.joins:
            QueryValidator._collect_predicate_refs(jc.on, refs)
        if query.having is not None:
            QueryValidator._collect_predicate_refs(query.having, refs)
        if query.order_by is not None:
            refs.append(query.order_by.column)

    @staticmethod
    def _collect_predicate_refs(pred: Predicate, refs: list[ColumnRef]) -> None:
        if isinstance(pred, BinaryPred):
            refs.append(pred.left)
            if isinstance(pred.right, ColumnRef):
                refs.append(pred.right)
        elif isinstance(pred, LikePred | InPred | IsNullPred | GraphPred | StringPred):
            refs.append(pred.column)
        elif isinstance(pred, ExistsPred):
            refs.append(pred.column)
        elif isinstance(pred, CompoundPred):
            for op in pred.operands:
                QueryValidator._collect_predicate_refs(op, refs)

    @staticmethod
    def _check_predicate_types(
        pred: Predicate,
        type_map: dict[str, str],
        relation_name: str,
        errors: list[str],
        store=None,
    ) -> None:
        """Check type compatibility in predicates (R2)."""
        if isinstance(pred, BinaryPred):
            col_name = pred.left.column
            col_type = type_map.get(col_name, "")
            if pred.op in ("gt", "gte", "lt", "lte"):
                if col_type not in ("int", "float", "Int64", "Float64"):
                    errors.append(
                        f"R2: Cannot use '{pred.op}' on non-numeric column '{col_name}' (type: {col_type})"
                    )
            if isinstance(pred.right, Literal) and pred.right.value is not None:
                # Check that literal is compatible with gt/gte/lt/lte
                if pred.op in ("gt", "gte", "lt", "lte"):
                    if not isinstance(pred.right.value, (int, float)):
                        errors.append(
                            f"R2: Literal value for '{pred.op}' must be numeric"
                        )
        elif isinstance(pred, LikePred):
            col_name = pred.column.column
            col_type = type_map.get(col_name, "")
            # like only makes sense on string columns
            if col_type not in ("str", "string"):
                errors.append(
                    f"R2: Cannot use 'like' on non-string column '{col_name}' (type: {col_type})"
                )
        elif isinstance(pred, InPred):
            col_name = pred.column.column
            col_type = type_map.get(col_name, "")
            for lit in pred.values:
                if lit.value is not None and not isinstance(
                    lit.value, (str, int, float, bool)
                ):
                    errors.append(
                        f"R2: InPred value type mismatch for column '{col_name}'"
                    )
        elif isinstance(pred, StringPred):
            col_name = pred.column.column
            col_type = type_map.get(col_name, "")
            if col_type not in ("str", "string", ""):
                errors.append(
                    f"R2: Cannot use '{pred.op}' on non-string column '{col_name}' (type: {col_type})"
                )
        elif isinstance(pred, ExistsPred):
            if store is None:
                errors.append("R2: Cannot validate ExistsPred without store access")
            else:
                target_rel = getattr(store, pred.target_relation, None)
                if target_rel is None:
                    errors.append(
                        f"R2: Target relation '{pred.target_relation}' not found for exists_in/not_exists_in"
                    )
                else:
                    if pred.target_column not in target_rel.columns:
                        errors.append(
                            f"R2: Column '{pred.target_column}' not in relation '{pred.target_relation}'"
                        )
        elif isinstance(pred, GraphPred):
            col_name = pred.column.column
            if col_name not in type_map:
                errors.append(
                    f"R2: Column '{col_name}' not found for {pred.op}"
                )
        elif isinstance(pred, CompoundPred):
            if pred.op == "not" and len(pred.operands) != 1:
                errors.append("R2: 'not' requires exactly 1 operand")
            elif pred.op in ("and", "or") and len(pred.operands) < 2:
                errors.append(f"R2: '{pred.op}' requires at least 2 operands")
            for op in pred.operands:
                QueryValidator._check_predicate_types(
                    op, type_map, relation_name, errors, store
                )

    @staticmethod
    def _check_subquery_visibility(
        source: Source,
        store: ResultStore,
        errors: list[str],
        context: str = "source",
    ) -> None:
        """Validate subquery sources (R5)."""
        if source.subquery is not None:
            sub_name = QueryValidator._resolve_source_name(source.subquery.source)
            if sub_name is not None:
                schema = QueryValidator._get_relation_schema(sub_name, store)
                if schema is None:
                    errors.append(
                        f"R5: Subquery {context} relation '{sub_name}' not found in store"
                    )

    @staticmethod
    def _validate_source(source: Source) -> list[str]:
        """R0 — Source.relation, Source.subquery, and Source.graph_fn are mutually exclusive."""
        has_rel = source.relation is not None
        has_sub = source.subquery is not None
        has_graph = source.graph_fn is not None
        count = sum([has_rel, has_sub, has_graph])
        if count > 1:
            return [
                "R0: Source must have at most one of 'relation', 'subquery', or 'graph_fn'"
            ]
        if count == 0:
            return ["R0: Source must have one of 'relation', 'subquery', or 'graph_fn'"]
        return []
