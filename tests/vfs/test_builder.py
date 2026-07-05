"""Tests for parallelines.vfs.builder -- VfsBuilder."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from parallelines.config import AppConfig
from parallelines.vfs.builder import VfsBuilder
from parallelines.vfs.filesystem import VirtualFileSystem


class TestVfsBuilder(unittest.TestCase):
    """Smoke tests for VfsBuilder construction and build lifecycle."""

    def test_init(self) -> None:
        """VfsBuilder initialises with a Path and default config."""
        with tempfile.TemporaryDirectory() as tmp:
            game_root = Path(tmp)
            config = AppConfig()
            builder = VfsBuilder(game_root, config=config, use_cache=False)

            self.assertEqual(builder.game_root, game_root.resolve())
            self.assertIs(builder.config, config)
            self.assertFalse(builder.use_cache)
            self.assertFalse(builder.cache_hit)

    def test_init_default_config(self) -> None:
        """VfsBuilder can be created without an explicit config (falls back to load_config)."""
        with tempfile.TemporaryDirectory() as tmp:
            game_root = Path(tmp)
            builder = VfsBuilder(game_root, use_cache=False)

            self.assertEqual(builder.game_root, game_root.resolve())
            self.assertIsNotNone(builder.config)

    def test_build_returns_vfs(self) -> None:
        """VfsBuilder.build() returns a VirtualFileSystem even without a real game directory."""
        with tempfile.TemporaryDirectory() as tmp:
            game_root = Path(tmp)
            config = AppConfig()
            builder = VfsBuilder(game_root, config=config, use_cache=False)

            vfs = builder.build()

            self.assertIsInstance(vfs, VirtualFileSystem)
            # Without a gameinfo.txt, the VFS should be empty
            self.assertEqual(len(vfs.get_all_files()), 0)

    def test_build_from_nonexistent_root(self) -> None:
        """VfsBuilder handles a non-existent game root gracefully."""
        game_root = Path(tempfile.mktemp(suffix="_nonexistent"))
        self.assertFalse(game_root.exists())

        config = AppConfig()
        builder = VfsBuilder(game_root, config=config, use_cache=False)
        vfs = builder.build()

        self.assertIsInstance(vfs, VirtualFileSystem)

    def test_custom_num_workers(self) -> None:
        """VfsBuilder accepts custom num_workers parameter."""
        with tempfile.TemporaryDirectory() as tmp:
            builder = VfsBuilder(Path(tmp), use_cache=False, num_workers=4)
            self.assertEqual(builder.num_workers, 4)


if __name__ == "__main__":
    unittest.main()
