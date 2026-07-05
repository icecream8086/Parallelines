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


@dataclass
class Query:
    select: list[ColumnRef | Literal]
    source: Source
    where: Predicate | None = None
    join: JoinClause | None = None
    group_by: GroupByClause | None = None
    order_by: OrderByClause | None = None
    limit: int | None = None
