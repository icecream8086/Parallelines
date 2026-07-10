"""Test composite index, multi-column join, theta join, and rename."""
from __future__ import annotations

import pytest

from parallelines.engine.store import Relation


class TestCompositeIndex:
    def test_build_and_lookup_composite(self):
        """两列复合索引的构建和 O(1) 查找。"""
        rel = Relation("test", columns=("a", "b", "c"), rows=[
            (1, "x", 10), (2, "y", 20), (1, "x", 30), (3, "z", 40)
        ])
        rel.build_index("a", "b")
        result = rel.lookup(("a", "b"), (1, "x"))
        assert len(result) == 2
        assert result[0] == (1, "x", 10)
        assert result[1] == (1, "x", 30)

    def test_composite_none_skipped(self):
        """NULL 语义：复合键中任一元为 None 则跳过索引。"""
        rel = Relation("test", columns=("a", "b", "c"), rows=[
            (1, None, 10), (1, "x", 20), (None, "x", 30)
        ])
        rel.build_index("a", "b")
        result = rel.lookup(("a", "b"), (1, "x"))
        assert len(result) == 1
        assert result[0] == (1, "x", 20)

    def test_composite_not_indexed_raises(self):
        """复合索引未构建时 lookup 抛出 KeyError。"""
        rel = Relation("test", columns=("a", "b"), rows=[(1, "x")])
        with pytest.raises(KeyError, match="not built"):
            rel.lookup(("a", "b"), (1, "x"))


class TestMultiColumnJoin:
    def test_multi_column_equi_join(self):
        """两列等值 JOIN 结果正确。"""
        left = Relation("L", columns=("a", "b", "c"), rows=[
            (1, "x", 10), (2, "y", 20), (1, "z", 30)
        ])
        right = Relation("R", columns=("a", "b", "d"), rows=[
            (1, "x", 100), (2, "y", 200), (1, "z", 300), (1, "x", 400)
        ])
        result = left.join(right, on=("a", "b"))
        assert len(result) == 4
        assert result.columns == ("a", "b", "c", "d")
        rows = set(result.rows)
        assert (1, "x", 10, 100) in rows
        assert (1, "x", 10, 400) in rows
        assert (2, "y", 20, 200) in rows
        assert (1, "z", 30, 300) in rows

    def test_multi_column_join_left(self):
        """LEFT JOIN 保留不匹配行。"""
        left = Relation("L", columns=("a", "b", "c"), rows=[
            (1, "x", 10), (2, "y", 20), (3, "w", 999)
        ])
        right = Relation("R", columns=("a", "b", "d"), rows=[
            (1, "x", 100)
        ])
        result = left.join_left(right, on=("a", "b"))
        assert len(result) == 3
        assert result.columns == ("a", "b", "c", "d")
        assert result.rows[0] == (1, "x", 10, 100)
        assert result.rows[1] == (2, "y", 20, None)
        assert result.rows[2] == (3, "w", 999, None)

    def test_single_column_backward_compat(self):
        """单列 join 行为与之前完全一致。"""
        left = Relation("L", columns=("k", "v"), rows=[(1, "a"), (2, "b")])
        right = Relation("R", columns=("k", "w"), rows=[(1, "x"), (2, "y")])
        result = left.join(right, on="k")
        assert len(result) == 2
        assert result.columns == ("k", "v", "w")
        assert result.rows[0] == (1, "a", "x")
        assert result.rows[1] == (2, "b", "y")

    def test_multi_column_join_equals_cross_reference(self):
        """多列 JOIN 结果必须与手动交叉引用一致。"""
        left = Relation("L", columns=("a", "b", "c"), rows=[
            (1, "x", 10), (2, "y", 20), (1, "z", 30)
        ])
        right = Relation("R", columns=("a", "b", "d"), rows=[
            (1, "x", 100), (2, "y", 200), (1, "z", 300), (1, "x", 400)
        ])
        join_result = left.join(right, on=("a", "b"))
        # Manual cross-reference
        manual = []
        for lr in left.rows:
            for rr in right.rows:
                if lr[0] == rr[0] and lr[1] == rr[1]:
                    manual.append(lr + tuple(rr[i] for i, c in enumerate(right.columns) if c not in ("a", "b")))
        assert set(join_result.rows) == set(manual)


