"""Layer 2 — 蜕变测试：DependencyGraph。

图变换后可达性/影响面按预期变化的蜕变关系。
"""
from __future__ import annotations

import icontract
import pytest

from parallelines.graph.deps import DependencyGraph


class TestGraphMetamorphic:
    """DependencyGraph 蜕变关系。"""

    # ── 蜕变 1：加边 → 可达集扩大或不变 ──────────────────────────────────

    def test_adding_edge_increases_or_keeps_reachable(self) -> None:
        """添加边 → 从入口点的可达集只会增大或不变，绝不缩小。"""
        g = DependencyGraph()
        for n in ["A", "B", "C", "D"]:
            g.add_node(n)
        g.add_edges([("A", "B")])
        reachable_before = g.get_descendants("A")

        g.add_edges([("B", "C")])
        reachable_after = g.get_descendants("A")

        # 加边后可达集一定是超集（包含原有所有可达节点）
        assert reachable_before.issubset(reachable_after), (
            f"加边后可达缩小了：before={reachable_before}, after={reachable_after}"
        )
        assert "C" in reachable_after, "加边后 C 应该可达"

    # ── 蜕变 2：反转所有边 → descendants 变 ancestors ──────────────────

    def test_edge_reversal_swaps_ancestors_descendants(self) -> None:
        """反转所有边 → descendants(X) == 原图的 ancestors(X)。"""
        g = DependencyGraph()
        for n in ["A", "B", "C", "D"]:
            g.add_node(n)
        g.add_edges([("A", "B"), ("B", "C"), ("A", "D")])

        original_desc = g.get_descendants("A")
        original_anc = g.get_ancestors("C")

        # 建反向图：新图节点相同，边方向相反
        g_rev = DependencyGraph()
        for n in ["A", "B", "C", "D"]:
            g_rev.add_node(n)
        g_rev.add_edges([("B", "A"), ("C", "B"), ("D", "A")])

        rev_desc_from_c = g_rev.get_descendants("C")

        # 原图中 C 的 ancestors = 反向图中从 C 的 descendants
        assert rev_desc_from_c == original_anc, (
            f"反转边不匹配：原图 ancestors(C)={original_anc}, "
            f"反向图 descendants(C)={rev_desc_from_c}"
        )

    # ── 蜕变 3：删除"非桥接"边 → 可达性不变 ──────────────────────────────

    def test_remove_redundant_edge_preserves_reachability(self) -> None:
        """删除冗余边（已在其他路径上可达的目标）→ 可达集不变。"""
        g = DependencyGraph()
        for n in ["A", "B", "C", "D"]:
            g.add_node(n)
        # A→B→C 且 A→C（C 已通过 A→B→C 可达，A→C 是冗余边）
        g.add_edges([("A", "B"), ("B", "C"), ("A", "C")])

        reachable_with_all = g.get_descendants("A")

        # 删除 A→C 冗余边
        g2 = DependencyGraph()
        for n in ["A", "B", "C", "D"]:
            g2.add_node(n)
        g2.add_edges([("A", "B"), ("B", "C")])

        reachable_without = g2.get_descendants("A")

        assert reachable_without == reachable_with_all, (
            f"删除冗余边后可达集变了：{reachable_with_all} → {reachable_without}"
        )

    # ── 蜕变 4：freeze() 后不能修改 ──────────────────────────────────────

    def test_frozen_graph_rejects_mutations(self) -> None:
        """freeze() 后调用 add_edge/add_node 必须抛异常。

        可能抛出 icontract.ViolationError（契约检查先于方法体）。
        """
        g = DependencyGraph()
        g.add_node("A")
        g.freeze()

        with pytest.raises((RuntimeError, icontract.errors.ViolationError)):
            g.add_node("B")

        with pytest.raises((RuntimeError, icontract.errors.ViolationError)):
            g.add_edges([("A", "B")])

    # ── 蜕变 5：可达性的传递性（三角关系）──────────────────────────────────

    def test_reachability_transitive(self) -> None:
        """若 A→B 且 B→C，则 A→C（传递性）。"""
        g = DependencyGraph()
        for n in ["A", "B", "C"]:
            g.add_node(n)
        g.add_edges([("A", "B"), ("B", "C")])

        assert g.has_path("A", "C"), "传递性违反：A→B→C 但 A 不可达 C"

    # ── 蜕变 6：空集合的 reachable_from_all ───────────────────────────────

    def test_empty_sources_reachable(self) -> None:
        """空入口点集合 → reachable_from_all 返回空集。"""
        g = DependencyGraph()
        for n in ["A", "B"]:
            g.add_node(n)
        g.add_edges([("A", "B")])

        result = g.reachable_from_all(set())
        assert result == set(), f"空入口点应返回空集，实际返回 {result}"

    # ── 蜕变 7：不存在的源被静默跳过 ──────────────────────────────────────

    def test_nonexistent_source_skipped(self) -> None:
        """不在图中的入口点被静默跳过，不应抛异常。"""
        g = DependencyGraph()
        g.add_node("A")

        # 这个调用不应该抛异常
        result = g.reachable_from_all({"NONEXISTENT"})
        assert result == set(), f"不存在的源应返回空，实际 {result}"

    # ── 蜕变 8：循环不破坏可达性 ──────────────────────────────────────────

    def test_cycle_self_reachable(self) -> None:
        """在循环中，每个节点都可达其他节点。"""
        g = DependencyGraph()
        g.add_node("A")
        g.add_node("B")
        g.add_node("C")
        g.add_edges([("A", "B"), ("B", "C"), ("C", "A")])

        assert g.has_path("A", "C")
        assert g.has_path("B", "A")
        assert g.has_path("C", "B")

        # 从 A 出发，B 和 C 都可达
        desc = g.get_descendants("A")
        assert "B" in desc
        assert "C" in desc
