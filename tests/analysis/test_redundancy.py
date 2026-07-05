"""Tests for parallelines.analysis.redundancy — RedundancyAnalyzer."""

from __future__ import annotations

import unittest

from parallelines.analysis.redundancy import RedundancyAnalyzer
from parallelines.types import FileNode
from parallelines.vfs.filesystem import VirtualFileSystem


class TestRedundancyAnalyzer(unittest.TestCase):
    """Verify RedundancyAnalyzer detection logic."""

    def setUp(self) -> None:
        self.analyzer = RedundancyAnalyzer()

    def test_redundant_file_detected(self) -> None:
        """When two sources provide the same path, the lower-priority one is redundant."""
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode(
                virtual_path="maps/c1m1_hotel.bsp",
                source_type="game",
                source_name="base",
                priority=10,
            )
        )
        vfs.add_file(
            FileNode(
                virtual_path="maps/c1m1_hotel.bsp",
                source_type="addon",
                source_name="addon_a",
                priority=50,
            )
        )
        vfs.resolve()

        fragment = self.analyzer.analyze(vfs, graph=None)
        self.assertEqual(fragment.analyzer_name, "RedundancyAnalyzer")
        self.assertEqual(len(fragment.items), 1)
        item = fragment.items[0]
        self.assertEqual(item["virtual_path"], "maps/c1m1_hotel.bsp")
        self.assertEqual(item["source_name"], "base")
        self.assertEqual(item["overridden_by"], "addon_a")

    def test_no_redundant(self) -> None:
        """All unique paths produce no redundancies."""
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode("a.txt", "game", "base", priority=10)
        )
        vfs.add_file(
            FileNode("b.txt", "game", "base", priority=10)
        )
        vfs.resolve()

        fragment = self.analyzer.analyze(vfs, graph=None)
        self.assertEqual(len(fragment.items), 0)

    def test_none_vfs(self) -> None:
        """When VFS is None, the analyzer returns an empty fragment."""
        fragment = self.analyzer.analyze(None, graph=None)
        self.assertEqual(fragment.analyzer_name, "RedundancyAnalyzer")
        self.assertEqual(len(fragment.items), 0)

    def test_multiple_redundant_same_path(self) -> None:
        """Multiple redundant files for the same path should all be reported."""
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode("shared.txt", "game", "base", priority=10)
        )
        vfs.add_file(
            FileNode("shared.txt", "vpk", "pak01_dir", priority=20)
        )
        vfs.add_file(
            FileNode("shared.txt", "addon", "addon_z", priority=30)
        )
        vfs.resolve()

        fragment = self.analyzer.analyze(vfs, graph=None)
        # Two redundant nodes: base and pak01_dir
        self.assertEqual(len(fragment.items), 2)
        redundant_sources = {i["source_name"] for i in fragment.items}
        self.assertSetEqual(redundant_sources, {"base", "pak01_dir"})

    def test_all_disabled_no_redundant(self) -> None:
        """When all nodes for a path are disabled, resolve skips the path
        entirely and does not mark any node as redundant. The analyzer
        returns an empty item list because no redundant nodes exist."""
        vfs = VirtualFileSystem()
        node1 = FileNode("shared.txt", "game", "base", priority=10, is_enabled=False)
        node2 = FileNode("shared.txt", "addon", "addon_x", priority=50, is_enabled=False)
        vfs.add_file(node1)
        vfs.add_file(node2)
        vfs.resolve()

        # resolve() skips paths where no enabled nodes exist, so neither
        # node is marked as redundant (is_redundant stays False).
        self.assertFalse(node1.is_redundant)
        self.assertFalse(node2.is_redundant)

        # The analyzer iterates get_all_files() looking for is_redundant=True
        fragment = self.analyzer.analyze(vfs, graph=None)
        self.assertEqual(len(fragment.items), 0)


if __name__ == "__main__":
    unittest.main()