class TestThetaJoin:
    def test_theta_inner(self):
        """不等值条件 nested loop 结果正确。"""
        left = Relation("L", columns=("a", "v"), rows=[(1, 10), (2, 20)])
        right = Relation("R", columns=("b", "w"), rows=[(1, 15), (2, 25)])
        result = left.join_theta(
            right,
            predicate=lambda l, r: l[1] < r[1] if isinstance(l, tuple) else l.v < r.w,
            how="inner",
        )
        assert len(result) > 0
        # (1,10) < (1,15) and (1,10) < (2,25) and (2,20) < (2,25) → 3 matches
        assert len(result) == 3
        assert result.columns == ("a", "v", "b", "w")

    def test_theta_left_with_nulls(self):
        """θ-LEFT JOIN 不匹配行填充 None。"""
        left = Relation("L", columns=("a",), rows=[(1,), (99,)])
        right = Relation("R", columns=("b",), rows=[(1,), (2,)])
        result = left.join_theta(
            right,
            predicate=lambda l, r: (l[0] if isinstance(l, tuple) else l.a) == (r[0] if isinstance(r, tuple) else r.b),
            how="left",
        )
        assert len(result) == 2
        # (99,) unmatched → right side is None
        assert result.rows[1] == (99, None)

    def test_theta_column_conflict(self):
        """列名冲突时右表同名列加 _right 后缀。"""
        left = Relation("L", columns=("id", "name"), rows=[(1, "a")])
        right = Relation("R", columns=("id", "score"), rows=[(1, 100)])
        result = left.join_theta(
            right,
            predicate=lambda l, r: (l[0] if isinstance(l, tuple) else l.id) == (r[0] if isinstance(r, tuple) else r.id),
        )
        assert "id" in result.columns
        assert "id_right" in result.columns
        assert "name" in result.columns
        assert "score" in result.columns
        assert result.columns == ("id", "name", "id_right", "score")


class TestThetaJoinRightFull:
    def test_theta_right(self):
        """RIGHT θ-连接：右表所有行保留，左表无匹配时填充 None。"""
        left = Relation("L", columns=("a",), rows=[(1,), (99,)])
        right = Relation("R", columns=("b",), rows=[(1,), (2,)])
        result = left.join_theta(
            right,
            predicate=lambda l, r: (l[0] if isinstance(l, tuple) else l.a) == (r[0] if isinstance(r, tuple) else r.b),
            how="right",
        )
        # right has 2 rows, left 99 has no match → left side is None for row 99
        assert len(result) == 2

    def test_theta_full(self):
        """FULL θ-连接：双方不匹配行都保留，填充 None。"""
        left = Relation("L", columns=("a",), rows=[(1,), (99,)])
        right = Relation("R", columns=("b",), rows=[(1,), (100,)])
        result = left.join_theta(
            right,
            predicate=lambda l, r: (l[0] if isinstance(l, tuple) else l.a) == (r[0] if isinstance(r, tuple) else r.b),
            how="full",
        )
        # 1 matches, 99 unmatched (None on right), 100 unmatched (None on left) → 3 rows
        assert len(result) == 3

    def test_theta_full_both_empty(self):
        """双方都为空时 FULL 返回空 Relation。"""
        left = Relation("L", columns=("a",), rows=[])
        right = Relation("R", columns=("b",), rows=[])
        result = left.join_theta(
            right,
            predicate=lambda l, r: False,
            how="full",
        )
        assert len(result) == 0

    def test_theta_inner_empty_left(self):
        """θ-内连接左表为空返回空。"""
        left = Relation("L", columns=("a",), rows=[])
        right = Relation("R", columns=("b",), rows=[(1,)])
        assert len(left.join_theta(right, predicate=lambda l, r: True, how="inner")) == 0
        assert len(left.join_theta(right, predicate=lambda l, r: True, how="left")) == 0

    def test_theta_inner_empty_right(self):
        """θ-内连接右表为空：INNER=空，LEFT=左表+NULL。"""
        left = Relation("L", columns=("a",), rows=[(1,)])
        right = Relation("R", columns=("b",), rows=[])
        assert len(left.join_theta(right, predicate=lambda l, r: True, how="inner")) == 0
        left_result = left.join_theta(right, predicate=lambda l, r: True, how="left")
        assert len(left_result) == 1
        assert left_result.rows[0][1] is None


