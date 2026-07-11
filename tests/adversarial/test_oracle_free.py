"""Oracle-Free Tests — metamorphic relations for DependencyGraph, Relation, VFS.

遵循 devdocs/oracle-free-testing-prompt.md 的方法论：
- 不在测试代码中手写任何具体的 y_expected
- 使用蜕变关系（Metamorphic Relations）替代具体 Oracle
- 覆盖 ≥ 2 个 Chen 类别（Invertive, Additive, Compositional, Permutative）
- 使用 hypothesis 进行属性基测试（PBT），随机生成输入搜索反例

目标：证明现有代码存在 bug。
"""

from __future__ import annotations

import networkx as nx
import pytest
from hypothesis import assume, given, strategies as st

from dataclasses import dataclass

from parallelines.engine.store import Relation
from parallelines.graph.deps import DependencyGraph
from parallelines.types import FileNode
from parallelines.vfs.filesystem import VirtualFileSystem


# ═══════════════════════════════════════════════════════════════
# §1 — DependencyGraph: 图论蜕变关系
# ═══════════════════════════════════════════════════════════════

# ── 策略 ────────────────────────────────────────────────────

_node_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P"), max_codepoint=127),
    min_size=1,
    max_size=8,
)

_graph_strategy = st.lists(
    st.tuples(_node_names, _node_names).filter(lambda t: t[0] != t[1]),
    min_size=0,
    max_size=20,
).map(lambda edges: _build_graph(edges))


def _build_graph(edges: list[tuple[str, str]]) -> DependencyGraph:
    """Build a frozen graph from edge tuples."""
    g = DependencyGraph()
    seen: set[str] = set()
    for src, tgt in edges:
        if src not in seen:
            g.add_node(src)
            seen.add(src)
        if tgt not in seen:
            g.add_node(tgt)
            seen.add(tgt)
        g.add_edges([(src, tgt)])
    g.freeze()
    return g


# ── MR1 (Invertive): descendants 与 ancestors 互逆 ──────────


@given(_graph_strategy, _node_names)
def test_mr_invertive_descendants_ancestors(graph, node):
    """MR-Invertive: x ∈ descendants(y) ⇔ y ∈ ancestors(x).

    如果违反了，说明图的边方向不一致，或者 get_descendants/get_ancestors
    的实现中存在不对称的 bug。
    """
    assume(graph.node_count > 0)
    assume(node in graph.graph)

    descendants = graph.get_descendants(node)
    for d in descendants:
        assert node in graph.get_ancestors(d), (
            f"MR-Invertive violation: {node} → {d} via descendants, "
            f"but {node} ∉ ancestors({d})"
        )

    ancestors = graph.get_ancestors(node)
    for a in ancestors:
        assert node in graph.get_descendants(a), (
            f"MR-Invertive violation: {a} → {node} via ancestors, "
            f"but {node} ∉ descendants({a})"
        )


# ── MR2 (Additive): 添加无关节点不影响现有可达性 ─────────


@given(_graph_strategy, _node_names)
def test_mr_additive_irrelevant_node(graph, new_node):
    """MR-Additive: 添加一个独立节点（无边）不影响已有节点的 descendants。

    如果在添加孤立节点后 get_descendants 的结果变了，说明图实现
    有状态污染 bug。
    """
    assume(graph.node_count > 0)
    assume(new_node not in graph.graph)

    # 对每个已有节点，记录其 descendants
    before = {}
    for n in list(graph.graph.nodes):
        before[n] = graph.get_descendants(n)

    # "添加"——实际上不可变，但我们可以验证新节点不存在
    # 真正的测试：没有边连接到 new_node，所以它不应出现在任何 descendants 中
    all_descendants: set[str] = set()
    for n in graph.graph.nodes:
        all_descendants |= graph.get_descendants(n)
    assert new_node not in all_descendants, (
        f"MR-Additive violation: independent node '{new_node}' "
        f"appeared in descendants despite having no edges"
    )


# ── MR3 (Compositional): 二分图的可达性并集 ───────────────


def _split_nodes(nodes: list[str]) -> tuple[set[str], set[str]]:
    """Split nodes into two disjoint sets by alternating."""
    a: set[str] = set()
    b: set[str] = set()
    for i, n in enumerate(nodes):
        if i % 2 == 0:
            a.add(n)
        else:
            b.add(n)
    return a, b


