"""JSON parser tests (PAR-01 ~ PAR-34, PAR-ERR-01 ~ PAR-ERR-22)."""
from __future__ import annotations

import pytest
from parallelines.engine.query_parser import QueryParseError, QueryParser
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
    StringPred,
)


class TestParserSource:
    def test_simple_from(self):
        """PAR-01: Simplest query select * from files."""
        q = QueryParser.parse({"select": ["*"], "from": "files"})
        assert len(q.select) == 1
        assert isinstance(q.select[0], Literal)
        assert q.select[0].value == "*"
        assert q.source.relation == "files"

    def test_column_selection(self):
        """PAR-02: Select specific columns."""
        q = QueryParser.parse({"select": ["a", "b"], "from": "f"})
        assert len(q.select) == 2
        assert q.select[0].column == "a"
        assert q.select[1].column == "b"

    def test_dot_column(self):
        """PAR-03: Dot notation column ref."""
        q = QueryParser.parse({"select": ["r.c"], "from": "f"})
        assert isinstance(q.select[0], ColumnRef)
        assert q.select[0].column == "c"
        assert q.select[0].relation == "r"

    def test_list_column(self):
        """PAR-04: List notation column ref."""
        q = QueryParser.parse({"select": [["r", "c"]], "from": "f"})
        assert isinstance(q.select[0], ColumnRef)
        assert q.select[0].column == "c"
        assert q.select[0].relation == "r"

    def test_subquery_source(self):
        """PAR-05: Subquery source."""
        q = QueryParser.parse({
            "select": ["*"],
            "from": {"query": {"select": ["*"], "from": "files"}},
        })
        assert q.source.subquery is not None
        assert q.source.subquery.source.relation == "files"

    def test_descendants_of(self):
        """PAR-06: descendants_of source."""
        q = QueryParser.parse({
            "select": ["*"],
            "from": {"descendants_of": "maps/c1m1.bsp"},
        })
        assert q.source.graph_fn == "descendants_of"
        assert q.source.graph_fn_arg == "maps/c1m1.bsp"

    def test_ancestors_of(self):
        """PAR-07: ancestors_of source."""
        q = QueryParser.parse({
            "select": ["*"],
            "from": {"ancestors_of": "materials/test.vmt"},
        })
        assert q.source.graph_fn == "ancestors_of"
        assert q.source.graph_fn_arg == "materials/test.vmt"

    def test_find_cycles(self):
        """PAR-08: find_cycles source."""
        q = QueryParser.parse({
            "select": ["*"],
            "from": {"find_cycles": True},
        })
        assert q.source.graph_fn == "find_cycles"