class TestThetaJoinColumnValues:
    def test_theta_column_values_correct(self):
        """MR-THETA-VAL: 左表 id 和右表 id_right 的值各自正确，不互换。"""
        left = Relation("L", columns=("id", "name"), rows=[(1, "a"), (2, "b")])
        right = Relation("R", columns=("id", "score"), rows=[(1, 100)])
        result = left.join_theta(
            right,
            predicate=lambda l, r: (l[0] if isinstance(l, tuple) else l.id) == (r[0] if isinstance(r, tuple) else r.id),
            how="inner",
        )
        id_idx = result.columns.index("id")
        id_right_idx = result.columns.index("id_right")
        name_idx = result.columns.index("name")
        score_idx = result.columns.index("score")
        row = result.rows[0]
        assert row[id_idx] == 1, f"left id should be 1, got {row[id_idx]}"
        assert row[id_right_idx] == 1, f"right id should be 1, got {row[id_right_idx]}"
        assert row[name_idx] == "a"
        assert row[score_idx] == 100

    def test_theta_three_common_columns(self):
        """三列同名时全部正确加 _right 后缀。"""
        left = Relation("L", columns=("id", "name", "val"), rows=[(1, "a", 10)])
        right = Relation("R", columns=("id", "name", "score"), rows=[(1, "b", 100)])
        result = left.join_theta(
            right,
            predicate=lambda l, r: (l[0] if isinstance(l, tuple) else l.id) == (r[0] if isinstance(r, tuple) else r.id),
            how="inner",
        )
        assert "id" in result.columns
        assert "id_right" in result.columns
        assert "name" in result.columns
        assert "name_right" in result.columns
        assert "val" in result.columns
        assert "score" in result.columns


class TestJoinCommutativity:
    def _as_set(self, rel: Relation) -> set[tuple]:
        if not rel.rows:
            return set()
        if isinstance(rel.rows[0], tuple):
            return set(rel.rows)
        return set(tuple(getattr(r, c) for c in rel.columns) for r in rel.rows)

    def test_single_key_commutes(self):
        """MR-COMMUTE-1: R⋈S == S⋈R on single key (set semantics)."""
        R = Relation("R", ("k", "v"), rows=[(1, "a"), (2, "b")])
        S = Relation("S", ("k", "w"), rows=[(1, "x"), (3, "z")])
        forward = R.join(S, on="k")
        reverse = S.join(R, on="k")
        common = tuple(sorted(set(forward.columns) & set(reverse.columns)))
        assert self._as_set(forward.project(*common)) == self._as_set(reverse.project(*common))

    def test_composite_key_commutes(self):
        """MR-COMMUTE-2: composite key R⋈S == S⋈R."""
        R = Relation("R", ("a", "b", "v"), rows=[(1, "x", 10), (2, "y", 20)])
        S = Relation("S", ("a", "b", "w"), rows=[(1, "x", 100), (2, "z", 200)])
        forward = R.join(S, on=("a", "b"))
        reverse = S.join(R, on=("a", "b"))
        common = tuple(sorted(set(forward.columns) & set(reverse.columns)))
        assert self._as_set(forward.project(*common)) == self._as_set(reverse.project(*common))

    def test_commute_with_nulls(self):
        """MR-COMMUTE-3: NULL keys — both directions agree."""
        R = Relation("R", ("k", "v"), rows=[(1, "a"), (None, "b")])
        S = Relation("S", ("k", "w"), rows=[(1, "x"), (None, "y")])
        forward = R.join(S, on="k")
        reverse = S.join(R, on="k")
        assert len(forward) == len(reverse)