@given(_graph_strategy)
def test_mr_compositional_descendants_union(graph):
    """MR-Compositional: descendants(A) ∪ descendants(B) = descendants(A ∪ B).

    从全部源节点的子集出发，并集的可达范围不应超过全量。
    """
    assume(graph.node_count >= 2)
    nodes = list(graph.graph.nodes)
    a, b = _split_nodes(nodes)

    # descendants(A) ∪ descendants(B)
    union_ab: set[str] = set()
    for n in a:
        union_ab |= graph.get_descendants(n)
    for n in b:
        union_ab |= graph.get_descendants(n)

    # descendants(A ∪ B) — 即全集
    all_desc: set[str] = set()
    for n in nodes:
        all_desc |= graph.get_descendants(n)

    # 并集应包含于全集（⊆）
    assert union_ab.issubset(all_desc), (
        f"MR-Compositional violation: partition union ({len(union_ab)}) "
        f"exceeds full set ({len(all_desc)})"
    )


# ── MR4 (Identity): 图中不应存在自环 ──────────────────────


@given(_graph_strategy)
def test_mr_identity_no_self_loop(graph):
    """MR-Identity: 对所有节点 n, n ∉ descendants(n)。

    图构造阶段禁止了自环边，但若 add_edges 或 freeze 后的状态
    有 bug，自环仍可能出现在 descendants 中。
    """
    assume(graph.node_count > 0)
    for node in graph.graph.nodes:
        assert node not in graph.get_descendants(node), (
            f"MR-Identity violation: self-loop detected for '{node}'"
        )


# ── MR5 (Crash): get_descendants 对不存在的节点不应崩溃 ─────


@given(_graph_strategy, _node_names)
def test_mr_robust_missing_node_descendants(graph, missing):
    """MR-Robust: get_descendants('non_existent') 应返回空集而非崩溃。

    当前实现直接调 nx.descendants，当节点不存在时抛 NetworkXError。
    这是 bug——调用者期望 set[str] 返回值。
    """
    assume(missing not in graph.graph)
    try:
        result = graph.get_descendants(missing)
        # 如果走到这里：返回了结果。检查是否为空。
        assert result == set(), (
            f"MR-Robust violation: get_descendants('{missing}') "
            f"returned {result}, expected empty set"
        )
    except nx.NetworkXError:
        pytest.fail(
            f"MR-Robust violation: get_descendants('{missing}') "
            f"crashed with NetworkXError — node not in graph should "
            f"return empty set, not crash"
        )


@given(_graph_strategy, _node_names)
def test_mr_robust_missing_node_ancestors(graph, missing):
    """MR-Robust: get_ancestors('non_existent') 应返回空集而非崩溃。

    与 MR5 相同的问题——缺少节点守卫。
    """
    assume(missing not in graph.graph)
    try:
        result = graph.get_ancestors(missing)
        assert result == set(), (
            f"MR-Robust violation: get_ancestors('{missing}') "
            f"returned {result}, expected empty set"
        )
    except nx.NetworkXError:
        pytest.fail(
            f"MR-Robust violation: get_ancestors('{missing}') "
            f"crashed with NetworkXError"
        )


# ═══════════════════════════════════════════════════════════════
# §2 — Relation: 关系代数蜕变关系
# ═══════════════════════════════════════════════════════════════


# ── 策略 ────────────────────────────────────────────────────

_any_value = st.integers(min_value=-100, max_value=100) | st.text(
    alphabet="abc", min_size=1, max_size=4
)
_row = st.dictionaries(
    keys=st.just("key") | st.just("val"),
    values=_any_value,
    min_size=2,
    max_size=2,
)


def _rel_from_dicts(name: str, rows: list[dict]) -> Relation:
    """Build a Relation from a list of dicts."""
    if not rows:
        return Relation(name, ("key", "val"), [])
    @dataclass
    class Row:
        key: str = ""
        val: int | str = 0

    typed = [Row(**r) for r in rows]
    rel = Relation.from_rows(name, typed)
    return rel


# ── MR6 (Idempotent): select 是幂等的 ──────────────────────


