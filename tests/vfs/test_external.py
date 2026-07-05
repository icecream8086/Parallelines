"""Tests for parallelines.vfs.external -- ExternalVpkOverlay."""

from __future__ import annotations

import unittest
from pathlib import Path

from parallelines.vfs.external import ExternalVpkOverlay
from parallelines.vfs.filesystem import VirtualFileSystem


class TestExternalVpkOverlay(unittest.TestCase):
    """Smoke tests for ExternalVpkOverlay construction and analysis."""

    def test_importable(self) -> None:
        """ExternalVpkOverlay class can be imported."""
        from parallelines.vfs.external import ExternalVpkOverlay as EVO

        self.assertIsNotNone(EVO)

    def test_init(self) -> None:
        """ExternalVpkOverlay can be created with an empty VFS and a dummy VPK path."""
        base_vfs = VirtualFileSystem()
        dummy_path = Path("/nonexistent/external.vpk")
        overlay = ExternalVpkOverlay(base_vfs, dummy_path, priority=50)

        self.assertIs(overlay.base_vfs, base_vfs)
        self.assertEqual(overlay.vpk_path, dummy_path)
        self.assertEqual(overlay.priority, 50)

    def test_init_str_path(self) -> None:
        """ExternalVpkOverlay accepts a string path."""
        base_vfs = VirtualFileSystem()
        overlay = ExternalVpkOverlay(base_vfs, "/some/path.vpk", priority=10)

        self.assertIsInstance(overlay.vpk_path, Path)
        self.assertEqual(overlay.vpk_path, Path("/some/path.vpk"))

    def test_analyze_no_vpks(self) -> None:
        """Analyze with a non-existent VPK returns an error dict with empty summaries."""
        base_vfs = VirtualFileSystem()
        dummy_path = Path("/nonexistent/external.vpk")
        overlay = ExternalVpkOverlay(base_vfs, dummy_path, priority=50)

        result = overlay.analyze()

        self.assertIsInstance(result, dict)
        self.assertIn("error", result)
        self.assertEqual(result["external_vpk"], "external.vpk")
        self.assertEqual(result["summary"]["total_files_in_vpk"], 0)
        self.assertEqual(result["summary"]["will_override"], 0)
        self.assertEqual(result["summary"]["will_be_overridden"], 0)
        self.assertEqual(result["summary"]["new_files"], 0)
        self.assertEqual(result["overrides"], [])
        self.assertEqual(result["will_be_overridden"], [])
        self.assertEqual(result["new_files"], [])


if __name__ == "__main__":
    unittest.main()
