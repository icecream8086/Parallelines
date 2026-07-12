"""Tests for parallelines.vfs.external -- ExternalVpkOverlay."""

from __future__ import annotations

import unittest
from pathlib import Path

from parallelines.types import FileNode
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

# ===================================================================
# Oracle-free tests for ExternalVpkOverlay
# ===================================================================


class TestExternalVpkOverlayOracleFree:
    """Oracle-free (metamorphic) tests for ExternalVpkOverlay.build_overlay."""

    def test_build_overlay_preserves_base_nodes(self) -> None:
        """MR-Add: overlay VFS contains at least the base nodes after build.

        The overlay should never lose base nodes; the base is an additive
        foundation that the overlay inherits.
        """
        base = VirtualFileSystem()
        base.add_file(FileNode("a.txt", "game", "base", priority=10))
        base.add_file(FileNode("b.txt", "game", "base", priority=10))

        overlay_vfs = ExternalVpkOverlay(
            base, Path("/nonexistent/external.vpk")
        ).build_overlay()

        # MR-Add: the overlay must have at least as many nodes as the base
        assert len(overlay_vfs.get_all_files()) >= 2

    def test_nonexistent_vpk_does_not_crash(self) -> None:
        """MR-Add: a nonexistent external VPK returns an overlay with base nodes intact.

        The VPK parse error is caught internally; the base nodes survive the
        exception and the overlay is still usable.
        """
        base = VirtualFileSystem()
        base.add_file(FileNode("surviving.txt", "game", "base", priority=10))

        overlay_vfs = ExternalVpkOverlay(
            base, Path("/nonexistent/external.vpk")
        ).build_overlay()

        # The base node should still be present
        assert len(overlay_vfs.get_all_files()) >= 1

    def test_overlay_nodes_are_detached_copies(self) -> None:
        """MR-Inv: modifying overlay nodes does not affect base VFS nodes.

        Invertive: the overlay creates detached copies (via dataclasses.replace),
        so mutating the overlay nodes is invertible with respect to the base —
        the base remains unchanged.
        """
        base = VirtualFileSystem()
        base.add_file(
            FileNode("a.txt", "game", "base", priority=10, file_size=100)
        )

        overlay_vfs = ExternalVpkOverlay(
            base, Path("/nonexistent/external.vpk")
        ).build_overlay()

        base_nodes = base.get_all_files()
        overlay_nodes = overlay_vfs.get_all_files()

        assert len(overlay_nodes) >= 1

        # Mutate all overlay nodes
        for node in overlay_nodes:
            node.file_size = 999

        # Base nodes must be unchanged
        for node in base_nodes:
            assert node.file_size == 100


if __name__ == "__main__":
    unittest.main()