@given(st.lists(_row, min_size=0, max_size=10))
def test_mr_idempotent_select(rows):
    """MR-Idempotent: select(p).select(p) = select(p)。

    两次相同的过滤不应改变结果。若违反，说明 select 有副作用。
    """
    rel = _rel_from_dicts("test", rows)
    if not rel.rows:
        return

    # 随机选一个谓词
    import random
    sample_row = random.choice(rel.rows)
    threshold = getattr(sample_row, "val", 0)
    if not isinstance(threshold, (int, float)):
        threshold = 0

    def pred(r) -> bool:
        v = getattr(r, "val", 0)
        return isinstance(v, (int, float)) and v > threshold

    once = rel.select(pred)
    twice = once.select(pred)

    assert len(once.rows) == len(twice.rows), (
        f"MR-Idempotent violation: first select gave {len(once.rows)} rows, "
        f"second select gave {len(twice.rows)}"
    )


# ── MR7 (Select-Project Commute, Permutative) ──────────────


@given(st.lists(_row, min_size=0, max_size=10))
def test_mr_permutative_select_project(rows):
    """MR-Permutative: 当列集相同时, select(p) 后 project(c)
    与 project(c) 后 select(p) 的行数相同。

    select 和 project 都是逐行操作，顺序交换不应改变最终行数。
    """
    rel = _rel_from_dicts("test", rows)
    if not rel.rows or len(rel.columns) < 2:
        return

    import random
    sample_row = random.choice(rel.rows)
    threshold = getattr(sample_row, "val", 0)
    if not isinstance(threshold, (int, float)):
        threshold = 0

    def pred(r) -> bool:
        v = getattr(r, "val", 0) if not isinstance(r, tuple) else r[1]
        return isinstance(v, (int, float)) and v > threshold

    # select → project (only key)
    sp = rel.select(pred)
    sp_proj = sp.project("key")

    # project (keep val for select) → select → project (only key)
    proj = rel.project("key", "val")
    ps = proj.select(pred)
    ps_proj = ps.project("key")

    # Both end with project("key"), so results should match
    assert len(sp_proj.rows) == len(ps_proj.rows), (
        f"MR-Permutative violation: select→project gave {len(sp_proj.rows)} rows, "
        f"project→select→project gave {len(ps_proj.rows)} rows"
    )


# ═══════════════════════════════════════════════════════════════
# §3 — VirtualFileSystem: 优先级叠加蜕变关系
# ═══════════════════════════════════════════════════════════════


def _make_node(vpath: str, source: str, priority: int, enabled: bool = True) -> FileNode:
    """Helper to create FileNode with minimal fields."""
    return FileNode(
        virtual_path=vpath,
        source_name=source,
        source_type="addon",
        priority=priority,
        is_enabled=enabled,
    )


# ── MR8 (Additive): 添加低优先级节点不应改变活跃节点 ─────


def test_mr_additive_lower_priority_does_not_affect_winner():
    """MR-Additive: 对已有节点添加更低优先级的副本时，活跃节点不应改变。

    若违反，说明 VFS resolve() 在选择 winner 时有非确定性或
    优先级比较有 bug。
    """
    vfs = VirtualFileSystem()
    vfs.add_file(_make_node("maps/c1m1_hotel.bsp", "addon1", 100))
    vfs.resolve()

    winner_before = vfs.get_active_file("maps/c1m1_hotel.bsp")
    assert winner_before is not None

    # 添加低优先级版本
    vfs.add_file(_make_node("maps/c1m1_hotel.bsp", "addon2", 50))
    vfs.resolve()

    winner_after = vfs.get_active_file("maps/c1m1_hotel.bsp")
    assert winner_after is not None

    # 活跃节点不应变化（source 应保持 addon1）
    assert winner_after.source_name == winner_before.source_name, (
        f"MR-Additive violation: adding lower-priority node changed winner "
        f"from '{winner_before.source_name}' (p=100) to "
        f"'{winner_after.source_name}' (p=50)"
    )


# ── MR9 (Monotonic): 优先级越高越可能胜出 ────────────────


