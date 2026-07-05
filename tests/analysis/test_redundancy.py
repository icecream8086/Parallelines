"""Tests for parallelines.analysis.redundancy — RedundancyAnalyzer."""

from __future__ import annotations

import unittest

from parallelines.analysis.redundancy import RedundancyAnalyzer
from parallelines.engine import FileRow, Relation, ResultStore
from parallelines.types import FileNode
from parallelines.vfs.filesystem import VirtualFileSystem


class TestRedundancyAnalyzer(unittest.TestCase):
    """Verify RedundancyAnalyzer detection logic."""

    def setUp(self) -> None:
        self.analyzer = RedundancyAnalyzer()

    def _build_store_from_vfs(self, vfs: VirtualFileSystem) -> ResultStore:
        """Populate a ResultStore with FileRows derived from VFS nodes."""
        store = ResultStore()
        file_rows: list[FileRow] = []
        for node in vfs.get_all_files():
            file_rows.append(
                FileRow(
                    virtual_path=node.virtual_path,
                    source_name=node.source_name,
                    source_type=node.source_type,
                    priority=node.priority,
                    file_hash=node.file_hash or "",
                    file_size=node.file_size,
                    is_active=not node.is_redundant,
                )
            )
        store.files = Relation.from_rows("files", file_rows)
        return store

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

        store = self._build_store_from_vfs(vfs)
        self.analyzer.analyze(vfs, graph=None, store=store)

        redundant = [r for r in store.files.rows if r.is_redundant]
        self.assertEqual(len(redundant), 1)
        self.assertEqual(redundant[0].virtual_path, "maps/c1m1_hotel.bsp")
        self.assertEqual(redundant[0].source_name, "base")

    def test_no_redundant(self) -> None:
        """All unique paths produce no redundancies."""
        vfs = VirtualFileSystem()
        vfs.add_file(FileNode("a.txt", "game", "base", priority=10))
        vfs.add_file(FileNode("b.txt", "game", "base", priority=10))
        vfs.resolve()

        store = self._build_store_from_vfs(vfs)
        self.analyzer.analyze(vfs, graph=None, store=store)

        redundant = [r for r in store.files.rows if r.is_redundant]
        self.assertEqual(len(redundant), 0)

    def test_none_vfs(self) -> None:
        """When VFS is None, the analyzer returns without error."""
        store = ResultStore()
        self.analyzer.analyze(None, None, store=store)
        # store.files is None since no VFS was provided; no assertions needed.

    def test_multiple_redundant_same_path(self) -> None:
        """Multiple redundant files for the same path should all be reported."""
        vfs = VirtualFileSystem()
        vfs.add_file(FileNode("shared.txt", "game", "base", priority=10))
        vfs.add_file(FileNode("shared.txt", "vpk", "pak01_dir", priority=20))
        vfs.add_file(FileNode("shared.txt", "addon", "addon_z", priority=30))
        vfs.resolve()

        store = self._build_store_from_vfs(vfs)
        self.analyzer.analyze(vfs, graph=None, store=store)

        redundant = [r for r in store.files.rows if r.is_redundant]
        self.assertEqual(len(redundant), 2)
        redundant_sources = {r.source_name for r in redundant}
        self.assertSetEqual(redundant_sources, {"base", "pak01_dir"})

    def test_all_disabled_no_redundant(self) -> None:
        """When all nodes for a path are disabled, resolve skips the path
        entirely and does not mark any node as redundant."""
        vfs = VirtualFileSystem()
        node1 = FileNode("shared.txt", "game", "base", priority=10, is_enabled=False)
        node2 = FileNode(
            "shared.txt", "addon", "addon_x", priority=50, is_enabled=False
        )
        vfs.add_file(node1)
        vfs.add_file(node2)
        vfs.resolve()

        # resolve() skips paths where no enabled nodes exist
        self.assertFalse(node1.is_redundant)
        self.assertFalse(node2.is_redundant)

        store = self._build_store_from_vfs(vfs)
        self.analyzer.analyze(vfs, graph=None, store=store)

        redundant = [r for r in store.files.rows if r.is_redundant]
        self.assertEqual(len(redundant), 0)


if __name__ == "__main__":
    unittest.main()
