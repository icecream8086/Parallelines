"""Tests for parallelines.analysis.hash_conflict — HashConflictAnalyzer."""

from __future__ import annotations

import unittest

from parallelines.analysis.hash_conflict import HashConflictAnalyzer
from parallelines.types import FileNode
from parallelines.vfs.filesystem import VirtualFileSystem


class TestHashConflictAnalyzer(unittest.TestCase):
    """Verify HashConflictAnalyzer conflict detection and severity classification."""

    def setUp(self) -> None:
        self.analyzer = HashConflictAnalyzer()

    def test_hash_conflict_detected(self) -> None:
        """Same virtual path, different hashes, both enabled -> severity=warning."""
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

        fragment = self.analyzer.analyze(vfs, graph=None)
        self.assertEqual(fragment.analyzer_name, "HashConflictAnalyzer")
        self.assertEqual(len(fragment.items), 1)

        item = fragment.items[0]
        self.assertEqual(item["virtual_path"], "scripts/skill.cfg")
        self.assertTrue(item["hash_differ"])
        self.assertEqual(item["severity"], "warning")

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

        fragment = self.analyzer.analyze(vfs, graph=None)
        self.assertEqual(len(fragment.items), 0)

    def test_same_hash_no_conflict(self) -> None:
        """Same path, same hash across sources -> severity=silent."""
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

        fragment = self.analyzer.analyze(vfs, graph=None)
        self.assertEqual(len(fragment.items), 1)
        item = fragment.items[0]
        self.assertFalse(item["hash_differ"])
        self.assertEqual(item["severity"], "silent")

    def test_engine_override_is_info(self) -> None:
        """Addon winning over engine source with different hash -> handled (no crash)."""
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

        fragment = self.analyzer.analyze(vfs, graph=None)
        self.assertEqual(len(fragment.items), 1)
        item = fragment.items[0]
        # Addon wins (priority 200 > 100) and hash differs
        self.assertTrue(item["hash_differ"])
        # Winner is addon_overrider (not an engine source), so severity is warning
        self.assertEqual(item["severity"], "warning")

    def test_engine_wins_info_severity(self) -> None:
        """When an engine source is the winner and hash differs -> severity=info."""
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

        fragment = self.analyzer.analyze(vfs, graph=None)
        self.assertEqual(len(fragment.items), 1)
        item = fragment.items[0]
        self.assertTrue(item["hash_differ"])
        # Engine source wins (pak01_dir has priority 100 > 50)
        self.assertEqual(item["severity"], "info")

    def test_none_vfs_empty_fragment(self) -> None:
        """A None VFS produces an empty fragment."""
        fragment = self.analyzer.analyze(None, graph=None)
        self.assertEqual(fragment.analyzer_name, "HashConflictAnalyzer")
        self.assertEqual(len(fragment.items), 0)

    def test_multiple_paths_some_conflict(self) -> None:
        """Multiple paths: only those with multi-source conflicts appear."""
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

        fragment = self.analyzer.analyze(vfs, graph=None)
        self.assertEqual(len(fragment.items), 1)
        self.assertEqual(fragment.items[0]["virtual_path"], "conflict.txt")


if __name__ == "__main__":
    unittest.main()
