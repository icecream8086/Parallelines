"""Layer 1 — 独立 Oracle 属性测试：DeadFileAnalyzer。

用朴素不动点算法作 Oracle，与 DeadFileAnalyzer 的 BFS 实现对比。
核心原则：Oracle 必须用与实现完全不同的算法。
"""
from __future__ import annotations

import networkx as nx
import pytest

# SUT
from parallelines.analysis.dead_file import DeadFileAnalyzer
from parallelines.engine.store import ResultStore
from parallelines.graph.deps import DependencyGraph
from parallelines.types import FileNode
from parallelines.vfs.filesystem import VirtualFileSystem

_HYPOTHESIS_AVAILABLE: bool = False
try:
    from hypothesis import given, settings, strategies as st, HealthCheck

    _HYPOTHESIS_AVAILABLE = True
except ImportError:

    def given(x=None, **kw):  # type: ignore[misc]
        return lambda f: f

    def settings(x=None, **kw):  # type: ignore[misc]
        return lambda f: f

    st = None  # type: ignore[assignment]


def _naive_reachable(graph: nx.DiGraph, entries: set[str]) -> set[str]:
    """最朴素的传递闭包：重复遍历所有边直到不动点。

    时间复杂度 O(V·E)，空间 O(V)。比 BFS 慢 100 倍，
    但实现只有 6 行，肉眼可验证正确性。
    """
    reachable = set(entries)
    changed = True
    while changed:
        changed = False
        for src, dst in graph.edges():
            if src in reachable and dst not in reachable:
                reachable.add(dst)
                changed = True
    return reachable


