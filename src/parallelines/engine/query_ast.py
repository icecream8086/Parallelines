"""Query DSL — AST node type definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal as _Literal


# ── Expression nodes ────────────────────────────────────────


@dataclass
class ColumnRef:
    column: str
    relation: str | None = None


@dataclass
class Literal:
    value: str | int | float | bool | None


# ── Predicate nodes ─────────────────────────────────────────


@dataclass
class BinaryPred:
    op: _Literal["eq", "neq", "gt", "gte", "lt", "lte"]
    left: ColumnRef
    right: Literal | ColumnRef


@dataclass
class LikePred:
    column: ColumnRef
    pattern: str


@dataclass
class InPred:
    column: ColumnRef
    values: list[Literal]
    negated: bool = False


@dataclass
class IsNullPred:
    column: ColumnRef
    not_null: bool = False


@dataclass
class CompoundPred:
    op: _Literal["and", "or", "not"]
    operands: list[Predicate]

    def __post_init__(self) -> None:
        if self.op == "not" and len(self.operands) != 1:
            raise ValueError("'not' requires exactly 1 operand")
        if self.op in ("and", "or") and len(self.operands) < 2:
            raise ValueError(f"'{self.op}' requires at least 2 operands")


@dataclass
class GraphPred:
    op: str  # "ancestor_is_map" | "descendant_is_script" | "descendant_is_any"
    column: ColumnRef
    params: dict | None = None


@dataclass
class StringPred:
    op: str  # "starts_with" | "ends_with" | "contains" | "not_contains"
    column: ColumnRef
    pattern: str


@dataclass
class ExistsPred:
    not_exists: bool  # False = exists_in, True = not_exists_in
    column: ColumnRef
    target_relation: str
    target_column: str = "virtual_path"


Predicate = (
    BinaryPred
    | LikePred
    | InPred
    | IsNullPred
    | CompoundPred
    | GraphPred
    | StringPred
    | ExistsPred
)


# ── Query nodes ────────────────────────────────────────────


@dataclass
class JoinClause:
    type: _Literal["inner", "left", "right", "full"]
    with_source: Source
    on: Predicate


@dataclass
class GroupByClause:
    columns: list[ColumnRef]
    aggregations: dict[str, str | list | dict]


@dataclass
class OrderByClause:
    column: ColumnRef
    direction: _Literal["asc", "desc"]


@dataclass
class Source:
    relation: str | None = None
    subquery: Query | None = None
    graph_fn: str | None = None
    graph_fn_arg: str | None = None

    def __post_init__(self) -> None:
        has_rel = self.relation is not None
        has_sub = self.subquery is not None
        has_graph = self.graph_fn is not None
        if sum([has_rel, has_sub, has_graph]) != 1:
            raise ValueError(
                "Source must have exactly one of 'relation', 'subquery', or 'graph_fn'"
            )


@dataclass
class Query:
    select: list[ColumnRef | Literal]
    source: Source
    where: Predicate | None = None
    joins: list[JoinClause] = field(default_factory=list)
    group_by: GroupByClause | None = None
    having: Predicate | None = None
    order_by: OrderByClause | None = None
    limit: int | None = None
    offset: int | None = None
