"""Layer 2 — 蜕变测试：VFS resolve()。

蜕变测试不依赖"正确答案"，而是验证输入变换与输出变换之间的
可预测关系。天然免疫 oracle 问题。
"""
from __future__ import annotations

import pytest

from parallelines.types import FileNode
from parallelines.vfs.filesystem import VirtualFileSystem


class TestVfsMetamorphic:
    """VFS resolve() 蜕变关系。

    每条测试方法验证一个蜕变关系：变换输入后输出如何按已知方式变化。
    """

    @staticmethod
    def _make_vfs(
        path_priorities: list[tuple[str, int]],
        enabled: bool = True,
    ) -> VirtualFileSystem:
        vfs = VirtualFileSystem()
        for path, prio in path_priorities:
            vfs.add_file(
                FileNode(
                    virtual_path=path,
                    source_type="test",
                    source_name=f"src_{prio}",
                    priority=prio,
                    is_enabled=enabled,
                )
            )
        vfs.resolve()
        return vfs

    # ── 蜕变 1：添加更高优先级 → winner 一定切换 ─────────────────────────

    def test_add_higher_priority_changes_winner(self) -> None:
        """添加更高优先级的同路径文件 → winner 必变为新文件。"""
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode("a.txt", "test", "low", priority=5, is_enabled=True)
        )
        vfs.resolve()
        assert vfs.get_active_file("a.txt").source_name == "low"  # type: ignore[union-attr]

        vfs.add_file(
            FileNode("a.txt", "test", "high", priority=10, is_enabled=True)
        )
        vfs.resolve()
        winner = vfs.get_active_file("a.txt")
        assert winner is not None
        assert winner.source_name == "high", (
            f"添加更高优先级后 winner 应为 'high'，实际为 '{winner.source_name}'"
        )

    # ── 蜕变 2：移除 winner → 次高晋升 ──────────────────────────────────

    def test_remove_winner_promotes_runner_up(self) -> None:
        """移除当前 winner 的前置条件：is_dead → 次高优先级变为新 winner。"""
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode("a.txt", "test", "high", priority=10, is_enabled=True)
        )
        vfs.add_file(
            FileNode("a.txt", "test", "mid", priority=5, is_enabled=True)
        )
        vfs.add_file(
            FileNode("a.txt", "test", "low", priority=1, is_enabled=True)
        )
        vfs.resolve()

        winner_before = vfs.get_active_file("a.txt")
        assert winner_before is not None
        assert winner_before.source_name == "high"

        # 让 winner 变为 dead → 触发重新裁决
        winner_before.is_dead = True
        # 注意：resolve() 在 _files 中过滤 is_dead，但 is_dead 是 FileNode 上的可变标志
        # 需要重新 resolve
        vfs.resolve()

        winner_after = vfs.get_active_file("a.txt")
        assert winner_after is not None
        assert winner_after.source_name == "mid", (
            f"移除 high 后 winner 应为 'mid'，实际为 '{winner_after.source_name}'"
        )
        assert winner_after.priority == 5

    # ── 蜕变 3：禁用 winner → 降级为 redundant，次高变为 active ────────

    def test_disable_winner_demotes(self) -> None:
        """禁用当前 winner 的 is_enabled → 它变为 redundant，次高 active。"""
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode("a.txt", "test", "high", priority=10, is_enabled=True)
        )
        vfs.add_file(
            FileNode("a.txt", "test", "low", priority=1, is_enabled=True)
        )
        vfs.resolve()

        high_node = vfs.get_active_file("a.txt")
        assert high_node is not None
        assert high_node.source_name == "high"

        # 标记禁用并重新 resolve
        high_node.is_enabled = False
        vfs.resolve()

        new_winner = vfs.get_active_file("a.txt")
        assert new_winner is not None
        assert new_winner.source_name == "low", (
            "禁用 high 后 low 应成为新 winner"
        )

    # ── 蜕变 4：添加全新路径 → active 文件数 +1 ─────────────────────────

    def test_adding_unique_path_increases_count(self) -> None:
        """添加从未出现过的路径 → active 文件数增加 1。"""
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode("a.txt", "test", "s1", priority=10, is_enabled=True)
        )
        vfs.resolve()
        count_before = len(vfs.get_all_active())

        vfs.add_file(
            FileNode("b.txt", "test", "s1", priority=10, is_enabled=True)
        )
        vfs.resolve()
        count_after = len(vfs.get_all_active())

        assert count_after == count_before + 1, (
            f"添加新路径后 active 数应 +1，实际 {count_before} → {count_after}"
        )

    # ── 蜕变 5：解决幂等性（resolve() 两次 ≡ resolve() 一次）──────────────

    def test_resolve_idempotent(self) -> None:
        """resolve() 两次的结果必须与 resolve() 一次完全相同。"""
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode("a.txt", "test", "s1", priority=10, is_enabled=True)
        )
        vfs.add_file(
            FileNode("a.txt", "test", "s2", priority=5, is_enabled=True)
        )
        vfs.add_file(
            FileNode("b.txt", "test", "s1", priority=3, is_enabled=True)
        )
        vfs.resolve()

        first_active = {
            (n.virtual_path, n.source_name, n.priority)
            for n in vfs.get_all_active()
        }

        # 第二次 resolve()
        vfs.resolve()
        second_active = {
            (n.virtual_path, n.source_name, n.priority)
            for n in vfs.get_all_active()
        }

        assert first_active == second_active, (
            f"resolve() 幂等性违反\n"
            f"  第一次: {first_active}\n"
            f"  第二次: {second_active}"
        )

    # ── 蜕变 6：合并无重叠路径的 VFS → active 数等于各 VFS 之和 ──────────

    def test_merge_independent_vfs_is_additive(self) -> None:
        """两个路径集不重叠的 VFS → merge 后 active 数 = 各自 active 数之和。"""
        vfs_a = self._make_vfs([("a.txt", 10), ("b.txt", 5)])
        vfs_b = self._make_vfs([("c.txt", 10), ("d.txt", 5)])

        count_a = len(vfs_a.get_all_active())
        count_b = len(vfs_b.get_all_active())

        # 合并：将 vfs_b 的文件加入 vfs_a
        for node in vfs_b.get_all_files():
            vfs_a.add_file(node)
        vfs_a.resolve()

        count_merged = len(vfs_a.get_all_active())
        assert count_merged == count_a + count_b, (
            f"合并无重叠路径的 VFS：预期 {count_a}+{count_b}={count_a+count_b}，"
            f"实际 {count_merged}"
        )

    # ── 蜕变 7：等优先级平局必须是确定性的 ─────────────────────────────────

    def test_tie_break_deterministic(self) -> None:
        """相同优先级的文件，多次 resolve() 结果必须一致。"""
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode("tie.txt", "test", "a", priority=5, is_enabled=True)
        )
        vfs.add_file(
            FileNode("tie.txt", "test", "b", priority=5, is_enabled=True)
        )
        vfs.add_file(
            FileNode("tie.txt", "test", "c", priority=5, is_enabled=True)
        )

        vfs.resolve()
        first_winner = vfs.get_active_file("tie.txt")
        assert first_winner is not None

        # 重复 resolve 多次
        for _ in range(10):
            vfs.resolve()
            w = vfs.get_active_file("tie.txt")
            assert w is not None and w.source_name == first_winner.source_name, (
                f"平局结果不稳定：首次 {first_winner.source_name}，"
                f"后续 {w.source_name if w else 'None'}"
            )