@pytest.mark.skipif(
    not _HYPOTHESIS_AVAILABLE, reason="hypothesis not installed"
)
class TestDeadFileNaiveOracle:
    """用朴素不动点 Oracle 验证 DeadFileAnalyzer 结果。"""

    @staticmethod
    def _build_vfs_and_graph(
        paths: list[str],
        edges: list[tuple[str, str]],
    ) -> tuple[VirtualFileSystem, DependencyGraph]:
        vfs = VirtualFileSystem()
        for i, path in enumerate(paths):
            vfs.add_file(
                FileNode(
                    virtual_path=path,
                    source_type="test",
                    source_name=f"src_{i}",
                    priority=i,
                    is_enabled=True,
                )
            )
        vfs.resolve()

        graph = DependencyGraph()
        for path in paths:
            graph.add_node(path)
        graph.add_edges(edges)
        return vfs, graph

    # ── 核心属性：朴素 Oracle 必须与 DeadFileAnalyzer 一致 ──────────────

    @given(
        nodes=st.sets(
            st.text(min_size=0, max_size=16).filter(lambda s: "\\" not in s),
            min_size=1,
            max_size=30,
        ),
        edges=st.lists(
            st.tuples(
                st.text(min_size=0, max_size=16),
                st.text(min_size=0, max_size=16),
            ),
            min_size=0,
            max_size=100,
        ),
    )
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_dead_matches_naive_oracle(
        self,
        nodes: set[str],
        edges: list[tuple[str, str]],
    ) -> None:
        """DeadFileAnalyzer 标记的 dead 集合 = 朴素传递闭包求出的不可达集合。"""
        # 过滤边：只保留两端都在节点集中的边
        valid_edges = [(s, t) for s, t in edges if s in nodes and t in nodes]
        # 选 1-5 个入口点
        node_list = sorted(nodes)
        entry_count = max(1, len(node_list) // 6)
        entries = set(node_list[:entry_count])

        vfs, graph = self._build_vfs_and_graph(node_list, valid_edges)

        analyzer = DeadFileAnalyzer(entry_points=entries)
        store = ResultStore.from_analysis(vfs, graph, [analyzer], entry_points=entries)
        assert store.files is not None

        actual_dead = {r.virtual_path for r in store.files.rows if r.is_dead}

        # 独立 Oracle：朴素不动点
        reachable = _naive_reachable(graph.graph, entries)
        expected_dead = {n for n in nodes if n not in reachable}

        assert actual_dead == expected_dead, (
            f"DeadFileAnalyzer 与朴素 Oracle 不一致\n"
            f"  预期 dead: {sorted(expected_dead)}\n"
            f"  实际 dead: {sorted(actual_dead)}"
        )

    # ── 边界：空图 ──────────────────────────────────────────────────────

    @given(nodes=st.sets(st.text(min_size=0, max_size=8), min_size=1, max_size=10))
    @settings(max_examples=50)
    def test_empty_graph_no_edges(self, nodes: set[str]) -> None:
        """无边的图，只有入口点可达，其他全是 dead。"""
        node_list = sorted(nodes)
        entries = {node_list[0]}

        vfs, graph = self._build_vfs_and_graph(node_list, [])
        analyzer = DeadFileAnalyzer(entry_points=entries)
        store = ResultStore.from_analysis(vfs, graph, [analyzer], entry_points=entries)
        assert store.files is not None

        actual_dead = {r.virtual_path for r in store.files.rows if r.is_dead}
        expected_dead = set(node_list[1:])

        assert actual_dead == expected_dead, (
            f"无边图：预期 {sorted(expected_dead)} dead, "
            f"实际 {sorted(actual_dead)}"
        )

    # ── 边界：全连接图（无 dead 文件）──────────────────────────────────────

    @given(nodes=st.sets(st.text(min_size=0, max_size=8), min_size=2, max_size=8))
    @settings(max_examples=50)
    def test_fully_connected_no_dead(self, nodes: set[str]) -> None:
        """全连接图 = 所有文件都可达 = 无 dead 文件。"""
        node_list = sorted(nodes)
        entries = {node_list[0]}
        # 完全有向图：从 entry 到所有其他节点
        edges = [(node_list[0], n) for n in node_list[1:]]

        vfs, graph = self._build_vfs_and_graph(node_list, edges)
        analyzer = DeadFileAnalyzer(entry_points=entries)
        store = ResultStore.from_analysis(vfs, graph, [analyzer], entry_points=entries)
        assert store.files is not None

        actual_dead = {r.virtual_path for r in store.files.rows if r.is_dead}
        assert actual_dead == set(), (
            f"全连接图预期无 dead，实际有 {sorted(actual_dead)}"
        )

    # ── 反例搜索：大图 + 稀疏边 → 容易遗漏可达性 ────────────────────────────

    @given(
        nodes=st.sets(
            st.text(min_size=0, max_size=8), min_size=5, max_size=20
        ),
        edges=st.lists(
            st.tuples(
                st.sampled_from(sorted(["A", "B", "C", "D", "E", "F", "G", "H"])),
                st.sampled_from(sorted(["A", "B", "C", "D", "E", "F", "G", "H"])),
            ),
            min_size=0,
            max_size=50,
        ),
    )
    @settings(max_examples=200)
    def test_redundant_edges_dont_change_dead_set(
        self, nodes: set[str], edges: list[tuple[str, str]]
    ) -> None:
        """添加冗余边（已可达路径的快捷方式）不会改变 dead 集合。

        蜕变性：添加冗余边 → dead 集必定不变或缩小，绝不可能扩大。
        这个属性如果被违反，说明分析器把冗余边当成了新依赖，属于 bug。
        """
        node_list = sorted(nodes)
        entries = {node_list[0]}

        vfs, graph = self._build_vfs_and_graph(node_list, [])
        analyzer = DeadFileAnalyzer(entry_points=entries)
        store = ResultStore.from_analysis(vfs, graph, [analyzer], entry_points=entries)
        assert store.files is not None
        dead_no_edges = {r.virtual_path for r in store.files.rows if r.is_dead}

        # 添加边
        valid_edges = [(s, t) for s, t in edges if s in nodes and t in nodes]
        vfs2, graph2 = self._build_vfs_and_graph(node_list, valid_edges)
        analyzer2 = DeadFileAnalyzer(entry_points=entries)
        store2 = ResultStore.from_analysis(
            vfs2, graph2, [analyzer2], entry_points=entries
        )
        assert store2.files is not None
        dead_with_edges = {r.virtual_path for r in store2.files.rows if r.is_dead}

        # 核心断言：加边后 dead 集最多缩小，绝不扩大
        assert dead_with_edges <= dead_no_edges, (
            f"加边后 dead 集扩大了！这不可能是正确的。\n"
            f"  无边 dead: {sorted(dead_no_edges)}\n"
            f"  加边 dead: {sorted(dead_with_edges)}"
        )
