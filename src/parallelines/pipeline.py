"""VFS → Graph → Analysis orchestration pipeline.

Extracted from the God Module ``cli.py`` (Phase 4 of I/O audit refactoring).
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

from parallelines.analysis.engine import AnalyzerEngine
from parallelines.analysis.entry_points import (
    discover_entry_points,
    filter_entry_points,
)
from parallelines.cli_args import get_check_extensions
from parallelines.config import AppConfig, default_cache_dir
from parallelines.engine import ResultStore
from parallelines.i18n import _
from parallelines.graph.builder import GraphBuilder
from parallelines.sys_utils import check_memory_available
from parallelines.vfs.builder import VfsBuilder

logger = logging.getLogger(__name__)


# ── Public API ────────────────────────────────────────────────


def apply_check_filters(store: ResultStore, args) -> None:
    """Apply --check-* filters in-place by selecting rows from relevant relations."""
    exts = get_check_extensions(args)
    if exts is None:
        return

    ext_tuple = tuple(exts)

    if store.hash_conflicts:
        store.hash_conflicts = store.hash_conflicts.select(
            lambda r: r.virtual_path.lower().endswith(ext_tuple)
        )
    if store.dep_conflicts:
        store.dep_conflicts = store.dep_conflicts.select(
            lambda r: (
                r.from_path.lower().endswith(ext_tuple) or r.to_path.lower().endswith(ext_tuple)
            )
        )


def print_summary_from_store(store: ResultStore) -> None:
    """从 ResultStore 生成 CLI 摘要表。"""
    from prettytable import PrettyTable

    summary = PrettyTable()
    summary.title = _("report.summary")
    summary.field_names = [_("report.analyzer"), _("report.issues"), _("report.status")]
    summary.align = "l"

    fragments = [
        ("analyzer.redundancy", store.files.select(lambda r: r.is_redundant) if store.files else None),
        ("analyzer.dead_file", store.files.select(lambda r: r.is_dead) if store.files else None),
        ("analyzer.hash_conflict", store.hash_conflicts),
        ("analyzer.dep_conflict", store.dep_conflicts),
        (
            "analyzer.isolated",
            store.isolated.select(lambda r: r.dead_file_count > 0) if store.isolated else None,
        ),
        ("analyzer.impact", store.impact),
    ]

    for key, rel in fragments:
        count = len(rel) if rel is not None else 0
        status = _("report.ok") if count == 0 else _("report.found").format(count=count)
        summary.add_row([_(key), str(count), status])

    print(summary)


def build_store(config: AppConfig, args: argparse.Namespace) -> tuple[ResultStore | None, Any]:
    """Build VFS, graph, and run analyzers → return (store, vfs).

    Shared pipeline used by ``cmd_analyze`` and ``cmd_external``.
    Returns (None, None) on fatal error (gameinfo.txt missing, etc.).
    """
    if not config.general.game_root:
        logger.error("--game-root is required for analysis")
        return None, None

    game_root = Path(config.general.game_root).resolve()
    if not (game_root / "gameinfo.txt").exists():
        logger.error("gameinfo.txt not found in %s", game_root)
        return None, None

    # 0 -- Resolve resource limits
    num_workers = config.general.num_workers
    if getattr(args, "nolimit", False):
        num_workers = 0
    elif getattr(args, "cpu", None) is not None:
        num_workers = args.cpu

    check_memory_available(config, logger)

    # 1 -- Build VFS (with optional cache)
    use_cache = not getattr(args, "no_cache", False)

    # Cold-build confirmation — first run or --no-cache can take 2-3 min of heavy I/O.
    if not getattr(args, "yes", False):
        cache_dir = Path(config.general.cache_dir or default_cache_dir())
        cache_ready = (
            use_cache
            and (cache_dir / "meta.json").exists()
            and (cache_dir / "all_files.parquet").exists()
            and (cache_dir / "dependencies.parquet").exists()
        )
        if not cache_ready:
            print()
            print("=" * 60)
            print(f"  {_('pipeline.cold_boot.title')}")
            print()
            if not use_cache:
                print(f"  {_('pipeline.cold_boot.no_cache')}")
            else:
                print(f"  {_('pipeline.cold_boot.first_run')}")
            print(f"  {_('pipeline.cold_boot.eta')}")
            print()
            print(f"  {_('pipeline.cold_boot.hint')}")
            print("=" * 60)
            try:
                answer = input(f"  {_('pipeline.cold_boot.confirm')}").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print(f"\n  {_('pipeline.cold_boot.cancelled')}")
                return None, None
            if answer != "y":
                print(f"  {_('pipeline.cold_boot.cancelled')} {_('pipeline.cold_boot.skip_hint')}")
                return None, None
            print()

    builder = VfsBuilder(game_root, config, use_cache=use_cache, num_workers=num_workers)

    if getattr(args, "clean_cache", False):
        builder.invalidate_cache()

    logger.info("Building VFS from '%s' (game=%s) ...", game_root, config.general.game)
    vfs = builder.build()

    if builder.cache_hit:
        logger.info(
            "VFS loaded from SSD cache (%s) -- use --no-cache to force rebuild",
            builder.cache_size(),
        )
        logger.info("  清理缓存: python -m parallelines ... analyze --clean-cache")
    else:
        logger.info("VFS built from disk, cache saved (%s)", builder.cache_size())

    logger.info("VFS ready: %d active files", len(vfs.get_all_active()))

    # 2 -- Build dependency graph (fast-path from cache when available)
    logger.info("Building dependency graph ...")
    if builder.cache_hit:
        graph = GraphBuilder.build_from_cached(vfs)
        chain = None  # not needed -- deps already in node.dependencies
        logger.info(
            "Graph built from cache: %d nodes, %d edges",
            graph.node_count,
            graph.edge_count,
        )
    else:
        logger.info("Building file system chain ...")
        chain = builder.get_chain()
        if chain is not None:
            vpk_count = sum(1 for s in chain.systems if "vpk" in str(type(s[0])).lower())
            logger.info("FileSystemChain ready (%d VPKs in chain)", vpk_count)
            graph = GraphBuilder(chain, vfs, debug=(config.general.log_level == "DEBUG")).build()
            logger.info(
                "Graph ready: %d nodes, %d edges",
                graph.node_count,
                graph.edge_count,
            )
            # Persist edges to cache so next run can skip chain + I/O.
            builder.save_edges(vfs)
        else:
            logger.warning("srctools FileSystem not available; graph will be empty")
            graph = None

    # 3a -- Generate Graphviz .dot if requested
    if getattr(args, "graphviz", None) and graph is not None:
        from parallelines.report.graphviz import generate_dot

        dot_path = generate_dot(graph, args.graphviz)
        logger.info("Graphviz .dot saved to %s", dot_path)

    # 3 -- Discover entry points (unless user provided explicit ones)
    if getattr(args, "entry_points", None):
        entry_points = set(args.entry_points)
    else:
        entry_points = discover_entry_points(vfs, chain=chain, game=config.general.game)

    # 3b -- If --maps was provided, expand to maps/{name}.bsp and add to set.
    if getattr(args, "maps", None):
        for map_name in args.maps:
            map_path = f"maps/{map_name}.bsp"
            entry_points.add(map_path)
            logger.debug("cmd_analyze: added map entry point '%s'", map_path)
        logger.info("Added %d map entry point(s) from --maps", len(args.maps))

    # 3c -- Filter entry points: remove those with no outgoing edges.
    if entry_points and graph is not None:
        entry_points = filter_entry_points(entry_points, vfs, graph)

    if entry_points:
        logger.info(
            "Entry points: %d (%s)",
            len(entry_points),
            ", ".join(sorted(entry_points)[:5]),
        )
    else:
        logger.info("No entry points -- dead file analysis will be skipped")

    # 4 -- Run analyzers via AnalyzerEngine
    base_paths = (
        {n.virtual_path for n in vfs.get_all_active() if n.source_type == "game"} if vfs else set()
    )
    engine = AnalyzerEngine.from_config(
        config, entry_points=entry_points, chain=chain, base_paths=base_paths,
    )

    # 4b -- Map version conflict analysis
    if getattr(args, "compare_maps", None):
        from parallelines.analysis.map_conflict import MapConflictAnalyzer
        from parallelines.parsers.vpk_parser import parse_vpk_index

        external_maps: dict[str, str] = {}
        for vpk_arg in args.compare_maps:
            vpk_path = Path(vpk_arg)
            if not vpk_path.exists():
                vpk_path = Path.cwd() / vpk_arg
            if not vpk_path.exists():
                logger.warning("VPK not found: %s", vpk_arg)
                continue
            entries = parse_vpk_index(str(vpk_path))
            for e in entries:
                p = e.get("virtual_path", "")
                if p.lower().endswith(".bsp"):
                    external_maps[p] = vpk_path.name

        if not external_maps:
            logger.warning("No .bsp found in specified VPKs")
        else:
            logger.info(
                "Map conflict analysis: %d maps from %d VPK(s)",
                len(external_maps),
                len(args.compare_maps),
            )
            engine.register(
                MapConflictAnalyzer(
                    target_maps=set(external_maps.keys()),
                    external_sources=external_maps,
                )
            )

    # 5 -- Create store and run analyzers
    store = ResultStore.from_analysis(
        vfs=vfs,
        graph=graph,
        analyzers=[],
        entry_points=entry_points,
        addon_manifests=None,
    )
    store = engine.run(vfs, graph, store)

    # sv_pure whitelist integration (runs for all modes)
    whitelist_path = (
        getattr(args, "sv_pure", None) or config.entry_points.pure_server_whitelist_path
    )
    if whitelist_path:
        from parallelines.analysis.pure_whitelist import (
            filter_vfs_by_whitelist,
            load_pure_whitelist,
        )

        whitelist = load_pure_whitelist(whitelist_path)
        if whitelist:
            allowed_nodes = filter_vfs_by_whitelist(vfs.get_all_files(), whitelist)
            allowed_paths = {n.virtual_path for n in allowed_nodes}
            blocked_count = 0
            for fr in store.files.rows if store.files else []:
                if fr.virtual_path not in allowed_paths:
                    fr.is_pure_allowed = False
                    blocked_count += 1
            logger.info(
                "sv_pure whitelist applied: %d allowed, %d blocked",
                len(allowed_nodes),
                blocked_count,
            )

    return store, vfs
