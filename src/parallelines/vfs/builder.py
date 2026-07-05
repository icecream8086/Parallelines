"""VfsBuilder: orchestrates gameinfo parsing, VPK scanning, VFS construction, and SSD caching."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from parallelines.cache.manager import CacheManager

try:
    import pandas as pd

    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    pd = None  # type: ignore[assignment]
from parallelines.config import AppConfig, load_config
from parallelines.exceptions import ParseError
from parallelines.parsers.gameinfo import (
    parse_gameinfo,
    extract_search_paths,
    extract_game_dirs,
    extract_addon_roots,
)
from parallelines.parsers.vpk_parser import parse_vpk_index
from parallelines.types import FileNode
from parallelines.vfs.filesystem import VirtualFileSystem

try:
    from tqdm import tqdm  # type: ignore[import-untyped]

    HAS_TQDM = True
except ImportError:  # pragma: no cover
    HAS_TQDM = False

logger = logging.getLogger(__name__)


def _parse_vpk_worker(args: tuple) -> tuple:
    """Worker function for ProcessPool. Standalone to support pickling.

    Receieves ``(vpk_path_str, name, priority)`` and returns
    ``(name, priority, entries_list, error_or_none)``. Returns the
    exception message as the fourth element when parsing fails so
    the caller can log the failure reason.
    """
    vpk_path_str, name, priority = args
    try:
        from parallelines.parsers.vpk_parser import parse_vpk_index

        entries = parse_vpk_index(vpk_path_str)
    except Exception as exc:
        return (name, priority, [], str(exc))
    return (name, priority, entries, None)


class VfsBuilder:
    """Builds a resolved :class:`VirtualFileSystem` from a **Source Engine** game root.

    Only supports Source Engine games (L4D2, CS:GO, TF2, Portal 2, etc.).
    Does NOT support Respawn-modified VPKs or non-Source .vpk files.

    Supports SSD caching via :class:`~parallelines.cache.manager.CacheManager`:
    VPK file lists are persisted as Parquet files so subsequent runs skip
    re-parsing when VPK timestamps are unchanged.
    """

    def __init__(
        self,
        game_root: str | Path,
        config: AppConfig | None = None,
        use_cache: bool = True,
        num_workers: int = 0,
    ) -> None:
        self.game_root = Path(game_root).resolve()
        self.config = config if config is not None else load_config()
        self.game = self.config.general.game
        self.use_cache = use_cache
        self.num_workers = num_workers or (
            self.config.general.num_workers if self.config else 0
        )

        cache_dir = self.config.general.cache_dir or "./cache"
        self._cache = CacheManager(Path(cache_dir))
        self._cache_hit = False
        self.debug = (
            (self.config.general.log_level == "DEBUG") if self.config else False
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def cache_hit(self) -> bool:
        """True if the last :meth:`build` loaded from cache instead of re-parsing."""
        return self._cache_hit

    def build(self) -> VirtualFileSystem:
        """Parse gameinfo, scan all content sources, build and resolve VFS.

        If caching is enabled and the VPK manifest is unchanged from the
        previous run, the VFS is reconstructed from the SSD cache
        (seconds) instead of re-parsing every VPK (tens of seconds).
        """
        t0 = time.perf_counter()

        gameinfo_path = self.game_root / "gameinfo.txt"
        if not gameinfo_path.exists():
            logger.warning("gameinfo.txt not found at %s", gameinfo_path)
            return VirtualFileSystem()

        vfs = VirtualFileSystem()

        # 1 -- Parse gameinfo.txt
        try:
            gameinfo_data = parse_gameinfo(gameinfo_path)
        except ParseError as exc:
            logger.error("Failed to parse gameinfo: %s", exc)
            return vfs

        search_paths = extract_search_paths(gameinfo_data)
        game_dirs = extract_game_dirs(search_paths)
        addon_roots = extract_addon_roots(search_paths)

        # 2 -- Collect VPK manifest for cache validation
        vpk_manifest: list[dict] = self._collect_vpk_manifest(game_dirs, addon_roots)

        # 3 -- Try cache load
        self._cache_hit = False
        if self.use_cache and self._cache.is_valid(vpk_manifest):
            vfs = self._load_from_cache()
            if vfs.get_all_files():
                elapsed = time.perf_counter() - t0
                logger.info(
                    "VFS loaded from cache: %d active files (%.1fs)",
                    len(vfs.get_all_active()),
                    elapsed,
                )
                self._cache_hit = True
                return vfs
            logger.info("Cache was stale or empty, rebuilding ...")

        # 4 -- Full rebuild: scan VPKs and directories
        self._build_from_disk(vfs, game_dirs, addon_roots)
        if HAS_TQDM:
            tqdm.write(
                f"Building dependency graph from {len(vfs.get_all_active())} active files..."
            )  # type: ignore[name-defined]
        vfs.resolve()
        elapsed = time.perf_counter() - t0

        logger.info(
            "VFS built from disk: %d files (%d active) in %.1fs",
            len(vfs.get_all_files()),
            len(vfs.get_all_active()),
            elapsed,
        )

        # 5 -- Save to cache
        if self.use_cache:
            self._save_to_cache(vfs, vpk_manifest)

        return vfs

    def invalidate_cache(self) -> None:
        """Remove all cached VPK analysis data (next run will rebuild)."""
        self._cache.invalidate()
        logger.info("Cache cleared — next run will rebuild from disk")

    def cache_size(self) -> str:
        """Return human-readable cache directory size."""
        total = 0
        for name in ("all_files.parquet", "dependencies.parquet", "meta.json"):
            p = self._cache.cache_dir / name
            if p.exists():
                total += p.stat().st_size
        if total > 1_000_000:
            return f"{total / 1_000_000:.1f} MB"
        elif total > 1_000:
            return f"{total / 1_000:.0f} KB"
        return f"{total} B"

    # ------------------------------------------------------------------
    # Build from disk
    # ------------------------------------------------------------------

    def _build_from_disk(
        self,
        vfs: VirtualFileSystem,
        game_dirs: list[str],
        addon_roots: list[str],
    ) -> None:
        """Full rebuild: scan VPKs and loose files from all game directories."""
        vpk_queue: list[tuple[str, str, int]] = []  # (path_str, name, priority)

        base_priority = 100
        for i, game_dir in enumerate(game_dirs):
            resolved = self._resolve_path(game_dir)
            if resolved is None or not resolved.is_dir():
                continue
            priority = base_priority - i

            for vpk_file in sorted(resolved.glob("*_dir.vpk")):
                vpk_queue.append((str(vpk_file), vpk_file.name, priority))

            # Skip scanning loose files in directories outside game_root (e.g., hl2)
            try:
                resolved.relative_to(self.game_root)
            except ValueError:
                logger.debug("Skipping loose scan for %s (outside game root)", resolved)
                continue

            self._scan_directory(vfs, resolved, resolved, priority)

        # Addons
        addon_priority = 1000
        for addon_root_dir in dict.fromkeys(addon_roots + ["addons"]):
            resolved = self._resolve_path(addon_root_dir)
            if resolved is None or not resolved.is_dir():
                continue
            for vpk_file in sorted(resolved.glob("*.vpk")):
                vpk_queue.append((str(vpk_file), vpk_file.name, addon_priority))
                addon_priority -= 1

        if self.debug:
            logger.debug("Found %d VPK(s) to parse", len(vpk_queue))

        # Parse all VPKs (parallel or sequential)
        self._ingest_vpks(vfs, vpk_queue)

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _collect_vpk_manifest(
        self, game_dirs: list[str], addon_roots: list[str]
    ) -> list[dict]:
        """Build a manifest of all discoverable VPKs for cache validation."""
        manifest: list[dict] = []
        seen: set[str] = set()

        for game_dir in game_dirs:
            resolved = self._resolve_path(game_dir)
            if resolved is None or not resolved.is_dir():
                continue
            for vpk_file in sorted(resolved.glob("*_dir.vpk")):
                if vpk_file.name in seen:
                    continue
                seen.add(vpk_file.name)
                try:
                    st = vpk_file.stat()
                except OSError:
                    continue
                manifest.append(
                    {
                        "source_name": vpk_file.name,
                        "name": vpk_file.name,
                        "path": str(vpk_file),
                        "mtime": st.st_mtime,
                        "size": st.st_size,
                    }
                )

        for addon_root_dir in dict.fromkeys(addon_roots + ["addons"]):
            resolved = self._resolve_path(addon_root_dir)
            if resolved is None or not resolved.is_dir():
                continue
            for vpk_file in sorted(resolved.glob("*.vpk")):
                if vpk_file.name in seen:
                    continue
                seen.add(vpk_file.name)
                try:
                    st = vpk_file.stat()
                except OSError:
                    continue
                manifest.append(
                    {
                        "source_name": vpk_file.name,
                        "name": vpk_file.name,
                        "path": str(vpk_file),
                        "mtime": st.st_mtime,
                        "size": st.st_size,
                    }
                )

        return manifest

    def _load_from_cache(self) -> VirtualFileSystem:
        """Reconstruct a VFS from cached Parquet data."""
        vfs = VirtualFileSystem()
        try:
            df = self._cache.load_files()
            if df.empty:
                return vfs

            from parallelines.types import FileNode

            for _, row in df.iterrows():
                node = FileNode(
                    virtual_path=row.get("virtual_path", ""),
                    source_type=row.get("source_type", "vpk"),
                    source_name=row.get("source_name", ""),
                    priority=int(row.get("priority", 0)),
                    file_size=int(row.get("file_size", 0)),
                    file_hash=row.get("file_hash"),
                    is_enabled=bool(row.get("is_enabled", True)),
                )
                vfs.add_file(node)

            vfs.resolve()

            # Load dependency edges from cache and apply to active nodes
            # so GraphBuilder can use them without re-extracting from file content.
            edges_df = self._cache.load_edges()
            if edges_df is not None and not edges_df.empty:
                for _, edge_row in edges_df.iterrows():
                    from_path = edge_row.get("from", "")
                    to_path = edge_row.get("to", "")
                    if from_path and to_path:
                        active_node = vfs.get_active_file(from_path)
                        if active_node is not None:
                            active_node.dependencies.add(to_path)
        except Exception as exc:
            logger.warning("Failed to load from cache: %s", exc)
            return VirtualFileSystem()

        return vfs

    def _save_to_cache(self, vfs: VirtualFileSystem, vpk_manifest: list[dict]) -> None:
        """Persist the VFS to Parquet cache."""
        try:
            records: list[dict] = []
            for node in vfs.get_all_files():
                records.append(
                    {
                        "virtual_path": node.virtual_path.encode(
                            "utf-8", errors="replace"
                        ).decode("utf-8"),
                        "source_type": node.source_type,
                        "source_name": node.source_name.encode(
                            "utf-8", errors="replace"
                        ).decode("utf-8"),
                        "priority": node.priority,
                        "file_size": node.file_size,
                        "file_hash": node.file_hash or "",
                        "is_enabled": node.is_enabled,
                    }
                )

            files_df = pd.DataFrame(records)

            # Collect dependency edges from active FileNodes
            edge_records: list[dict[str, str]] = []
            for node in vfs.get_all_active():
                for dep in node.dependencies:
                    edge_records.append({"from": node.virtual_path, "to": dep})
            edges_df = (
                pd.DataFrame(edge_records)
                if edge_records
                else pd.DataFrame(columns=["from", "to"])
            )

            meta = {
                "version": "1.0",
                "game_root": str(self.game_root),
                "game": self.game,
                "entry_count": len(records),
                "entries": {
                    e["source_name"]: {
                        "mtime": e.get("mtime", 0),
                        "size": e.get("size", 0),
                    }
                    for e in vpk_manifest
                },
            }

            self._cache.save(files_df, edges_df, meta)
            logger.info(
                "Cache saved: %d entries, %s",
                len(records),
                self.cache_size(),
            )
        except Exception as exc:
            logger.warning("Failed to save cache: %s", exc)

    # ------------------------------------------------------------------
    # FileSystemChain (for srctools-based content reading during graph building)
    # ------------------------------------------------------------------

    def get_chain(self):
        """Build and return a :class:`srctools.filesys.FileSystemChain`.

        The chain combines all discovered VPKs into a single virtual file
        system that can be used by :class:`~parallelines.graph.GraphBuilder`
        to read file content (e.g. parsing ``.mdl`` / ``.nut`` / ``.vmt`` files).

        Returns ``None`` if ``srctools.filesys`` is not available.
        """
        try:
            from srctools.filesys import FileSystemChain, VPKFileSystem
        except ImportError:
            return None

        chain = FileSystemChain()
        seen: set[str] = set()

        def _add_vpk(vpk_path: Path) -> None:
            if not vpk_path.is_file() or vpk_path.name in seen:
                return
            seen.add(vpk_path.name)
            try:
                chain.add_sys(VPKFileSystem(str(vpk_path)))
            except Exception as exc:
                logger.debug("Failed to add VPK to chain %s: %s", vpk_path.name, exc)

        # Main game VPKs
        for vpk_file in sorted(self.game_root.glob("*_dir.vpk")):
            _add_vpk(vpk_file)

        # Addon VPKs
        addons_dir = self.game_root / "addons"
        if addons_dir.is_dir():
            for vpk_file in sorted(addons_dir.glob("*.vpk")):
                _add_vpk(vpk_file)

        # 不添加 loose files RawFileSystem — 依赖提取只需要 VPK 里的文件，
        # 整个游戏目录 (~13GB) 的 RawFileSystem 会吃掉几十 GB 内存。
        return chain

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ingest_vpk(
        self, vfs: VirtualFileSystem, vpk_path: Path, priority: int
    ) -> None:
        """Parse a single VPK and add all its files to the VFS."""
        try:
            entries = parse_vpk_index(vpk_path)
        except ParseError as exc:
            logger.warning("Skipping VPK %s: %s", vpk_path.name, exc)
            return

        source_name = vpk_path.name
        self._add_vpk_entries(vfs, source_name, priority, entries)
        logger.debug("Ingested %s: %d files", source_name, len(entries))

    def _add_vpk_entries(
        self,
        vfs: VirtualFileSystem,
        source_name: str,
        priority: int,
        entries: list[dict],
    ) -> None:
        """Add parsed VPK entries to the VFS. Must be called from the main process."""
        for entry in entries:
            node = FileNode(
                virtual_path=entry["virtual_path"],
                source_type="vpk",
                source_name=source_name,
                priority=priority,
                file_size=entry.get("file_size", 0),
                file_hash=entry.get("crc"),
            )
            vfs.add_file(node)

    def _ingest_vpks(
        self,
        vfs: VirtualFileSystem,
        vpk_queue: list[tuple[str, str, int]],
    ) -> None:
        """Parse multiple VPKs and add their entries to the VFS.

        Uses parallel processing via ``multiprocessing.Pool`` when the number
        of VPKs is large enough (>= 3) and ``num_workers`` is not 1 (single-
        process mode).  Falls back to sequential parsing otherwise, which is
        faster for small batches.

        Each worker calls :func:`parse_vpk_index` and returns raw entry dicts.
        FileNode creation and VFS mutation happen in the main process (since
        ``FileNode`` is not picklable).

        Args:
            vfs: The :class:`~parallelines.vfs.filesystem.VirtualFileSystem`
                to populate.
            vpk_queue: List of ``(path_str, name, priority)`` tuples.
        """
        if not vpk_queue:
            return

        use_parallel = self.num_workers != 1 and len(vpk_queue) >= 3

        if use_parallel:
            from multiprocessing import Pool

            n = self.num_workers if self.num_workers > 0 else None
            logger.info(
                "Parsing %d VPK(s) in parallel (%s worker(s)) ...",
                len(vpk_queue),
                n if n is not None else "auto",
            )
            with Pool(n) as pool:
                failed_count = 0
                for name, priority, entries, error in pool.imap_unordered(
                    _parse_vpk_worker, vpk_queue
                ):
                    if error:
                        logger.warning("Failed to parse VPK %s: %s", name, error)
                        failed_count += 1
                    if entries:
                        self._add_vpk_entries(vfs, name, priority, entries)
                if failed_count:
                    logger.warning(
                        "%d VPK(s) failed to parse during parallel ingestion",
                        failed_count,
                    )
        else:
            if HAS_TQDM:
                vpk_iter = tqdm(  # type: ignore[name-defined]
                    vpk_queue, desc="Parsing VPKs", unit="vpk", disable=None
                )
            else:
                vpk_iter = vpk_queue
            for path_str, _name, priority in vpk_iter:
                self._ingest_vpk(vfs, Path(path_str), priority)

    def _scan_directory(
        self,
        vfs: VirtualFileSystem,
        base_dir: Path,
        current_dir: Path,
        priority: int,
    ) -> None:
        """Recursively scan a directory for loose files."""
        try:
            for fpath in current_dir.iterdir():
                if fpath.is_file():
                    try:
                        rel = fpath.relative_to(base_dir)
                    except ValueError:
                        continue
                    node = FileNode(
                        virtual_path=rel.as_posix(),
                        source_type="game",
                        source_name="base",
                        priority=priority,
                        file_size=fpath.stat().st_size,
                    )
                    vfs.add_file(node)
                elif fpath.is_dir() and fpath.name not in ("bin", ".git"):
                    self._scan_directory(vfs, base_dir, fpath, priority)
        except PermissionError:
            pass

    def _resolve_path(self, search_path: str) -> Path | None:
        """Resolve a gameinfo search path token to an absolute Path.

        Handles ``|gameinfo_path|`` prefix.  Returns ``None`` if the resolved
        path does not exist.
        """
        path_str = search_path.replace("|gameinfo_path|", str(self.game_root))
        resolved = Path(path_str)
        if not resolved.is_absolute():
            resolved = self.game_root / resolved
        return resolved.resolve() if resolved.exists() else None
