"""Property tests for CacheManager edge-cache integrity (Bug B5).

Bug B5 root cause
-----------------
``_save_to_cache()`` in ``vfs/builder.py`` creates an empty edges DataFrame
(``pd.DataFrame(columns=["from", "to"])``) and calls ``self._cache.save()``,
which writes that empty DataFrame to ``dependencies.parquet``.  Later,
``save_edge_cache()`` overwrites it with real edges.  If the process crashes
between the two writes, the cache contains an empty edge table, producing
spurious "no dependencies" results on the next run.

These tests verify that:

1.  A normal save/load round-trip preserves edge counts correctly.
2.  Saving an empty edge table then loading it back **does** return empty
    (confirming the B5 window exists -- this test currently PASSES, which
    is the buggy behaviour; a fix would need to make the intermediate state
    detectable or atomic).
3.  Calling ``save_edges()`` twice with the same data produces identical
    files on disk (idempotency).
4.  ``invalidate()`` removes all three cache files, leaving no stale data.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from parallelines.cache.manager import CacheManager


def _cache_manager(tmp_path: Path) -> CacheManager:
    """Build a CacheManager rooted at *tmp_path*."""
    return CacheManager(tmp_path / ".cache")


def _sample_edges() -> pd.DataFrame:
    """Return a small non-empty edges DataFrame."""
    return pd.DataFrame({
        "from": ["materials/wall.vmt", "materials/floor.vmt"],
        "to":   ["materials/wall.vtf",  "materials/floor.vtf"],
    })


def _sample_files() -> pd.DataFrame:
    """Return a minimal non-empty files DataFrame."""
    return pd.DataFrame({
        "virtual_path": ["materials/wall.vmt"],
        "source_type":  ["vpk"],
        "source_name":  ["pak01_dir.vpk"],
        "priority":     [100],
        "file_size":    [512],
        "file_hash":    ["abc123"],
        "is_enabled":   [True],
    })


def _sample_meta() -> dict:
    """Return a minimal metadata dict."""
    return {"version": "1.0", "entries": {}}


class TestEdgeCacheIntegrity:
    """Edge-cache integrity properties."""

    # ------------------------------------------------------------------
    # Test 1 — Round-trip preserves edge count
    # ------------------------------------------------------------------
    def test_edge_cache_round_trip(self, tmp_path: Path) -> None:
        """Save non-empty edges, load them back, verify count matches."""
        mgr = _cache_manager(tmp_path)
        files = _sample_files()
        edges = _sample_edges()

        mgr.save(files, edges, _sample_meta())

        loaded = mgr.load_edges()
        assert len(loaded) == len(edges)
        assert list(loaded.columns) == ["from", "to"]

        # Verify the actual content round-trips correctly.
        pd.testing.assert_frame_equal(loaded.reset_index(drop=True),
                                       edges.reset_index(drop=True))

    # ------------------------------------------------------------------
    # Test 2 — Empty edges via save() (confirms B5 window)
    # ------------------------------------------------------------------
    def test_edge_cache_without_save_edge_call(self, tmp_path: Path) -> None:
        """Save with empty edges via save(), load back -- edges are empty.

        This test **passes** under the current buggy code, confirming that
        the ``B5`` crash window exists: ``save()`` writes an empty edge table,
        and nothing distinguishes that state from a legitimate "no edges" run.
        """
        mgr = _cache_manager(tmp_path)
        files = _sample_files()
        empty_edges = pd.DataFrame(columns=["from", "to"])

        mgr.save(files, empty_edges, _sample_meta())

        loaded = mgr.load_edges()
        assert loaded.empty
        assert list(loaded.columns) == ["from", "to"]

    # ------------------------------------------------------------------
    # Test 3 — save_edges() is idempotent
    # ------------------------------------------------------------------
    def test_save_edge_cache_idempotent(self, tmp_path: Path) -> None:
        """Two identical save_edges() calls produce the same file on disk."""
        mgr = _cache_manager(tmp_path)
        edges = _sample_edges()

        # First write via save() to create the cache directory and parquet.
        mgr.save(_sample_files(), edges, _sample_meta())

        edges_path = mgr.cache_dir / "dependencies.parquet"
        digest1 = hashlib.sha256(edges_path.read_bytes()).hexdigest()

        # Second write via save_edges() with the same data.
        mgr.save_edges(edges)

        digest2 = hashlib.sha256(edges_path.read_bytes()).hexdigest()

        assert digest1 == digest2, (
            "save_edges() is not idempotent -- file content differs "
            "between calls"
        )

    # ------------------------------------------------------------------
    # Test 4 — invalidate() removes all cache files
    # ------------------------------------------------------------------
    def test_invalidate_clears_cache(self, tmp_path: Path) -> None:
        """After invalidate(), all three cache files are gone."""
        mgr = _cache_manager(tmp_path)

        # Populate the cache.
        mgr.save(_sample_files(), _sample_edges(), _sample_meta())

        cache_files = [
            mgr.cache_dir / "meta.json",
            mgr.cache_dir / "all_files.parquet",
            mgr.cache_dir / "dependencies.parquet",
        ]

        # Sanity: all exist before invalidation.
        for f in cache_files:
            assert f.exists(), f"Expected {f.name} to exist before invalidate"

        mgr.invalidate()

        for f in cache_files:
            assert not f.exists(), f"Expected {f.name} to be removed after invalidate"

        # The cache directory itself should still exist.
        assert mgr.cache_dir.exists()
