"""JSON dict → Query AST parser."""

from __future__ import annotations

from parallelines.engine.query_ast import (
    BinaryPred,
    ColumnRef,
    CompoundPred,
    GroupByClause,
    InPred,
    IsNullPred,
    JoinClause,
    LikePred,
    Literal,
    OrderByClause,
    Predicate,
    Query,
    Source,
)


class QueryParseError(Exception):
    """Raised when a query dict cannot be parsed."""


def _to_literal(v) -> Literal:
    if isinstance(v, Literal):
        return v
    return Literal(v)


class QueryParser:
    """Parse a JSON-compatible dict into a Query AST node."""

    @staticmethod
    def parse(d: dict) -> Query:
        """Parse a JSON dict into a Query AST node."""
        # ── select ───────────────────────────────────────────
        raw_select = d["select"]
        if raw_select == ["*"]:
            select: list[ColumnRef | Literal] = [Literal("*")]
        else:
            select = [QueryParser._parse_col(s) for s in raw_select]

        # ── from / source ────────────────────────────────────
        source = QueryParser._parse_source(d["from"])

        # ── optional clauses ─────────────────────────────────
        where: Predicate | None = None
        if "where" in d:
            where = QueryParser._parse_predicate(d["where"])

        join: JoinClause | None = None
        if "join" in d:
            join = QueryParser._parse_join(d["join"])

        group_by: GroupByClause | None = None
        if "group_by" in d:
            group_by = QueryParser._parse_group(d["group_by"])

        order_by = None
        if "order_by" in d:
            order_by = QueryParser._parse_order(d["order_by"])

        limit: int | None = d.get("limit")

        return Query(
            select=select,
            source=source,
            where=where,
            join=join,
            group_by=group_by,
            order_by=order_by,
            limit=limit,
        )

    @staticmethod
    def _parse_source(s: str | dict) -> Source:
        if isinstance(s, str):
            return Source(relation=s)
        # subquery
        return Source(subquery=QueryParser.parse(s["query"]))

    @staticmethod
    def _parse_predicate(p: dict) -> Predicate:
        """Recursively parse a predicate dict."""
        if "and" in p:
            return CompoundPred(
                "and", [QueryParser._parse_predicate(pp) for pp in p["and"]]
            )
        if "or" in p:
            return CompoundPred(
                "or", [QueryParser._parse_predicate(pp) for pp in p["or"]]
            )
        if "not" in p:
            return CompoundPred("not", [QueryParser._parse_predicate(p["not"])])
        if "eq" in p:
            k, v = p["eq"]
            return BinaryPred("eq", QueryParser._parse_col(k), _to_literal(v))
        if "neq" in p:
            k, v = p["neq"]
            return BinaryPred("neq", QueryParser._parse_col(k), _to_literal(v))
        if "gt" in p:
            k, v = p["gt"]
            return BinaryPred("gt", QueryParser._parse_col(k), _to_literal(v))
        if "gte" in p:
            k, v = p["gte"]
            return BinaryPred("gte", QueryParser._parse_col(k), _to_literal(v))
        if "lt" in p:
            k, v = p["lt"]
            return BinaryPred("lt", QueryParser._parse_col(k), _to_literal(v))
        if "lte" in p:
            k, v = p["lte"]
            return BinaryPred("lte", QueryParser._parse_col(k), _to_literal(v))
        if "like" in p:
            k, pat = p["like"]
            return LikePred(QueryParser._parse_col(k), pat)
        if "in" in p:
            k, vals = p["in"]
            return InPred(QueryParser._parse_col(k), [Literal(v) for v in vals])
        if "is_null" in p:
            return IsNullPred(QueryParser._parse_col(p["is_null"]))
        if "is_not_null" in p:
            return IsNullPred(QueryParser._parse_col(p["is_not_null"]), True)
        raise QueryParseError(f"Unknown predicate: {p}")

    @staticmethod
    def _parse_col(ref: str | list) -> ColumnRef:
        if isinstance(ref, list):
            if len(ref) == 1:
                return ColumnRef(column=ref[0])
            return ColumnRef(column=ref[1], relation=ref[0])
        # Support "relation.column" dot notation as sugar for ["relation", "column"]
        if "." in ref:
            parts = ref.split(".", 1)
            return ColumnRef(column=parts[1], relation=parts[0])
        return ColumnRef(column=ref)

    @staticmethod
    def _parse_join(j: dict) -> JoinClause:
        return JoinClause(
            type=j["type"],
            with_source=QueryParser._parse_source(j["with"]),
            on=QueryParser._parse_predicate(j["on"]),
        )

    @staticmethod
    def _parse_group(g: dict) -> GroupByClause:
        return GroupByClause(
            columns=[QueryParser._parse_col(c) for c in g["by"]],
            aggregations=g["agg"],
        )

    @staticmethod
    def _parse_order(o: dict) -> OrderByClause:
        return OrderByClause(
            column=QueryParser._parse_col(o["by"]),
            direction=o.get("dir", "asc"),
        )
