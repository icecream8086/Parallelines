"""Tests for parallelines.types — dataclass behaviour."""

from __future__ import annotations

import unittest

from parallelines.types import (
    AddonManifest,
    AnalysisFragment,
    AnalysisReport,
    ConflictRecord,
    FileNode,
)


class TestFileNode(unittest.TestCase):
    """Verify FileNode field defaults and behaviour."""

    def test_file_node_defaults(self) -> None:
        """FileNode should produce sensible defaults for optional fields."""
        node = FileNode(
            virtual_path="maps/c1m1_hotel.bsp",
            source_type="game",
            source_name="base",
        )

        self.assertEqual(node.virtual_path, "maps/c1m1_hotel.bsp")
        self.assertEqual(node.source_type, "game")
        self.assertEqual(node.source_name, "base")
        self.assertIsNone(node.addon_id)
        self.assertEqual(node.priority, 0)
        self.assertEqual(node.file_size, 0)
        self.assertIsNone(node.file_hash)
        self.assertTrue(node.is_enabled)
        self.assertEqual(node.dependencies, set())
        self.assertFalse(node.is_dead)
        self.assertFalse(node.is_redundant)

    def test_file_node_dependencies(self) -> None:
        """FileNode should store dependencies correctly."""
        node = FileNode(
            virtual_path="materials/brick/brick.vtf",
            source_type="vpk",
            source_name="pak01_dir",
            dependencies={"materials/brick/brick_normal.vtf", "materials/brick/brick_bump.vtf"},
        )
        self.assertIn("materials/brick/brick_normal.vtf", node.dependencies)
        self.assertIn("materials/brick/brick_bump.vtf", node.dependencies)
        self.assertEqual(len(node.dependencies), 2)

    def test_file_node_all_fields(self) -> None:
        """FileNode should accept and store all fields."""
        node = FileNode(
            virtual_path="scripts/example.nut",
            source_type="addon",
            source_name="my_addon",
            addon_id="workshop_123",
            priority=50,
            file_size=1024,
            file_hash="abc123",
            is_enabled=True,
            is_dead=False,
            is_redundant=False,
        )
        self.assertEqual(node.addon_id, "workshop_123")
        self.assertEqual(node.priority, 50)
        self.assertEqual(node.file_size, 1024)
        self.assertEqual(node.file_hash, "abc123")


class TestConflictRecord(unittest.TestCase):
    """Verify ConflictRecord fields and defaults."""

    def test_conflict_record_defaults(self) -> None:
        """ConflictRecord should have correct defaults for optional fields."""
        record = ConflictRecord(
            conflict_type="hash_conflict",
            involved_vpks=["pak01_dir.vpk", "addon1.vpk"],
        )
        self.assertEqual(record.conflict_type, "hash_conflict")
        self.assertEqual(record.involved_vpks, ["pak01_dir.vpk", "addon1.vpk"])
        self.assertEqual(record.conflict_files, [])
        self.assertEqual(record.dependency_chain, [])
        self.assertEqual(record.suggestion, "")

    def test_conflict_record_full(self) -> None:
        """ConflictRecord with all fields populated."""
        record = ConflictRecord(
            conflict_type="dep_breakage",
            involved_vpks=["addon_a.vpk", "addon_b.vpk"],
            conflict_files=[{"path": "materials/brick.vtf", "source": "addon_a.vpk"}],
            dependency_chain=["a", "b", "c"],
            suggestion="Remove addon_b or reorder priorities",
        )
        self.assertEqual(record.conflict_type, "dep_breakage")
        self.assertEqual(len(record.conflict_files), 1)
        self.assertEqual(len(record.dependency_chain), 3)
        self.assertIn("Remove", record.suggestion)


class TestAddonManifest(unittest.TestCase):
    """Verify AddonManifest fields."""

    def test_addon_manifest(self) -> None:
        """AddonManifest should store all fields."""
        manifest = AddonManifest(
            addon_id="workshop_456",
            is_enabled=True,
            priority=100,
            name="My Cool Addon",
        )
        self.assertEqual(manifest.addon_id, "workshop_456")
        self.assertTrue(manifest.is_enabled)
        self.assertEqual(manifest.priority, 100)
        self.assertEqual(manifest.name, "My Cool Addon")


class TestAnalysisReport(unittest.TestCase):
    """Verify AnalysisReport / AnalysisFragment."""

    def test_analysis_report_empty(self) -> None:
        """An empty report should have no fragments."""
        report = AnalysisReport()
        self.assertEqual(report.fragments, [])

    def test_analysis_fragment(self) -> None:
        """AnalysisFragment should store analyzer name and items."""
        fragment = AnalysisFragment(
            analyzer_name="RedundancyAnalyzer",
            items=[{"virtual_path": "test.txt", "source": "base"}],
        )
        self.assertEqual(fragment.analyzer_name, "RedundancyAnalyzer")
        self.assertEqual(len(fragment.items), 1)
        self.assertEqual(fragment.items[0]["virtual_path"], "test.txt")

    def test_report_with_fragments(self) -> None:
        """AnalysisReport containing multiple fragments."""
        f1 = AnalysisFragment(analyzer_name="A", items=[{"id": 1}])
        f2 = AnalysisFragment(analyzer_name="B", items=[])
        report = AnalysisReport(fragments=[f1, f2])
        self.assertEqual(len(report.fragments), 2)
        self.assertEqual(report.fragments[0].analyzer_name, "A")


if __name__ == "__main__":
    unittest.main()
