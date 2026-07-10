"""Layer 3 — 差分测试：图算法。

同一个规约的多个独立实现，输出必须一致。
输出不一致 → 至少有一个实现有 bug。
"""
from __future__ import annotations

import pytest

from parallelines.graph.deps import DependencyGraph
from parallelines.vfs.filesystem import VirtualFileSystem
from parallelines.types import FileNode

_HYPOTHESIS_AVAILABLE: bool = False
try:
    from hypothesis import given, settings, strategies as st, HealthCheck
    import networkx as nx

    _HYPOTHESIS_AVAILABLE = True
except ImportError:

    def given(x=None, **kw):  # type: ignore[misc]
        return lambda f: f

    def settings(x=None, **kw):  # type: ignore[misc]
        return lambda f: f

    st = None  # type: ignore[assignment]


def _naive_descendants(graph: nx.DiGraph, sources: set[str]) -> set[str]:
    """朴素不动点 — 只返回从 sources 可达的后代节点（不含 sources 自身）。

    与 nx.descendants 语义一致，用于差分比对。
    """
    if not sources:
        return set()
    frontier = set(sources)
    descendants: set[str] = set()
    changed = True
    while changed:
        changed = False
        for src, dst in graph.edges():
            if src in frontier and dst not in descendants and dst not in sources:
                descendants.add(dst)
                frontier.add(dst)
                changed = True
    return descendants


def _bfs_reachable(graph: nx.DiGraph, entries: set[str]) -> set[str]:
    """手写 BFS — 独立实现 B（与 _naive_reachable 和 nx.descendants 都不同）。"""
    reachable: set[str] = set()
    queue = list(entries)
    visited = set(entries)
    while queue:
        current = queue.pop(0)
        for src, dst in graph.edges():
            if src == current and dst not in visited:
                visited.add(dst)
                reachable.add(dst)
                queue.append(dst)
    return reachable


@pytest.mark.skipif(
    not _HYPOTHESIS_AVAILABLE, reason="hypothesis not installed"
)
class TestReachabilityDifferential:
    """三个独立可达性实现必须输出相同结果。"""

    @given(
        nodes=st.sets(
            st.text(min_size=0, max_size=12), min_size=0, max_size=20
        ),
        edges=st.lists(
            st.tuples(
                st.text(min_size=0, max_size=12),
                st.text(min_size=0, max_size=12),
            ),
            min_size=0,
            max_size=50,
        ),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_three_implementations_agree(
        self,
        nodes: set[str],
        edges: list[tuple[str, str]],
    ) -> None:
        """三个独立可达性实现必须输出相同结果。"""
        node_list = sorted(nodes)
        if not node_list:
            return
        valid_edges = [(s, t) for s, t in edges if s in nodes and t in nodes]

        # 构建 DependencyGraph
        graph = DependencyGraph()
        for n in node_list:
            graph.add_node(n)
        graph.add_edges(valid_edges)

        entries = {node_list[0]}

        # 实现 1: graph.reachable_from_all() — 被测方法（基于 nx.descendants）
        result1 = graph.reachable_from_all(entries)

        # 实现 2: 朴素不动点（只返回后代）
        result2 = _naive_descendants(graph.graph, entries)

        # 实现 3: 手写 BFS
        result3 = _bfs_reachable(graph.graph, entries)

        assert result1 == result2, (
            f"被测实现与朴素不动点不一致\n"
            f"  reachable_from_all: {sorted(result1)}\n"
            f"  朴素不动点:        {sorted(result2)}"
        )
        assert result2 == result3, (
            f"朴素不动点与 BFS 不一致\n"
            f"  朴素不动点: {sorted(result2)}\n"
            f"  BFS:         {sorted(result3)}"
        )


@pytest.mark.skipif(
    not _HYPOTHESIS_AVAILABLE, reason="hypothesis not installed"
)
class TestReachabilityEdgeCases:
    """差分测试的边界条件。"""

    def test_empty_graph(self) -> None:
        """空图 → 所有实现返回空集。"""
        graph = DependencyGraph()
        entries = set()

        r1 = graph.reachable_from_all(entries)
        r2 = _naive_descendants(graph.graph, entries)
        r3 = _bfs_reachable(graph.graph, entries)

        assert r1 == r2 == r3 == set()

    def test_self_loop(self) -> None:
        """自环 → 从入口点出发没有"其他"可达节点。"""
        graph = DependencyGraph()
        graph.add_node("A")
        graph.add_edges([("A", "A")])

        entries = {"A"}
        r1 = graph.reachable_from_all(entries)
        r2 = _naive_descendants(graph.graph, entries)
        r3 = _bfs_reachable(graph.graph, entries)

        # nx.descendants 不包含节点自身，所以都是 set()
        assert r1 == r2 == r3 == set()

    def test_disconnected_components(self) -> None:
        """多连通分量 → 只返回入口点所在分量的后代节点。"""
        graph = DependencyGraph()
        for n in ["A", "B", "C", "X", "Y", "Z"]:
            graph.add_node(n)
        # 分量 1: A→B→C
        graph.add_edges([("A", "B"), ("B", "C")])
        # 分量 2: X→Y→Z
        graph.add_edges([("X", "Y"), ("Y", "Z")])

        entries = {"A"}
        r1 = graph.reachable_from_all(entries)
        r2 = _naive_descendants(graph.graph, entries)
        r3 = _bfs_reachable(graph.graph, entries)

        assert r1 == r2 == r3 == {"B", "C"}, (
            f"应有 B,C，实际 r1={r1}, r2={r2}, r3={r3}"
        )

    def test_dead_file_analyzer_vs_direct_reachability(self) -> None:
        """差分：DeadFileAnalyzer 的 dead 判定 = 直接可达性计算。

        这个测试如果失败，说明 DeadFileAnalyzer 有不一致的处理逻辑。
        """
        from parallelines.analysis.dead_file import DeadFileAnalyzer
        from parallelines.engine.store import ResultStore

        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode("entry.bsp", "test", "src1", priority=10, is_enabled=True)
        )
        vfs.add_file(
            FileNode("wall.vmt", "test", "src1", priority=10, is_enabled=True)
        )
        vfs.add_file(
            FileNode("floor.vtf", "test", "src2", priority=5, is_enabled=True)
        )
        vfs.resolve()

        g = DependencyGraph()
        for n in ["entry.bsp", "wall.vmt", "floor.vtf"]:
            g.add_node(n)
        g.add_edges([("entry.bsp", "wall.vmt")])

        entries = {"entry.bsp"}

        # 方法 A：DeadFileAnalyzer
        analyzer = DeadFileAnalyzer(entry_points=entries)
        store = ResultStore.from_analysis(vfs, g, [analyzer], entry_points=entries)
        assert store.files is not None
        dead_by_analyzer = {
            r.virtual_path for r in store.files.rows if r.is_dead
        }

        # 方法 B：直接可达性计算
        reachable = g.reachable_from_all(entries)
        live = entries | reachable
        active_paths = {n.virtual_path for n in vfs.get_all_active()}
        dead_by_reachability = {p for p in active_paths if p not in live}

        assert dead_by_analyzer == dead_by_reachability, (
            f"差分测试失败：\n"
            f"  Analyzer: {sorted(dead_by_analyzer)}\n"
            f"  可达性:   {sorted(dead_by_reachability)}"
        )
