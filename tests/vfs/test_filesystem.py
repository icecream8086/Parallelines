"""Tests for parallelines.vfs.filesystem — VirtualFileSystem."""

from __future__ import annotations

import unittest

from parallelines.types import FileNode
from parallelines.vfs.filesystem import VirtualFileSystem


class TestVirtualFileSystem(unittest.TestCase):
    """Verify VFS add, resolve, and access behaviour."""

    def setUp(self) -> None:
        self.vfs = VirtualFileSystem()

    def test_add_and_resolve(self) -> None:
        """Adding two FileNodes with same path, different priority: highest wins."""
        low = FileNode(
            virtual_path="maps/c1m1_hotel.bsp",
            source_type="game",
            source_name="base",
            priority=10,
            is_enabled=True,
        )
        high = FileNode(
            virtual_path="maps/c1m1_hotel.bsp",
            source_type="addon",
            source_name="addon_a",
            priority=50,
            is_enabled=True,
        )

        self.vfs.add_file(low)
        self.vfs.add_file(high)
        self.vfs.resolve()

        active = self.vfs.get_active_file("maps/c1m1_hotel.bsp")
        self.assertIsNotNone(active)
        self.assertEqual(active.source_name, "addon_a")
        self.assertEqual(active.priority, 50)

        # Low-priority node should be marked redundant
        self.assertTrue(low.is_redundant)
        self.assertFalse(high.is_redundant)

    def test_resolve_tie(self) -> None:
        """Same priority: first-added node wins."""
        first = FileNode(
            virtual_path="materials/brick.vtf",
            source_type="vpk",
            source_name="pak01_dir",
            priority=100,
            is_enabled=True,
        )
        second = FileNode(
            virtual_path="materials/brick.vtf",
            source_type="addon",
            source_name="addon_b",
            priority=100,
            is_enabled=True,
        )

        self.vfs.add_file(first)
        self.vfs.add_file(second)
        self.vfs.resolve()

        active = self.vfs.get_active_file("materials/brick.vtf")
        self.assertIsNotNone(active)
        # In a tie, max() returns the first-encountered node
        self.assertEqual(active.source_name, "pak01_dir")

    def test_all_disabled(self) -> None:
        """All nodes for a path disabled => no active file for that path."""
        node = FileNode(
            virtual_path="scripts/disabled.nut",
            source_type="addon",
            source_name="disabled_addon",
            priority=100,
            is_enabled=False,
        )
        self.vfs.add_file(node)
        self.vfs.resolve()

        active = self.vfs.get_active_file("scripts/disabled.nut")
        self.assertIsNone(active)

    def test_get_active_file_missing(self) -> None:
        """Non-existent path returns None."""
        result = self.vfs.get_active_file("nonexistent/path.txt")
        self.assertIsNone(result)

    def test_get_all_active(self) -> None:
        """Verify count of active files after resolution."""
        self.vfs.add_file(
            FileNode("a.txt", "game", "base", priority=10, is_enabled=True)
        )
        self.vfs.add_file(
            FileNode("b.txt", "game", "base", priority=10, is_enabled=True)
        )
        self.vfs.add_file(
            FileNode("a.txt", "addon", "addon1", priority=50, is_enabled=True)
        )
        self.vfs.resolve()

        active = self.vfs.get_all_active()
        # Two unique paths: a.txt (won by addon1), b.txt (won by base)
        self.assertEqual(len(active), 2)
        paths = {n.virtual_path for n in active}
        self.assertSetEqual(paths, {"a.txt", "b.txt"})

    def test_get_all_files(self) -> None:
        """get_all_files returns all nodes regardless of active/redundant."""
        self.vfs.add_file(
            FileNode("a.txt", "game", "base", priority=10, is_enabled=True)
        )
        self.vfs.add_file(
            FileNode("a.txt", "addon", "addon1", priority=50, is_enabled=True)
        )
        self.vfs.add_file(
            FileNode("b.txt", "game", "base", priority=10, is_enabled=True)
        )

        all_files = self.vfs.get_all_files()
        # Three nodes total (two for a.txt, one for b.txt)
        self.assertEqual(len(all_files), 3)

    def test_resolve_idempotent(self) -> None:
        """Calling resolve multiple times should produce the same result."""
        self.vfs.add_file(
            FileNode("x.txt", "game", "base", priority=10, is_enabled=True)
        )
        self.vfs.add_file(
            FileNode("x.txt", "addon", "addon_x", priority=20, is_enabled=True)
        )
        self.vfs.resolve()
        self.vfs.resolve()
        self.vfs.resolve()

        active = self.vfs.get_active_file("x.txt")
        self.assertEqual(active.source_name, "addon_x")

    def test_dead_nodes_not_active(self) -> None:
        """Nodes with is_dead=True should not be considered for active resolution."""
        dead = FileNode(
            virtual_path="maps/dead_map.bsp",
            source_type="addon",
            source_name="dead_addon",
            priority=100,
            is_enabled=True,
            is_dead=True,
        )
        self.vfs.add_file(dead)
        self.vfs.resolve()
        self.assertIsNone(self.vfs.get_active_file("maps/dead_map.bsp"))


if __name__ == "__main__":
    unittest.main()
