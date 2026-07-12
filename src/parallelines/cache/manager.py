"""CacheManager — Parquet-based SSD cache for parsed VPK data."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from parallelines.cache.strategies import CacheStrategy, MtimeStrategy
from parallelines.error_policy import cache_write_failure
from parallelines.io import FileReader, FileWriter

logger = logging.getLogger(__name__)

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

    # Parser version — increment each time a new parser is added or an existing
    # parser changes its extraction logic.  Old caches are invalidated so the
    # dependency graph is guaranteed complete.
    PARSER_VERSION = 2

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
            cache_meta: dict = FileReader.read_json(meta_path)
        except (json.JSONDecodeError, OSError, FileNotFoundError):
            return False

        # Check parser version — invalidate when parsers have changed.
        if cache_meta.get("parser_version", 0) < self.PARSER_VERSION:
            return False

        # Extract the entries sub-dict for per-VPK comparison.
        cached_entries: dict = cache_meta.get("entries", {})

        current_state: dict = {}
        for vpk in vpk_list:
            # Use full path as primary key — name alone collides when the same
            # VPK file name appears in multiple directories (e.g. pak01_dir.vpk
            # in both left4dead2/ and hl2/).
            key = vpk.get("path") or vpk.get("source_name") or vpk.get("name", "")
            key = key.replace("\\", "/")
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

    def save(self, files_df, meta: dict, edges_df=None) -> None:
        """Persist analysis results to Parquet cache.

        Silently skips when pandas is not available (minimal build),
        in which case the next run will rebuild from disk.

        Args:
            files_df: DataFrame of file entries (saved to all_files.parquet).
            meta: Metadata dict (saved to meta.json).
            edges_df: Optional DataFrame of dependency edges. When None,
                dependencies.parquet is skipped (edges are saved separately
                via :meth:`save_edges` after GraphBuilder finishes).
        """
        if not HAS_PANDAS:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            files_df.to_parquet(self.cache_dir / "all_files.parquet")
            if edges_df is not None:
                edges_df.to_parquet(self.cache_dir / "dependencies.parquet")
        except Exception as exc:
            cache_write_failure(exc)
            return
        meta["parser_version"] = self.PARSER_VERSION
        meta_path = self.cache_dir / "meta.json"
        FileWriter.write_json(meta_path, meta)

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
        except Exception as exc:
            cache_write_failure(exc)
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
