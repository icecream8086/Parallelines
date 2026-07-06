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

if __name__ == "__main__":
    unittest.main()
