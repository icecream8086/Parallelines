"""JSON dict → Query AST parser."""

from __future__ import annotations

from parallelines.engine.query_ast import (
    BinaryPred,
    ColumnRef,
    CompoundPred,
    ExistsPred,
    GraphPred,
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
    StringPred,
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
        try:
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

            having: Predicate | None = None
            if "having" in d:
                having = QueryParser._parse_predicate(d["having"])

            order_by = None
            if "order_by" in d:
                order_by = QueryParser._parse_order(d["order_by"])

            limit: int | None = d.get("limit")
            if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool)):
                raise QueryParseError(
                    f"'limit' must be an integer, got {type(limit).__name__}"
                )

            return Query(
                select=select,
                source=source,
                where=where,
                join=join,
                group_by=group_by,
                having=having,
                order_by=order_by,
                limit=limit,
            )
        except (KeyError, ValueError, TypeError) as e:
            raise QueryParseError(f"Failed to parse query: {e}") from e

    @staticmethod
    def _parse_source(s: str | dict) -> Source:
        if isinstance(s, str):
            return Source(relation=s)
        if "query" in s:
            return Source(subquery=QueryParser.parse(s["query"]))
        if "descendants_of" in s:
            return Source(graph_fn="descendants_of", graph_fn_arg=s["descendants_of"])
        if "ancestors_of" in s:
            return Source(graph_fn="ancestors_of", graph_fn_arg=s["ancestors_of"])
        if "find_cycles" in s:
            return Source(graph_fn="find_cycles")
        raise QueryParseError(f"Invalid source: {s}")

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
            return BinaryPred("eq", QueryParser._parse_col(k), QueryParser._parse_value(v))
        if "neq" in p:
            k, v = p["neq"]
            return BinaryPred("neq", QueryParser._parse_col(k), QueryParser._parse_value(v))
        if "gt" in p:
            k, v = p["gt"]
            return BinaryPred("gt", QueryParser._parse_col(k), QueryParser._parse_value(v))
        if "gte" in p:
            k, v = p["gte"]
            return BinaryPred("gte", QueryParser._parse_col(k), QueryParser._parse_value(v))
        if "lt" in p:
            k, v = p["lt"]
            return BinaryPred("lt", QueryParser._parse_col(k), QueryParser._parse_value(v))
        if "lte" in p:
            k, v = p["lte"]
            return BinaryPred("lte", QueryParser._parse_col(k), QueryParser._parse_value(v))
        if "like" in p:
            k, pat = p["like"]
            return LikePred(QueryParser._parse_col(k), pat)
        if "in" in p:
            k, vals = p["in"]
            return InPred(QueryParser._parse_col(k), [Literal(v) for v in vals])
        if "not_in" in p:
            k, vals = p["not_in"]
            return InPred(
                QueryParser._parse_col(k), [Literal(v) for v in vals], negated=True
            )
        if "is_null" in p:
            return IsNullPred(QueryParser._parse_col(p["is_null"]))
        if "is_not_null" in p:
            return IsNullPred(QueryParser._parse_col(p["is_not_null"]), True)
        if "ancestor_is_map" in p:
            return GraphPred(
                "ancestor_is_map", QueryParser._parse_col(p["ancestor_is_map"])
            )
        if "descendant_is_script" in p:
            return GraphPred(
                "descendant_is_script",
                QueryParser._parse_col(p["descendant_is_script"]),
            )
        if "starts_with" in p:
            col, pat = p["starts_with"]
            return StringPred("starts_with", QueryParser._parse_col(col), pat)
        if "ends_with" in p:
            col, pat = p["ends_with"]
            return StringPred("ends_with", QueryParser._parse_col(col), pat)
        if "contains" in p:
            col, pat = p["contains"]
            return StringPred("contains", QueryParser._parse_col(col), pat)
        if "not_contains" in p:
            col, pat = p["not_contains"]
            return StringPred("not_contains", QueryParser._parse_col(col), pat)
        if "exists_in" in p:
            col_target = p["exists_in"]
            col_name = col_target[0] if isinstance(col_target, list) else col_target
            target = col_target[1] if isinstance(col_target, list) else ""
            return ExistsPred(False, QueryParser._parse_col(col_name), target)
        if "not_exists_in" in p:
            col_target = p["not_exists_in"]
            col_name = col_target[0] if isinstance(col_target, list) else col_target
            target = col_target[1] if isinstance(col_target, list) else ""
            return ExistsPred(True, QueryParser._parse_col(col_name), target)
        raise QueryParseError(f"Unknown predicate: {p}")

    @staticmethod
    def _parse_col(ref: str | list) -> ColumnRef:
        if isinstance(ref, list):
            if len(ref) == 0:
                raise QueryParseError("Empty column reference list")
            if len(ref) > 2:
                raise QueryParseError(
                    f"Column reference list too long (max 2, got {len(ref)}): {ref}"
                )
            if len(ref) == 1:
                if not ref[0]:
                    raise QueryParseError("Empty column name in reference list")
                return ColumnRef(column=ref[0])
            if not ref[1]:
                raise QueryParseError("Empty column name in reference list")
            return ColumnRef(column=ref[1], relation=ref[0])
        # Support "relation.column" dot notation as sugar for ["relation", "column"]
        if not ref:
            raise QueryParseError("Empty column name")
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
    def _parse_value(v) -> Literal | ColumnRef:
        """Parse a value in a binary predicate. List → ColumnRef, otherwise → Literal."""
        if isinstance(v, list):
            return QueryParser._parse_col(v)
        return _to_literal(v)

    @staticmethod
    def _parse_order(o: dict) -> OrderByClause:
        direction = o.get("dir", "asc")
        if direction not in ("asc", "desc"):
            raise QueryParseError(
                f"Invalid order direction '{direction}', must be 'asc' or 'desc'"
            )
        return OrderByClause(
            column=QueryParser._parse_col(o["by"]),
            direction=direction,
        )
