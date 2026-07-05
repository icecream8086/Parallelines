"""Tests for parallelines.analysis.hash_conflict — HashConflictAnalyzer."""

from __future__ import annotations

import unittest

from parallelines.analysis.hash_conflict import HashConflictAnalyzer
from parallelines.engine import Relation, ResultStore
from parallelines.engine.schema import FileRow
from parallelines.types import FileNode
from parallelines.vfs.filesystem import VirtualFileSystem


class TestHashConflictAnalyzer(unittest.TestCase):
    """Verify HashConflictAnalyzer conflict detection via ResultStore API."""

    def setUp(self) -> None:
        self.analyzer = HashConflictAnalyzer()

    def _make_store(self, vfs: VirtualFileSystem) -> ResultStore:
        """Build a ResultStore with files populated from VFS."""
        store = ResultStore()
        file_rows = [
            FileRow(
                virtual_path=node.virtual_path,
                source_name=node.source_name,
                source_type=node.source_type,
                priority=node.priority,
                file_hash=node.file_hash or "",
                file_size=node.file_size,
                is_active=not node.is_redundant,
            )
            for node in vfs.get_all_files()
        ]
        store.files = Relation.from_rows("files", file_rows)
        return store

    def test_hash_conflict_detected(self) -> None:
        """Same virtual path, different hashes, both enabled -> 1 conflict row."""
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode(
                virtual_path="scripts/skill.cfg",
                source_type="addon",
                source_name="addon_a",
                file_hash="abc123",
                priority=50,
            )
        )
        vfs.add_file(
            FileNode(
                virtual_path="scripts/skill.cfg",
                source_type="addon",
                source_name="addon_b",
                file_hash="def456",
                priority=100,
            )
        )
        vfs.resolve()
        store = self._make_store(vfs)
        self.analyzer.analyze(vfs, graph=None, store=store)

        self.assertIsNotNone(store.hash_conflicts)
        rows = store.hash_conflicts.rows
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].virtual_path, "scripts/skill.cfg")
        self.assertEqual(rows[0].winner_source, "addon_b")
        self.assertEqual(rows[0].loser_source, "addon_a")
        self.assertEqual(rows[0].winner_hash, "def456")
        self.assertEqual(rows[0].loser_hash, "abc123")

    def test_no_conflict_single_source(self) -> None:
        """A file appearing in only one source should not be reported."""
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode(
                virtual_path="unique.txt",
                source_type="game",
                source_name="base",
                file_hash="aaa",
                priority=10,
            )
        )
        vfs.resolve()
        store = self._make_store(vfs)
        self.analyzer.analyze(vfs, graph=None, store=store)

        rows = store.hash_conflicts.rows if store.hash_conflicts else []
        self.assertEqual(len(rows), 0)

    def test_same_hash_no_conflict(self) -> None:
        """Same path, same hash across sources -> no rows (same-hash is benign)."""
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode(
                virtual_path="materials/brick.vtf",
                source_type="vpk",
                source_name="pak01_dir",
                file_hash="samehash",
                priority=100,
            )
        )
        vfs.add_file(
            FileNode(
                virtual_path="materials/brick.vtf",
                source_type="addon",
                source_name="addon_c",
                file_hash="samehash",
                priority=50,
            )
        )
        vfs.resolve()
        store = self._make_store(vfs)
        self.analyzer.analyze(vfs, graph=None, store=store)

        rows = store.hash_conflicts.rows if store.hash_conflicts else []
        self.assertEqual(len(rows), 0)

    def test_engine_override_is_info(self) -> None:
        """Addon winning over engine source with different hash -> 1 conflict row."""
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode(
                virtual_path="maps/c1m1_hotel.bsp",
                source_type="game",
                source_name="pak01_dir",
                file_hash="engine_hash",
                priority=100,
            )
        )
        vfs.add_file(
            FileNode(
                virtual_path="maps/c1m1_hotel.bsp",
                source_type="addon",
                source_name="addon_overrider",
                file_hash="addon_hash",
                priority=200,
            )
        )
        vfs.resolve()
        store = self._make_store(vfs)
        self.analyzer.analyze(vfs, graph=None, store=store)

        rows = store.hash_conflicts.rows
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].virtual_path, "maps/c1m1_hotel.bsp")
        # Addon wins (priority 200 > 100)
        self.assertEqual(rows[0].winner_source, "addon_overrider")
        self.assertEqual(rows[0].loser_source, "pak01_dir")

    def test_engine_wins_info_severity(self) -> None:
        """Engine source wins and hash differs -> 1 conflict row."""
        vfs = VirtualFileSystem()
        vfs.add_file(
            FileNode(
                virtual_path="materials/brick.vtf",
                source_type="game",
                source_name="pak01_dir",
                file_hash="engine_hash",
                priority=100,
            )
        )
        vfs.add_file(
            FileNode(
                virtual_path="materials/brick.vtf",
                source_type="addon",
                source_name="addon_x",
                file_hash="addon_hash",
                priority=50,
            )
        )
        vfs.resolve()
        store = self._make_store(vfs)
        self.analyzer.analyze(vfs, graph=None, store=store)

        rows = store.hash_conflicts.rows
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].virtual_path, "materials/brick.vtf")
        # Engine source wins (pak01_dir has priority 100 > 50)
        self.assertEqual(rows[0].winner_source, "pak01_dir")
        self.assertEqual(rows[0].loser_source, "addon_x")

    def test_none_vfs_empty_fragment(self) -> None:
        """A None VFS should not raise and hash_conflicts should remain None."""
        store = ResultStore()
        self.analyzer.analyze(None, graph=None, store=store)
        self.assertIsNone(store.hash_conflicts)

    def test_multiple_paths_some_conflict(self) -> None:
        """Multiple paths: only those with multi-source hash conflicts appear."""
        vfs = VirtualFileSystem()
        # Two sources for this one
        vfs.add_file(
            FileNode("conflict.txt", "addon", "addon_a", file_hash="h1", priority=50)
        )
        vfs.add_file(
            FileNode("conflict.txt", "addon", "addon_b", file_hash="h2", priority=100)
        )
        # Single source for this one
        vfs.add_file(
            FileNode("unique.txt", "game", "base", file_hash="h3", priority=10)
        )
        vfs.resolve()
        store = self._make_store(vfs)
        self.analyzer.analyze(vfs, graph=None, store=store)

        rows = store.hash_conflicts.rows  # type: ignore[union-attr]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].virtual_path, "conflict.txt")


if __name__ == "__main__":
    unittest.main()
