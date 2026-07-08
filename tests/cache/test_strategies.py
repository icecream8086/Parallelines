"""Tests for parallelines.cache.strategies -- MtimeStrategy, HashStrategy."""

from __future__ import annotations

import unittest

from parallelines.cache.strategies import HashStrategy, MtimeStrategy


class TestMtimeStrategy(unittest.TestCase):
    """Verify MtimeStrategy cache validation logic."""

    def setUp(self) -> None:
        self.strategy = MtimeStrategy()

    def test_strategy_name(self) -> None:
        """MtimeStrategy class name is correct."""
        self.assertEqual(type(self.strategy).__name__, "MtimeStrategy")

    def test_is_valid_matching(self) -> None:
        """is_valid returns True when mtime and size match."""
        cache_meta = {
            "pak01_dir.vpk": {"mtime": 1000, "size": 500},
            "pak02_dir.vpk": {"mtime": 2000, "size": 600},
        }
        current_state = {
            "pak01_dir.vpk": {"mtime": 1000, "size": 500},
            "pak02_dir.vpk": {"mtime": 2000, "size": 600},
        }
        self.assertTrue(self.strategy.is_valid(cache_meta, current_state))

    def test_is_valid_mtime_mismatch(self) -> None:
        """is_valid returns False when mtime differs."""
        cache_meta = {
            "pak01_dir.vpk": {"mtime": 1000, "size": 500},
        }
        current_state = {
            "pak01_dir.vpk": {"mtime": 9999, "size": 500},
        }
        self.assertFalse(self.strategy.is_valid(cache_meta, current_state))

    def test_is_valid_size_mismatch(self) -> None:
        """is_valid returns False when size differs."""
        cache_meta = {
            "pak01_dir.vpk": {"mtime": 1000, "size": 500},
        }
        current_state = {
            "pak01_dir.vpk": {"mtime": 1000, "size": 999},
        }
        self.assertFalse(self.strategy.is_valid(cache_meta, current_state))

    def test_is_valid_key_mismatch(self) -> None:
        """is_valid returns False when VPK set differs."""
        cache_meta = {
            "pak01_dir.vpk": {"mtime": 1000, "size": 500},
        }
        current_state = {
            "pak01_dir.vpk": {"mtime": 1000, "size": 500},
            "pak02_dir.vpk": {"mtime": 2000, "size": 600},
        }
        self.assertFalse(self.strategy.is_valid(cache_meta, current_state))

    def test_is_valid_empty_dicts(self) -> None:
        """is_valid returns True when both dicts are empty."""
        self.assertTrue(self.strategy.is_valid({}, {}))


class TestHashStrategy(unittest.TestCase):
    """Verify HashStrategy cache validation logic."""

    def setUp(self) -> None:
        self.strategy = HashStrategy()

    def test_strategy_name(self) -> None:
        """HashStrategy class name is correct."""
        self.assertEqual(type(self.strategy).__name__, "HashStrategy")

    def test_is_valid_matching(self) -> None:
        """is_valid returns True when sha256 hashes match."""
        cache_meta = {
            "addon1.vpk": {"sha256": "abc123"},
            "addon2.vpk": {"sha256": "def456"},
        }
        current_state = {
            "addon1.vpk": {"sha256": "abc123"},
            "addon2.vpk": {"sha256": "def456"},
        }
        self.assertTrue(self.strategy.is_valid(cache_meta, current_state))

    def test_is_valid_hash_mismatch(self) -> None:
        """is_valid returns False when sha256 differs."""
        cache_meta = {
            "addon1.vpk": {"sha256": "abc123"},
        }
        current_state = {
            "addon1.vpk": {"sha256": "zzz999"},
        }
        self.assertFalse(self.strategy.is_valid(cache_meta, current_state))

    def test_is_valid_key_mismatch(self) -> None:
        """is_valid returns False when VPK keys differ."""
        cache_meta = {
            "addon1.vpk": {"sha256": "abc123"},
        }
        current_state = {
            "addon2.vpk": {"sha256": "abc123"},
        }
        self.assertFalse(self.strategy.is_valid(cache_meta, current_state))

    def test_is_valid_empty_dicts(self) -> None:
        """is_valid returns True when both dicts are empty."""
        self.assertTrue(self.strategy.is_valid({}, {}))


if __name__ == "__main__":
    unittest.main()
