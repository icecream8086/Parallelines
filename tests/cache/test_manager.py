"""Tests for parallelines.cache.manager -- CacheManager."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from parallelines.cache.manager import CacheManager
from parallelines.cache.strategies import MtimeStrategy


class TestCacheManager(unittest.TestCase):
    """Verify CacheManager initialisation, I/O, and invalidation."""

    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.manager = CacheManager(self.tmp_dir)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_init(self) -> None:
        """CacheManager initialises with a path and default strategy."""
        self.assertEqual(self.manager.cache_dir, self.tmp_dir)
        self.assertIsInstance(self.manager.strategy, MtimeStrategy)

    def test_init_custom_strategy(self) -> None:
        """CacheManager accepts a custom strategy."""
        from parallelines.cache.strategies import HashStrategy

        manager = CacheManager(self.tmp_dir, strategy=HashStrategy())
        self.assertIsInstance(manager.strategy, HashStrategy)

    def test_is_valid_empty_cache(self) -> None:
        """is_valid returns False when no cache exists yet."""
        self.assertFalse(self.manager.is_valid([]))
        self.assertFalse(self.manager.is_valid([{"name": "test.vpk"}]))

    def test_save_and_load(self) -> None:
        """Save data to cache and load it back successfully."""
        import pandas as pd

        files_df = pd.DataFrame(
            {
                "virtual_path": ["a.txt", "b.txt"],
                "source_type": ["vpk", "vpk"],
                "source_name": ["pak01_dir", "pak01_dir"],
                "priority": [100, 100],
                "file_size": [10, 20],
                "file_hash": ["abc", "def"],
                "is_enabled": [True, True],
            }
        )
        edges_df = pd.DataFrame(
            {
                "from": ["a.txt"],
                "to": ["b.txt"],
            }
        )
        meta = {
            "version": "1.0",
            "game": "l4d2",
            "entries": {
                "pak01_dir.vpk": {"mtime": 1000, "size": 500},
            },
        }

        self.manager.save(files_df, edges_df, meta)

        loaded_files = self.manager.load_files()
        self.assertIsNotNone(loaded_files)
        self.assertEqual(len(loaded_files), 2)
        self.assertIn("virtual_path", loaded_files.columns)

        loaded_edges = self.manager.load_edges()
        self.assertIsNotNone(loaded_edges)
        self.assertEqual(len(loaded_edges), 1)

    def test_is_valid_after_save(self) -> None:
        """is_valid returns True after saving matching VPK manifest data."""
        import pandas as pd

        vpk_list = [
            {"source_name": "pak01_dir.vpk", "mtime": 1000, "size": 500},
        ]
        files_df = pd.DataFrame(
            {
                "virtual_path": [],
                "source_type": [],
                "source_name": [],
                "priority": [],
                "file_size": [],
                "file_hash": [],
                "is_enabled": [],
            }
        )
        edges_df = pd.DataFrame({"from": [], "to": []})
        meta = {
            "version": "1.0",
            "entries": {
                "pak01_dir.vpk": {"mtime": 1000, "size": 500},
            },
        }

        self.manager.save(files_df, edges_df, meta)
        self.assertTrue(self.manager.is_valid(vpk_list))

        # Changing mtime should invalidate
        changed_vpk_list = [
            {"source_name": "pak01_dir.vpk", "mtime": 9999, "size": 500},
        ]
        self.assertFalse(self.manager.is_valid(changed_vpk_list))

    def test_clear(self) -> None:
        """Invalidate removes all cache files."""
        import pandas as pd

        files_df = pd.DataFrame(
            {
                "virtual_path": ["x.txt"],
                "source_type": ["game"],
                "source_name": ["base"],
                "priority": [10],
                "file_size": [100],
                "file_hash": [""],
                "is_enabled": [True],
            }
        )
        edges_df = pd.DataFrame({"from": [], "to": []})
        self.manager.save(files_df, edges_df, {"version": "1.0", "entries": {}})

        # Verify cache files exist
        self.assertTrue((self.tmp_dir / "meta.json").exists())
        self.assertTrue((self.tmp_dir / "all_files.parquet").exists())

        self.manager.invalidate()

        self.assertFalse((self.tmp_dir / "meta.json").exists())
        self.assertFalse((self.tmp_dir / "all_files.parquet").exists())
        self.assertFalse((self.tmp_dir / "dependencies.parquet").exists())

    def test_clear_empty_cache(self) -> None:
        """Invalidate on an empty cache does not raise errors."""
        self.manager.invalidate()  # Should not raise


if __name__ == "__main__":
    unittest.main()
