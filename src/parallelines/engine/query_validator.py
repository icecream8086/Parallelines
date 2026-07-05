"""Query validation against a ResultStore schema."""

from __future__ import annotations

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
from parallelines.engine.store import ResultStore


class QueryValidationError(Exception):
    """Raised when a query fails schema validation."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


class QueryValidator:
    """Validate a Query AST against a ResultStore schema."""

    @staticmethod
    def validate(query: Query, store: ResultStore) -> list[str]:
        """Run all 6 validation rules. Returns a list of error messages (empty = valid)."""
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
        for ref in refs:
            if ref.column not in all_columns:
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
                query.where, type_map, source_name, errors
            )
        if query.join is not None:
            QueryValidator._check_predicate_types(
                query.join.on, type_map, source_name, errors
            )

        # R3 — Join key existence
        if query.join is not None:
            join_on_cols: list[ColumnRef] = []
            QueryValidator._collect_predicate_refs(query.join.on, join_on_cols)
            join_source_name = QueryValidator._resolve_source_name(
                query.join.with_source
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
        if query.join is not None:
            QueryValidator._check_subquery_visibility(
                query.join.with_source, store, errors, context="join"
            )

        # R6 — Join type degradation (warn)
        if query.join is not None and query.join.type == "full":
            errors.append(
                "R6: Full outer join is not natively supported; will be emulated as left ∪ right union"
            )

        return errors

    # ── Internal helpers ─────────────────────────────────────

    @staticmethod
    def _resolve_source_name(source: Source) -> str | None:
        if source.relation is not None:
            return source.relation
        return None  # subquery

    @staticmethod
    def _get_relation_schema(name: str, store: ResultStore) -> tuple[str, ...] | None:
        rel = getattr(store, name, None)
        if rel is not None:
            return rel.columns
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
        import dataclasses

        if dataclasses.is_dataclass(row_type):
            return {f.name: f.type.__name__ for f in dataclasses.fields(row_type)}
        return {}

    @staticmethod
    def _collect_column_refs(query: Query, refs: list[ColumnRef]) -> None:
        """Collect all ColumnRefs from a query into *refs*."""
        for item in query.select:
            if isinstance(item, ColumnRef):
                refs.append(item)
        if query.where is not None:
            QueryValidator._collect_predicate_refs(query.where, refs)
        if query.join is not None:
            QueryValidator._collect_predicate_refs(query.join.on, refs)

    @staticmethod
    def _collect_predicate_refs(pred: Predicate, refs: list[ColumnRef]) -> None:
        if isinstance(pred, BinaryPred):
            refs.append(pred.left)
            if isinstance(pred.right, ColumnRef):
                refs.append(pred.right)
        elif isinstance(pred, LikePred | InPred | IsNullPred):
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
        elif isinstance(pred, CompoundPred):
            if pred.op == "not" and len(pred.operands) != 1:
                errors.append("R2: 'not' requires exactly 1 operand")
            elif pred.op in ("and", "or") and len(pred.operands) < 2:
                errors.append(f"R2: '{pred.op}' requires at least 2 operands")
            for op in pred.operands:
                QueryValidator._check_predicate_types(
                    op, type_map, relation_name, errors
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
        """R0 — Source.relation and Source.subquery are mutually exclusive."""
        has_rel = source.relation is not None
        has_sub = source.subquery is not None
        if has_rel and has_sub:
            return ["R0: Source cannot have both 'relation' and 'subquery'"]
        if not has_rel and not has_sub:
            return ["R0: Source must have either 'relation' or 'subquery'"]
        return []