class TestParserPredicates:
    def test_eq(self):
        """PAR-09: eq predicate."""
        q = QueryParser.parse({
            "select": ["*"], "from": "f",
            "where": {"eq": ["col", "val"]},
        })
        assert isinstance(q.where, BinaryPred)
        assert q.where.op == "eq"
        assert q.where.left.column == "col"
        assert q.where.right.value == "val"

    def test_all_binary_ops(self):
        """PAR-10: All binary ops (neq/gt/gte/lt/lte)."""
        for op in ("neq", "gt", "gte", "lt", "lte"):
            q = QueryParser.parse({
                "select": ["*"], "from": "f",
                "where": {op: ["col", 1]},
            })
            assert isinstance(q.where, BinaryPred)
            assert q.where.op == op

    def test_eq_cross_column(self):
        """PAR-11: eq with cross-column ref on right."""
        q = QueryParser.parse({
            "select": ["*"], "from": "f",
            "where": {"eq": [["f", "a"], ["g", "b"]]},
        })
        assert isinstance(q.where, BinaryPred)
        assert q.where.op == "eq"
        assert isinstance(q.where.right, ColumnRef)

    def test_and_compound(self):
        """PAR-12: and compound predicate."""
        q = QueryParser.parse({
            "select": ["*"], "from": "f",
            "where": {"and": [
                {"eq": ["a", 1]},
                {"gt": ["b", 0]},
            ]},
        })
        assert isinstance(q.where, CompoundPred)
        assert q.where.op == "and"
        assert len(q.where.operands) == 2

    def test_or_compound(self):
        """PAR-13: or compound predicate."""
        q = QueryParser.parse({
            "select": ["*"], "from": "f",
            "where": {"or": [
                {"eq": ["a", 1]},
                {"eq": ["a", 2]},
            ]},
        })
        assert isinstance(q.where, CompoundPred)
        assert q.where.op == "or"

    def test_not_compound(self):
        """PAR-14: not compound predicate."""
        q = QueryParser.parse({
            "select": ["*"], "from": "f",
            "where": {"not": {"eq": ["a", 1]}},
        })
        assert isinstance(q.where, CompoundPred)
        assert q.where.op == "not"
        assert len(q.where.operands) == 1

    def test_like(self):
        """PAR-15: like predicate."""
        q = QueryParser.parse({
            "select": ["*"], "from": "f",
            "where": {"like": ["col", "*.vmt"]},
        })
        assert isinstance(q.where, LikePred)
        assert q.where.pattern == "*.vmt"

    def test_in(self):
        """PAR-16: in predicate."""
        q = QueryParser.parse({
            "select": ["*"], "from": "f",
            "where": {"in": ["col", [1, 2, 3]]},
        })
        assert isinstance(q.where, InPred)
        assert q.where.negated is False
        assert [lit.value for lit in q.where.values] == [1, 2, 3]

    def test_not_in(self):
        """PAR-17: not_in predicate."""
        q = QueryParser.parse({
            "select": ["*"], "from": "f",
            "where": {"not_in": ["col", [1, 2, 3]]},
        })
        assert isinstance(q.where, InPred)
        assert q.where.negated is True

    def test_is_null(self):
        """PAR-18: is_null predicate."""
        q = QueryParser.parse({
            "select": ["*"], "from": "f",
            "where": {"is_null": "col"},
        })
        assert isinstance(q.where, IsNullPred)
        assert q.where.not_null is False

    def test_is_not_null(self):
        """PAR-19: is_not_null predicate."""
        q = QueryParser.parse({
            "select": ["*"], "from": "f",
            "where": {"is_not_null": "col"},
        })
        assert isinstance(q.where, IsNullPred)
        assert q.where.not_null is True

    def test_ancestor_is_map(self):
        """PAR-20: ancestor_is_map predicate."""
        q = QueryParser.parse({
            "select": ["*"], "from": "f",
            "where": {"ancestor_is_map": "virtual_path"},
        })
        assert isinstance(q.where, GraphPred)
        assert q.where.op == "ancestor_is_map"

    def test_descendant_is_script(self):
        """PAR-21: descendant_is_script predicate."""
        q = QueryParser.parse({
            "select": ["*"], "from": "f",
            "where": {"descendant_is_script": "virtual_path"},
        })
        assert isinstance(q.where, GraphPred)
        assert q.where.op == "descendant_is_script"

    def test_starts_with(self):
        """PAR-22: starts_with predicate."""
        q = QueryParser.parse({
            "select": ["*"], "from": "f",
            "where": {"starts_with": ["col", "pre"]},
        })
        assert isinstance(q.where, StringPred)
        assert q.where.op == "starts_with"
        assert q.where.pattern == "pre"

    def test_ends_with(self):
        """PAR-23: ends_with predicate."""
        q = QueryParser.parse({
            "select": ["*"], "from": "f",
            "where": {"ends_with": ["col", ".nut"]},
        })
        assert isinstance(q.where, StringPred)
        assert q.where.op == "ends_with"

    def test_contains(self):
        """PAR-24: contains predicate."""
        q = QueryParser.parse({
            "select": ["*"], "from": "f",
            "where": {"contains": ["col", "sub"]},
        })
        assert isinstance(q.where, StringPred)
        assert q.where.op == "contains"

    def test_not_contains(self):
        """PAR-25: not_contains predicate."""
        q = QueryParser.parse({
            "select": ["*"], "from": "f",
            "where": {"not_contains": ["col", "bad"]},
        })
        assert isinstance(q.where, StringPred)
        assert q.where.op == "not_contains"

    def test_exists_in(self):
        """PAR-26: exists_in predicate."""
        q = QueryParser.parse({
            "select": ["*"], "from": "f",
            "where": {"exists_in": ["virtual_path", "files"]},
        })
        assert isinstance(q.where, ExistsPred)
        assert q.where.not_exists is False
        assert q.where.target_relation == "files"

    def test_not_exists_in(self):
        """PAR-27: not_exists_in predicate."""
        q = QueryParser.parse({
            "select": ["*"], "from": "f",
            "where": {"not_exists_in": ["virtual_path", "files"]},
        })
        assert isinstance(q.where, ExistsPred)
        assert q.where.not_exists is True