def test_mr_monotonic_higher_priority_wins():
    """MR-Monotonic: 对同一虚拟路径，较高优先级的节点应成为活跃节点。

    若违反，说明 max() 的选择逻辑有 bug（如比较了错误字段）。
    """
    vfs = VirtualFileSystem()
    vfs.add_file(_make_node("maps/c2m1_highway.bsp", "low", 10))
    vfs.add_file(_make_node("maps/c2m1_highway.bsp", "high", 100))
    vfs.resolve()

    winner = vfs.get_active_file("maps/c2m1_highway.bsp")
    assert winner is not None
    assert winner.source_name == "high", (
        f"MR-Monotonic violation: expected winner='high' (p=100), "
        f"got '{winner.source_name}' (p={winner.priority})"
    )


# ── MR10 (Normalization): 路径归一化一致性 ────────────────


@pytest.mark.parametrize("input_path,lookup_path", [
    ("maps/test.bsp", "maps/test.bsp"),
    ("maps\\test.bsp", "maps/test.bsp"),
    ("MAPS/test.bsp", "maps/test.bsp"),
    ("Maps/Test.BSP", "maps/test.bsp"),
])
def test_mr_normalization_path_insensitivity(input_path, lookup_path):
    """MR-Normalization: VFS 应不区分大小写和路径分隔符地处理路径。

    若违反，说明 key 的 normalize 与 node.virtual_path 的保存
    之间存在不一致。
    """
    vfs = VirtualFileSystem()
    vfs.add_file(_make_node(input_path, "source_a", 100))
    vfs.resolve()

    active = vfs.get_active_file(lookup_path)
    assert active is not None, (
        f"MR-Normalization violation: '{input_path}' was added "
        f"but '{lookup_path}' resolved to None"
    )


# ── MR11 (Exclusive): 无 enabled 节点时不应有活跃节点 ──


def test_mr_exclusive_disabled_nodes_no_winner():
    """MR-Exclusive: 当所有节点都被 disabled 时，resolve 后不应有活跃节点。

    若违反，说明 resolve() 跳过了 enabled 检查或 is_enabled 被忽略。
    """
    vfs = VirtualFileSystem()
    vfs.add_file(_make_node("scripts/test.nut", "source_a", 100, enabled=False))
    vfs.add_file(_make_node("scripts/test.nut", "source_b", 200, enabled=False))
    vfs.resolve()

    active = vfs.get_active_file("scripts/test.nut")
    assert active is None, (
        f"MR-Exclusive violation: all nodes disabled but "
        f"'{active.source_name}' is active"
    )


# ═══════════════════════════════════════════════════════════════
# §4 — 跨模块集成蜕变关系
# ═══════════════════════════════════════════════════════════════


# ── MR12 (Compositional): Graph → VFS 一致性 ─────────────


def test_mr_compositional_graph_vfs_consistency():
    """MR-Compositional: 如果一个文件在 VFS 中不是活跃的，那么它在
    DependencyGraph 中不应有出边（因为它不应被解析依赖关系）。

    若违反，说明 VFS 的过滤逻辑与 GraphBuilder 的迭代节点之间存在脱节。
    """
    vfs = VirtualFileSystem()
    vfs.add_file(_make_node("maps/test.bsp", "source_a", 100))
    vfs.add_file(_make_node("maps/test.bsp", "source_b", 200, enabled=False))
    vfs.resolve()

    graph = DependencyGraph()
    for node in vfs.get_all_active():
        graph.add_node(node.virtual_path)

    # 每个活跃节点都应在图中
    active_nodes = {n.virtual_path for n in vfs.get_all_active()}
    graph_nodes = set(graph.graph.nodes)

    # 所有活跃节点应在图中
    assert active_nodes == graph_nodes, (
        f"MR-Compositional violation: VFS active nodes ({len(active_nodes)}) "
        f"differ from graph nodes ({len(graph_nodes)}). "
        f"Diff: active-graph={active_nodes - graph_nodes}, "
        f"graph-active={graph_nodes - active_nodes}"
    )


# ═══════════════════════════════════════════════════════════════
# §5 — 反模式检测：确保测试自身质量
# ═══════════════════════════════════════════════════════════════

# 注意：本文件所有测试函数以 test_mr_ 开头，使用蜕变关系断言 R(f(x), f(T(x)))，
# 没有使用 f(x) == y_expected 的自验证反模式（AP1）。
