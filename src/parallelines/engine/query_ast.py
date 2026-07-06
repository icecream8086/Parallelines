"""Query DSL — AST node type definitions."""

from __future__ import annotations

from dataclasses import dataclass
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


Predicate = BinaryPred | LikePred | InPred | IsNullPred | CompoundPred


# ── Query nodes ────────────────────────────────────────────


@dataclass
class JoinClause:
    type: _Literal["inner", "left", "right", "full"]
    with_source: Source
    on: Predicate


@dataclass
class GroupByClause:
    columns: list[ColumnRef]
    aggregations: dict[str, _Literal["count", "sum", "avg", "min", "max"]]


@dataclass
class OrderByClause:
    column: ColumnRef
    direction: _Literal["asc", "desc"]


@dataclass
class Source:
    relation: str | None = None
    subquery: Query | None = None

    def __post_init__(self) -> None:
        has_rel = self.relation is not None
        has_sub = self.subquery is not None
        if has_rel == has_sub:
            raise ValueError("Source must have exactly one of 'relation' or 'subquery'")


@dataclass
class Query:
    select: list[ColumnRef | Literal]
    source: Source
    where: Predicate | None = None
    join: JoinClause | None = None
    group_by: GroupByClause | None = None
    order_by: OrderByClause | None = None
    limit: int | None = None