class TestParserClauses:
    def test_join(self):
        """PAR-28: JOIN clause."""
        q = QueryParser.parse({
            "select": ["*"], "from": "f",
            "join": {
                "type": "inner",
                "with": "f2",
                "on": {"eq": [["f", "a"], ["f2", "b"]]},
            },
        })
        assert q.join is not None
        assert q.join.type == "inner"

    def test_group_by(self):
        """PAR-29: GROUP BY clause."""
        q = QueryParser.parse({
            "select": ["s", "cnt"], "from": "files",
            "group_by": {"by": ["s"], "agg": {"cnt": "count"}},
        })
        assert q.group_by is not None
        assert q.group_by.columns[0].column == "s"
        assert q.group_by.aggregations == {"cnt": "count"}

    def test_count_where(self):
        """PAR-30: count_where aggregation."""
        q = QueryParser.parse({
            "select": ["s"], "from": "files",
            "group_by": {
                "by": ["s"],
                "agg": {"active": {"count_where": {"eq": ["is_active", True]}}},
            },
        })
        assert q.group_by is not None
        agg = q.group_by.aggregations["active"]
        assert isinstance(agg, dict)
        assert "count_where" in agg

    def test_having(self):
        """PAR-31: HAVING clause."""
        q = QueryParser.parse({
            "select": ["s", "cnt"], "from": "f",
            "group_by": {"by": ["s"], "agg": {"cnt": "count"}},
            "having": {"gt": ["cnt", 10]},
        })
        assert q.having is not None
        assert isinstance(q.having, BinaryPred)

    def test_order_by_desc(self):
        """PAR-32: ORDER BY descending."""
        q = QueryParser.parse({
            "select": ["*"], "from": "f",
            "order_by": {"by": "c", "dir": "desc"},
        })
        assert q.order_by is not None
        assert q.order_by.direction == "desc"

    def test_order_by_default(self):
        """PAR-33: ORDER BY default asc."""
        q = QueryParser.parse({
            "select": ["*"], "from": "f",
            "order_by": {"by": "c"},
        })
        assert q.order_by is not None
        assert q.order_by.direction == "asc"

    def test_limit(self):
        """PAR-34: LIMIT clause."""
        q = QueryParser.parse({
            "select": ["*"], "from": "f",
            "limit": 20,
        })
        assert q.limit == 20


