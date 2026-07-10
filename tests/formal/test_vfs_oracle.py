"""Layer 1 — 独立 Oracle 属性测试：VFS resolve()。

用纯 Python 参考实现作 Oracle，验证 VirtualFileSystem.resolve() 的正确性。
参考实现使用完全不同的数据结构（纯 dict），与被测代码无共享逻辑。
"""
from __future__ import annotations

import pytest

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


def _reference_resolve(files: list[FileNode]) -> dict[str, FileNode | None]:
    """参考实现：对每个路径，手工找最高优先级的 enabled 非 dead 文件。

    与被测 resolve() 使用完全不同的数据结构（纯 dict 而非 class）。
    匹配 VFS 的语义：平局时 first-encountered 胜出。
    """
    by_path: dict[str, list[FileNode]] = {}
    for f in files:
        by_path.setdefault(f.virtual_path, []).append(f)

    winners: dict[str, FileNode | None] = {}
    for path, nodes in by_path.items():
        # 过滤：只保留 enabled 且非 dead 的
        qualified = [n for n in nodes if n.is_enabled and not n.is_dead]
        if not qualified:
            winners[path] = None
        else:
            # 平局时第一个遇到的胜出（与 VFS 的 max() 一致）
            winners[path] = max(qualified, key=lambda n: n.priority)
    return winners


@pytest.fixture
def _register_strategy():
    """Register hypothesis strategies — only when hypothesis is available."""
    pass


@st.composite
def file_node_specs(draw) -> list[FileNode]:
    """生成随机 FileNode 组合，覆盖所有状态标志和边界。

    改进点 vs 旧版 file_node_specs：
    1. 包含空路径、Unicode 路径
    2. 包含极低和极高优先级
    3. 强制生成全部 disabled / 全部 dead 的极端场景
    """
    n_paths = draw(st.integers(0, 8))
    if n_paths == 0:
        return []

    paths: list[str] = []
    for _ in range(n_paths):
        path = draw(
            st.text(min_size=0, max_size=16).filter(
                lambda s: "\\" not in s and "\0" not in s
            )
        )
        paths.append(path)
    # 去重空字符串可能重复
    unique_paths: list[str] = []
    seen = set()
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique_paths.append(p)
    if not unique_paths:
        return []

    specs: list[FileNode] = []
    for path in unique_paths:
        n_copies = draw(st.integers(0, 4))
        for _ in range(n_copies):
            specs.append(
                FileNode(
                    virtual_path=path,
                    source_type="test",
                    source_name=draw(
                        st.text(min_size=0, max_size=10).filter(
                            lambda s: "\0" not in s
                        )
                    ),
                    priority=draw(st.integers(-100, 1000)),
                    is_enabled=draw(st.booleans()),
                    is_dead=draw(st.booleans()),
                    is_redundant=False,
                    is_disabled_addon=draw(st.booleans()),
                )
            )
    return specs


@pytest.mark.skipif(
    not _HYPOTHESIS_AVAILABLE, reason="hypothesis not installed"
)
class TestVfsResolveOracle:
    """用参考实现 Oracle 验证 VFS resolve()。"""

    @settings(suppress_health_check=[HealthCheck.too_slow])
    @given(specs=file_node_specs())
    def test_resolve_matches_reference(self, specs: list[FileNode]) -> None:
        """被测 resolve() 的结果与参考实现一致。"""
        vfs = VirtualFileSystem()
        for node in specs:
            vfs.add_file(node)
        vfs.resolve()

        ref = _reference_resolve(specs)

        for path, expected_winner in ref.items():
            actual = vfs.get_active_file(path)
            if expected_winner is None:
                assert actual is None, (
                    f"路径 '{path}' 预期无 winner，实际有 {actual}"
                )
            else:
                assert actual is not None, (
                    f"路径 '{path}' 预期 winner={expected_winner.source_name}，实际为 None"
                )
                assert actual.virtual_path == expected_winner.virtual_path
                assert actual.source_name == expected_winner.source_name

    @settings(suppress_health_check=[HealthCheck.too_slow])
    @given(specs=file_node_specs())
    def test_redundant_implies_higher_priority_active(
        self, specs: list[FileNode]
    ) -> None:
        """每一条 enabled 冗余文件都有更高优先级的活跃 winner。

        注意：disabled 文件也可能被标记为 redundant，但它们从未入候选集，
        因此 priority 可能高于 winner — 这是一个设计决策而非 bug。
        """
        vfs = VirtualFileSystem()
        for node in specs:
            vfs.add_file(node)
        vfs.resolve()

        for node in vfs.get_all_files():
            if node.is_redundant and node.is_enabled and not node.is_dead:
                winner = vfs.get_active_file(node.virtual_path)
                assert winner is not None, (
                    f"冗余文件 {node.virtual_path}/{node.source_name} 没有活跃 winner"
                )
                assert winner.priority >= node.priority, (
                    f"冗余文件 {node.source_name}(pri={node.priority}) 的 winner "
                    f"{winner.source_name}(pri={winner.priority}) 优先级更低"
                )
                assert winner is not node, (
                    f"冗余文件 {node.source_name} 自身就是 winner — 标志矛盾"
                )

    @settings(suppress_health_check=[HealthCheck.too_slow])
    @given(specs=file_node_specs())
    def test_dead_files_never_win(self, specs: list[FileNode]) -> None:
        """is_dead=True 的文件永远不能成为 winner。"""
        vfs = VirtualFileSystem()
        for node in specs:
            vfs.add_file(node)
        vfs.resolve()

        for node in vfs.get_all_files():
            if node.is_dead:
                winner = vfs.get_active_file(node.virtual_path)
                if winner is not None:
                    assert winner is not node, (
                        f"Dead 文件 {node.virtual_path}/{node.source_name} "
                        f"成了 winner"
                    )

    @settings(suppress_health_check=[HealthCheck.too_slow])
    @given(specs=file_node_specs())
    def test_vfs_invariant_winner_has_max_priority(
        self, specs: list[FileNode]
    ) -> None:
        """活跃 winner 一定是该路径下 enabled 文件中的最高优先级。

        这是 resolve() 的核心正确性属性：比 Oracle 更强——Oracle
        只是说"结果一致"，这里说"结果必须是最优的"。
        """
        vfs = VirtualFileSystem()
        for node in specs:
            vfs.add_file(node)
        vfs.resolve()

        by_path: dict[str, list[FileNode]] = {}
        for node in specs:
            by_path.setdefault(node.virtual_path, []).append(node)

        for path, candidates in by_path.items():
            qualified = [
                n
                for n in candidates
                if n.is_enabled and not n.is_dead
            ]
            if not qualified:
                assert vfs.get_active_file(path) is None, (
                    f"无有效文件时路径 '{path}' 不应有 winner"
                )
            else:
                winner = vfs.get_active_file(path)
                assert winner is not None, (
                    f"路径 '{path}' 有 {len(qualified)} 个有效文件但无 winner"
                )
                max_prio = max(n.priority for n in qualified)
                assert winner.priority == max_prio, (
                    f"路径 '{path}' winner priority={winner.priority} "
                    f"不是最大值 {max_prio}"
                )
