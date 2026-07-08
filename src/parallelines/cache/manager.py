"""CacheManager — Parquet-based SSD cache for parsed VPK data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from parallelines.cache.strategies import CacheStrategy, MtimeStrategy

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    pd = None  # type: ignore[assignment]


class CacheManager:
    """Manages a Parquet-based on-disk cache for parsed VPK analysis results.

    Cache layout under *cache_dir*::

        meta.json               -- VPK metadata for staleness checks
        all_files.parquet       -- DataFrame of all files across VPKs
        dependencies.parquet    -- DataFrame of dependency edges
    """

    def __init__(
        self,
        cache_dir: str | Path,
        strategy: CacheStrategy | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.strategy: CacheStrategy = strategy or MtimeStrategy()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def is_valid(self, vpk_list: list[dict]) -> bool:
        """Check whether the on-disk cache is still usable.

        Loads ``meta.json`` from the cache directory and compares the stored
        metadata against *vpk_list* using the configured *strategy*.

        Returns:
            False if the cache directory is missing, ``meta.json`` cannot be
            read or parsed, or any entry has changed.
        """
        meta_path = self.cache_dir / "meta.json"
        if not meta_path.exists():
            return False

        try:
            with open(meta_path) as f:
                cache_meta: dict = json.load(f)
        except (json.JSONDecodeError, OSError):
            return False

        # Extract the entries sub-dict for per-VPK comparison.
        cached_entries: dict = cache_meta.get("entries", {})

        current_state: dict = {}
        for vpk in vpk_list:
            key = (
                vpk.get("source_name")
                or vpk.get("name")
                or vpk.get("path", "")
            )
            current_state[key] = vpk

        return self.strategy.is_valid(cached_entries, current_state)

    # ------------------------------------------------------------------
    # Load helpers
    # ------------------------------------------------------------------

    def load_files(self):
        """Load the cached files DataFrame.

        Returns:
            DataFrame with file entries, or an empty list if pandas is not
            available or the cache file does not exist.
        """
        if not HAS_PANDAS:
            return []
        path = self.cache_dir / "all_files.parquet"
        try:
            return pd.read_parquet(path)
        except (FileNotFoundError, ValueError):
            return pd.DataFrame() if HAS_PANDAS else []

    def load_edges(self):
        """Load the cached dependency edges DataFrame.

        Returns:
            DataFrame with edges, or empty list if unavailable.
        """
        if not HAS_PANDAS:
            return []
        path = self.cache_dir / "dependencies.parquet"
        try:
            return pd.read_parquet(path)
        except (FileNotFoundError, ValueError):
            return pd.DataFrame() if HAS_PANDAS else []

    # ------------------------------------------------------------------
    # Save / invalidate
    # ------------------------------------------------------------------

    def save(self, files_df, edges_df, meta: dict) -> None:
        """Persist analysis results to Parquet cache.

        Silently skips when pandas is not available (minimal build),
        in which case the next run will rebuild from disk.
        """
        if not HAS_PANDAS:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            files_df.to_parquet(self.cache_dir / "all_files.parquet")
            edges_df.to_parquet(self.cache_dir / "dependencies.parquet")
        except Exception:
            return
        meta_path = self.cache_dir / "meta.json"
        with open(meta_path, "w") as f:
            json.dump(meta, f)

    def save_edges(self, edges_df) -> None:
        """Update only the ``dependencies.parquet`` cache file.

        Called after GraphBuilder has populated node.dependencies, so edges
        are available for the next cache-hit run.
        """
        if not HAS_PANDAS:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            edges_df.to_parquet(self.cache_dir / "dependencies.parquet")
        except Exception:
            return

    def invalidate(self) -> None:
        """Remove all cache files from the cache directory.

        Deletes the three known cache files.  The directory itself is left
        in place.
        """
        for name in ("meta.json", "all_files.parquet", "dependencies.parquet"):
            path = self.cache_dir / name
            if path.exists():
                path.unlink()