class TestParserErrors:
    def test_missing_select(self):
        """PAR-ERR-01: Missing select key."""
        with pytest.raises(QueryParseError):
            QueryParser.parse({})

    def test_missing_from(self):
        """PAR-ERR-02: Missing from key."""
        with pytest.raises(QueryParseError):
            QueryParser.parse({"select": ["*"]})

    def test_limit_string(self):
        """PAR-ERR-03: limit as string."""
        with pytest.raises(QueryParseError):
            QueryParser.parse({"select": ["*"], "from": "f", "limit": "ten"})

    def test_limit_bool(self):
        """PAR-ERR-04: limit as bool."""
        with pytest.raises(QueryParseError):
            QueryParser.parse({"select": ["*"], "from": "f", "limit": True})

    def test_invalid_order_dir(self):
        """PAR-ERR-05: invalid order direction."""
        with pytest.raises(QueryParseError):
            QueryParser.parse({
                "select": ["*"], "from": "f",
                "order_by": {"by": "c", "dir": "foo"},
            })

    def test_col_list_too_long(self):
        """PAR-ERR-06: column ref list too long."""
        with pytest.raises(QueryParseError):
            QueryParser.parse({"select": [["a", "b", "c"]], "from": "f"})

    def test_empty_col_list(self):
        """PAR-ERR-07: empty column ref list."""
        with pytest.raises(QueryParseError):
            QueryParser.parse({"select": [[]], "from": "f"})

    def test_invalid_source(self):
        """PAR-ERR-08: invalid source type."""
        with pytest.raises(QueryParseError):
            QueryParser.parse({
                "select": ["*"], "from": {"unknown": True},
            })

    def test_unknown_predicate(self):
        """PAR-ERR-09: unknown predicate."""
        with pytest.raises(QueryParseError):
            QueryParser.parse({
                "select": ["*"], "from": "f",
                "where": {"unknown_op": ["x", 1]},
            })

    def test_graph_fn_arg_not_str(self):
        """PAR-ERR-10: descendants_of argument not a string."""
        with pytest.raises(QueryParseError):
            QueryParser.parse({
                "select": ["*"], "from": {"descendants_of": 123},
            })

    def test_graph_fn_empty_path(self):
        """PAR-ERR-11: empty descendants_of path."""
        with pytest.raises(QueryParseError):
            QueryParser.parse({
                "select": ["*"], "from": {"descendants_of": ""},
            })

    def test_find_cycles_non_bool(self):
        """PAR-ERR-12: find_cycles with non-bool value."""
        with pytest.raises(QueryParseError):
            QueryParser.parse({
                "select": ["*"], "from": {"find_cycles": "yes"},
            })

    def test_eq_missing_operand(self):
        """PAR-ERR-13: eq with too few operands."""
        with pytest.raises(QueryParseError):
            QueryParser.parse({
                "select": ["*"], "from": "f",
                "where": {"eq": ["col"]},
            })

    def test_eq_extra_operand(self):
        """PAR-ERR-14: eq with too many operands."""
        with pytest.raises(QueryParseError):
            QueryParser.parse({
                "select": ["*"], "from": "f",
                "where": {"eq": ["col", "a", "b"]},
            })

    def test_in_non_iterable(self):
        """PAR-ERR-15: in with non-iterable value."""
        with pytest.raises(QueryParseError):
            QueryParser.parse({
                "select": ["*"], "from": "f",
                "where": {"in": ["col", 42]},
            })

    def test_and_empty(self):
        """PAR-ERR-16: and with no operands raises."""
        with pytest.raises((QueryParseError, ValueError)):
            QueryParser.parse({
                "select": ["*"], "from": "f",
                "where": {"and": []},
            })

    def test_and_single_operand(self):
        """PAR-ERR-17: and with 1 operand raises (needs ≥2)."""
        with pytest.raises((QueryParseError, ValueError)):
            QueryParser.parse({
                "select": ["*"], "from": "f",
                "where": {"and": [{"eq": ["c", "v"]}]},
            })

    def test_not_two_operands(self):
        """PAR-ERR-18: not with 2 operands raises."""
        with pytest.raises((QueryParseError, ValueError)):
            QueryParser.parse({
                "select": ["*"], "from": "f",
                "where": {"not": [{"eq": ["a", 1]}, {"eq": ["b", 2]}]},
            })

    def test_starts_with_missing_arg(self):
        """PAR-ERR-19: starts_with with missing argument."""
        with pytest.raises(QueryParseError):
            QueryParser.parse({
                "select": ["*"], "from": "f",
                "where": {"starts_with": ["col"]},
            })

    def test_exists_in_missing_arg(self):
        """PAR-ERR-20: exists_in with missing argument."""
        with pytest.raises((QueryParseError, IndexError)):
            QueryParser.parse({
                "select": ["*"], "from": "f",
                "where": {"exists_in": ["col"]},
            })

    def test_unknown_join_type(self):
        """PAR-ERR-21: unknown join type."""
        with pytest.raises(QueryParseError):
            QueryParser.parse({
                "select": ["*"], "from": "f",
                "join": {"type": "cross", "with": "r", "on": {"eq": ["a", "b"]}},
            })

    def test_null_source(self):
        """PAR-ERR-22: null source."""
        with pytest.raises(QueryParseError):
            QueryParser.parse({
                "select": ["*"], "from": None,
            })