class TestJoinEdgeCases:
    def test_empty_left(self):
        """空左表 JOIN 返回空。"""
        R = Relation("R", ("k", "v"), rows=[])
        S = Relation("S", ("k", "w"), rows=[(1, "x")])
        assert len(R.join(S, on="k")) == 0
        assert len(R.join_left(S, on="k")) == 0

    def test_empty_right(self):
        """空右表 INNER JOIN 返回空，LEFT JOIN 返回左表+NULL。"""
        R = Relation("R", ("k", "v"), rows=[(1, "a")])
        S = Relation("S", ("k", "w"), rows=[])
        assert len(R.join(S, on="k")) == 0
        left = R.join_left(S, on="k")
        assert len(left) == 1
        assert left.rows[0][2] is None  # w is NULL

    def test_single_row_join(self):
        """单行 JOIN 退化为标量乘积。"""
        R = Relation("R", ("k", "v"), rows=[(1, "a")])
        S = Relation("S", ("k", "w"), rows=[(1, "x")])
        result = R.join(S, on="k")
        assert len(result) == 1

    def test_single_column_relation_join(self):
        """单列 Relation JOIN。"""
        R = Relation("R", ("k",), rows=[(1,), (2,)])
        S = Relation("S", ("k",), rows=[(1,), (3,)])
        result = R.join(S, on="k")
        assert len(result) == 1
        assert result.columns == ("k",)  # both sides same single column, right side removed

    def test_multi_column_empty_left(self):
        """多列 JOIN 左表为空：INNER=空，LEFT=空，FULL=右表行+NULL。"""
        R = Relation("R", ("a", "b", "c"), rows=[])
        S = Relation("S", ("a", "b", "d"), rows=[(1, "x", 100)])
        assert len(R.join(S, on=("a", "b"))) == 0
        assert len(R.join_left(S, on=("a", "b"))) == 0
        # FULL JOIN with empty left: right rows appear with NULL left
        full = R.join_full(S, on=("a", "b"))
        assert len(full) == 1
        assert full.rows[0][2] is None  # left c is NULL

    def test_multi_column_empty_right(self):
        """多列 JOIN 右表为空：INNER=空，LEFT=左表+NULL，FULL=左表+NULL。"""
        R = Relation("R", ("a", "b", "c"), rows=[(1, "x", 10)])
        S = Relation("S", ("a", "b", "d"), rows=[])
        assert len(R.join(S, on=("a", "b"))) == 0
        left = R.join_left(S, on=("a", "b"))
        assert len(left) == 1
        assert left.rows[0][3] is None  # right side d is NULL
        full = R.join_full(S, on=("a", "b"))
        assert len(full) == 1


class TestRename:
    def test_rename_some_columns(self):
        """rename 部分列。"""
        rel = Relation("R", columns=("a", "b", "c"), rows=[(1, 2, 3)])
        renamed = rel.rename({"a": "x", "b": "y"})
        assert renamed.columns == ("x", "y", "c")
        assert renamed.rows[0] == (1, 2, 3)

    def test_rename_does_not_mutate_original(self):
        """rename 不修改原 Relation。"""
        rel = Relation("R", columns=("a",), rows=[(1,)])
        _ = rel.rename({"a": "x"})
        assert rel.columns == ("a",)


class TestExtractEquiPairs:
    """测试 QueryExecutor._extract_equi_pairs。"""

    def test_simple_eq(self):
        from parallelines.engine.query_ast import BinaryPred, ColumnRef
        pred = BinaryPred("eq", ColumnRef("a"), ColumnRef("b"))
        from parallelines.engine.query_executor import QueryExecutor
        pairs = QueryExecutor._extract_equi_pairs(pred)
        assert pairs == [("a", "b")]

    def test_compound_and(self):
        from parallelines.engine.query_ast import BinaryPred, ColumnRef, CompoundPred
        pred = CompoundPred("and", [
            BinaryPred("eq", ColumnRef("a"), ColumnRef("b")),
            BinaryPred("eq", ColumnRef("c"), ColumnRef("d")),
        ])
        from parallelines.engine.query_executor import QueryExecutor
        pairs = QueryExecutor._extract_equi_pairs(pred)
        assert pairs == [("a", "b"), ("c", "d")]

    def test_or_returns_empty(self):
        from parallelines.engine.query_ast import BinaryPred, ColumnRef, CompoundPred
        pred = CompoundPred("or", [
            BinaryPred("eq", ColumnRef("a"), ColumnRef("b")),
            BinaryPred("eq", ColumnRef("c"), ColumnRef("d")),
        ])
        from parallelines.engine.query_executor import QueryExecutor
        pairs = QueryExecutor._extract_equi_pairs(pred)
        assert pairs == []

    def test_eq_with_literal_returns_empty(self):
        """eq 但右端是 Literal 而不是 ColumnRef → 不视为等值列对。"""
        from parallelines.engine.query_ast import BinaryPred, ColumnRef, Literal
        pred = BinaryPred("eq", ColumnRef("a"), Literal(5))
        from parallelines.engine.query_executor import QueryExecutor
        pairs = QueryExecutor._extract_equi_pairs(pred)
        assert pairs == []
