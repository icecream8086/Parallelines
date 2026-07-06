from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

from parallelines.config import load_config, AppConfig
from parallelines.engine import Relation, ResultStore
from parallelines.exceptions import ParallelinesError
from parallelines.report.generators import generate_report_from_store
from parallelines.i18n import set_language, _

logger = logging.getLogger(__name__)

SUPPORTED_GAMES = {
    # 目前已验证可直接使用的游戏
    "l4d2": "Left 4 Dead 2",
    # ── 以下为占位符，逻辑未验证 ──
    "l4d1": "Left 4 Dead (占位)",
    "csgo": "Counter-Strike: Global Offensive (占位)",
    "cs2": "Counter-Strike 2 (占位)",
    "tf2": "Team Fortress 2 (占位)",
    "portal2": "Portal 2 (占位)",
    "portal1": "Portal (占位)",
    "dota2": "Dota 2 (占位)",
    "hl2": "Half-Life 2 (占位)",
    "hl2ep1": "Half-Life 2: Episode One (占位)",
    "hl2ep2": "Half-Life 2: Episode Two (占位)",
    "sdk": "Source SDK / generic (占位)",
}


# ── 资源污染检查过滤器 ─────────────────────────────────────

_CHECK_FILTERS: dict[str, set[str]] = {
    "check_textures": {".vmt", ".vtf", ".tga", ".png", ".jpg"},
    "check_models": {".mdl", ".vvd", ".vtx", ".phy", ".ani"},
    "check_sounds": {".wav", ".mp3", ".ogg"},
    "check_scripts": {".nut", ".nuc"},
    "check_configs": {".cfg", ".txt", ".res"},
    "check_maps": {".bsp"},
    "check_manifests": {"_manifest.txt"},
}


def _get_check_extensions(args: argparse.Namespace) -> set[str] | None:
    """Return file extensions to filter by, or None for all (unfiltered)."""
    exts: set[str] = set()
    for flag, filter_exts in _CHECK_FILTERS.items():
        if getattr(args, flag, False) or args.check_all:
            exts |= filter_exts
    return exts if exts else None


def _apply_check_filters(store: ResultStore, args) -> None:
    """Apply --check-* filters in-place by selecting rows from relevant relations."""
    exts = _get_check_extensions(args)
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
                r.from_path.lower().endswith(ext_tuple)
                or r.to_path.lower().endswith(ext_tuple)
            )
        )


def _get_version() -> str:
    """Return the current version string."""
    try:
        from importlib.metadata import version

        return version("parallelines")
    except Exception:
        return "0.1.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parallelines",
        description="Source Engine VPK/addon resource dependency analysis CLI tool",
        epilog="Supported games: "
        + ", ".join(f"{k}({v})" for k, v in sorted(SUPPORTED_GAMES.items())),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_get_version()}",
    )
    parser.add_argument(
        "--game",
        type=str,
        required=True,
        choices=sorted(SUPPORTED_GAMES.keys()),
        help=f"Source Engine game ID ({', '.join(sorted(SUPPORTED_GAMES.keys()))})",
    )
    parser.add_argument(
        "--game-root",
        type=str,
        default="",
        help="Directory containing gameinfo.txt (e.g. .../common/Left 4 Dead 2/left4dead2 for L4D2)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="",
        help="Path to config.toml (default: ./config.toml)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="Override log level",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enable debug logging and full exception tracebacks",
    )
    parser.add_argument(
        "--cpu",
        type=int,
        default=None,
        help="Max worker processes (default: cpu_count-1, 0=no limit)",
    )
    parser.add_argument(
        "--memory",
        type=str,
        default=None,
        help="Memory limit e.g. 4GB (default: auto, 0=no limit)",
    )
    parser.add_argument(
        "--nolimit",
        action="store_true",
        default=None,
        help="Bypass all resource limits, use maximum available",
    )
    # TUI temporarily disabled
    # parser.add_argument(
    #     "--tui",
    #     action="store_true",
    #     default=False,
    #     help="Launch Textual TUI interface",
    # )
    parser.add_argument(
        "--lang",
        type=str,
        choices=["zh", "en"],
        default=None,
        help="Interface language (default: auto-detect from OS)",
    )

    # analyze mode (flags)
    parser.add_argument(
        "--analyze",
        action="store_true",
        default=False,
        help="Run full analysis on the game environment",
    )
    # ── 资源污染专项检查 (report.md 定义的 11 类问题) ──
    parser.add_argument(
        "--check-textures",
        action="store_true",
        default=False,
        help="材质/贴图冲突 -- .vmt/.vtf 同名哈希比对",
    )
    parser.add_argument(
        "--check-models",
        action="store_true",
        default=False,
        help="模型冲突 -- .mdl/.vvd/.vtx 覆盖检测",
    )
    parser.add_argument(
        "--check-sounds",
        action="store_true",
        default=False,
        help="音效冲突 -- .wav/.mp3 同名覆盖检测",
    )
    parser.add_argument(
        "--check-scripts",
        action="store_true",
        default=False,
        help="脚本冲突 -- .nut 全局函数覆盖风险",
    )
    parser.add_argument(
        "--check-configs",
        action="store_true",
        default=False,
        help="配置污染 -- .cfg 自动执行覆盖检测",
    )
    parser.add_argument(
        "--check-maps",
        action="store_true",
        default=False,
        help="地图完整性 -- .bsp 缺失依赖/版本不匹配",
    )
    parser.add_argument(
        "--check-manifests",
        action="store_true",
        default=False,
        help="清单污染 -- particles/soundscapes manifest 冲突",
    )
    parser.add_argument(
        "--check-all",
        action="store_true",
        default=False,
        help="全部资源污染检查 (等价于以上 --check-* 全开)",
    )
    parser.add_argument(
        "--compare-maps",
        type=str,
        nargs="+",
        default=None,
        metavar="VPK",
        help="地图版本比对: 指定一个或多个 VPK 文件, 提取其中的 .bsp 分析同名冲突",
    )
    parser.add_argument(
        "--external",
        type=str,
        default=None,
        metavar="VPK",
        help="Analyze an external vpk against the current environment",
    )
    parser.add_argument(
        "--repl",
        action="store_true",
        default=False,
        help="Enter interactive REPL mode",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["json", "csv", "text", "html"],
        default=None,
        help="Output format (overrides config)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (overrides config)",
    )
    parser.add_argument(
        "--entry-points",
        type=str,
        nargs="*",
        default=None,
        help="Virtual paths to use as entry points (auto-discovered if omitted)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        default=False,
        help="Force full rebuild, skip SSD cache",
    )
    parser.add_argument(
        "--clean-cache",
        action="store_true",
        default=False,
        help="Delete existing cache and rebuild",
    )
    parser.add_argument(
        "--maps",
        type=str,
        nargs="*",
        default=None,
        help="Specific maps to add as entry points (e.g. c1m1_hotel c2m1_highway)",
    )
    parser.add_argument(
        "--graphviz",
        type=str,
        default=None,
        help="Output path for Graphviz .dot file",
    )
    parser.add_argument(
        "--vpk-priority",
        type=str,
        default="highest",
        choices=["highest", "lowest"],
        help="Simulated priority for the external vpk (used with --external)",
    )
    # --ref-query is a deprecated alias. Users can use --query external_overrides instead.
    parser.add_argument(
        "--ref-query",
        type=str,
        default="all",
        choices=["all", "overrides", "overridden", "new_files"],
        help="[Deprecated: use --query with preset names external_overrides/external_overridden/external_new_files]",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        default=False,
        help="Skip the cold-build confirmation prompt (useful for scripting)",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        metavar="QUERY",
        help="Run a query after analysis: preset name or inline JSON DSL",
    )
    parser.add_argument(
        "--list-presets",
        action="store_true",
        default=False,
        help="List available query presets and exit",
    )
    parser.add_argument(
        "--sv-pure",
        type=str,
        default=None,
        metavar="WHITELIST",
        help="Path to pure_server_whitelist.txt for sv_pure filtering",
    )

    return parser


def print_summary_from_store(store: ResultStore) -> None:
    """从 ResultStore 生成 CLI 摘要表。"""
    from prettytable import PrettyTable

    summary = PrettyTable()
    summary.title = "Analysis Summary"
    summary.field_names = ["Analyzer", "Issues", "Status"]
    summary.align = "l"

    fragments = [
        (
            "Redundancy",
            store.files.select(lambda r: r.is_redundant) if store.files else None,
        ),
        ("DeadFile", store.files.select(lambda r: r.is_dead) if store.files else None),
        ("HashConflict", store.hash_conflicts),
        ("DepConflict", store.dep_conflicts),
        (
            "Isolated",
            store.isolated.select(lambda r: r.dead_file_count > 0)
            if store.isolated
            else None,
        ),
        ("Impact", store.impact),
    ]

    for name, rel in fragments:
        count = len(rel) if rel is not None else 0
        status = "OK" if count == 0 else f"{count} found"
        summary.add_row([name, str(count), status])

    print(summary)


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except KeyboardInterrupt:
        print(f"\n[parallelines] {_('error.interrupted')}")
        return 130
    except ParallelinesError as exc:
        logger.error("%s", exc)
        return 1
    except Exception as exc:
        logger.exception(_("error.unexpected").format(msg=exc))
        return 1


def _main(argv: list[str] | None = None) -> int:
    # Allow --list-presets without --game
    if argv is None:
        argv = sys.argv[1:]
    if "--list-presets" in argv:
        _list_presets()
        return 0

    parser = build_parser()
    args = parser.parse_args(argv)

    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)

    config.general.game = args.game
    if args.game_root:
        config.general.game_root = args.game_root
    if args.log_level:
        config.general.log_level = args.log_level
    if args.format:
        config.output.format = args.format
    if args.output_dir:
        config.output.output_dir = args.output_dir
    if args.cpu is not None:
        config.general.num_workers = args.cpu
    if args.memory is not None:
        config.general.memory_limit = args.memory
    if args.nolimit:
        config.general.nolimit = True
    if args.lang:
        set_language(args.lang)

    if args.debug:
        config.general.log_level = "DEBUG"

    # Resolve effective worker count
    if config.general.nolimit:
        num_workers = 0  # unlimited
    elif config.general.num_workers == 0:
        import os

        num_workers = max(1, (os.cpu_count() or 2) - 1)
    else:
        num_workers = config.general.num_workers

    # Write resolved worker count back to config so downstream components
    # (e.g. VfsBuilder) see the resolved value rather than the raw one.
    config.general.num_workers = num_workers

    logging.basicConfig(
        level=getattr(logging, config.general.log_level.upper(), logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",
    )

    logger.info(
        "Game: %s (%s)",
        config.general.game,
        SUPPORTED_GAMES.get(config.general.game, "Unknown"),
    )
    worker_str = "unlimited" if num_workers == 0 else str(num_workers)
    mem_str = config.general.memory_limit or "auto"
    logger.info("Resources: %s workers, memory=%s", worker_str, mem_str)

    # TUI temporarily disabled
    # if args.tui:
    #     from parallelines.tui.app import ParallelinesTUI
    #
    #     app = ParallelinesTUI(
    #         game=config.general.game,
    #         game_root=config.general.game_root,
    #     )
    #     app.run()
    #     return 0

    if not config.general.game_root:
        parser.print_help()
        print(f"\nError: {_('cli.game_root_required')}")
        return 1

    try:
        if args.analyze:
            return cmd_analyze(config, args)
        elif args.external:
            return cmd_external(config, args)
        elif args.repl:
            from parallelines.repl import ReplSession
            return ReplSession(config, args).run()
        else:
            parser.print_help()
            return 0
    except Exception as exc:
        if config.general.log_level == "DEBUG":
            logger.exception(_("error.unexpected").format(msg=exc))
        else:
            logger.error("%s", exc)
        return 1


def _parse_memory_limit(limit_str: str) -> int | None:
    """Parse a memory limit string into bytes.

    Accepts formats like ``"4GB"``, ``"2048MB"``, ``"0"`` (no limit).
    Returns ``None`` if the string is empty, ``0`` if explicitly disabled,
    or the byte count otherwise.
    """
    if not limit_str:
        return None
    limit_str = limit_str.strip().upper()
    if limit_str == "0":
        return 0
    if limit_str.endswith("GB"):
        try:
            return int(limit_str.removesuffix("GB")) * 1_073_741_824
        except ValueError:
            return None
    if limit_str.endswith("MB"):
        try:
            return int(limit_str.removesuffix("MB")) * 1_048_576
        except ValueError:
            return None
    if limit_str.endswith("KB"):
        try:
            return int(limit_str.removesuffix("KB")) * 1024
        except ValueError:
            return None
    try:
        return int(limit_str)
    except ValueError:
        return None


def _check_memory_available(config: AppConfig, logger: logging.Logger) -> None:
    """Log a warning if ``memory_limit`` is set but cannot be verified.

    This is purely advisory -- actual memory enforcement is left to the OS.
    """
    raw = config.general.memory_limit
    if not raw:
        return
    limit_bytes = _parse_memory_limit(raw)
    if limit_bytes is None:
        logger.warning("Unrecognised memory limit format '%s' -- ignoring", raw)
        return
    if limit_bytes == 0:
        return  # explicitly disabled

    # Try optional psutil first, then platform-specific fallbacks
    mem_available: int | None = None
    try:
        import psutil  # type: ignore[import-untyped]

        mem_available = psutil.virtual_memory().available
    except ImportError:
        pass

    if mem_available is None and sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            mem_status_buf = (ctypes.c_uint8 * 64)()
            # MEMORYSTATUSEX structure: 64 bytes, dwLength + state fields
            ctypes.c_uint64.from_buffer(mem_status_buf).value = 64
            if kernel32.GlobalMemoryStatusEx(mem_status_buf):
                # ullAvailPhys is at offset 8+8 = 16 on x64
                mem_available = ctypes.c_uint64.from_buffer(mem_status_buf, 16).value
        except Exception:
            pass

    if mem_available is None and sys.platform == "linux":
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            mem_available = int(parts[1]) * 1024
                        break
        except Exception:
            pass

    if mem_available is not None and limit_bytes > mem_available:
        logger.warning(
            "Memory limit (%s) exceeds available memory (%s MB) -- "
            "system may swap or OOM",
            raw,
            round(mem_available / 1_048_576),
        )
    elif mem_available is not None and limit_bytes > mem_available * 0.8:
        logger.info(
            "Memory limit (%s) is close to available memory (%s MB)",
            raw,
            round(mem_available / 1_048_576),
        )


def _build_store(
    config: AppConfig, args: argparse.Namespace
) -> tuple[ResultStore | None, Any]:
    """Build VFS, graph, and run analyzers → return (store, vfs).

    Shared pipeline used by ``cmd_analyze`` and ``cmd_external``.
    Returns (None, None) on fatal error (gameinfo.txt missing, etc.).
    """
    from parallelines.analysis.addon_dep import AddonDependencyAnalyzer
    from parallelines.analysis.cascade_detector import CascadeDetector
    from parallelines.analysis.cycle_detector import CycleDetector
    from parallelines.analysis.dead_file import DeadFileAnalyzer
    from parallelines.analysis.dep_conflict import DependencyConflictAnalyzer
    from parallelines.analysis.entry_points import (
        discover_entry_points,
        filter_entry_points,
    )
    from parallelines.analysis.global_script_detector import GlobalScriptDetector
    from parallelines.analysis.hash_conflict import HashConflictAnalyzer
    from parallelines.analysis.implicit_dep_detector import ImplicitDepDetector
    from parallelines.analysis.impact import ImpactAnalyzer
    from parallelines.analysis.isolated import IsolatedPackageAnalyzer
    from parallelines.analysis.mod_classify import ModClassifier
    from parallelines.analysis.redundancy import RedundancyAnalyzer
    from parallelines.graph.builder import GraphBuilder
    from parallelines.vfs.builder import VfsBuilder

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

    _check_memory_available(config, logger)

    # 1 -- Build VFS (with optional cache)
    use_cache = not getattr(args, "no_cache", False)

    # Cold-build confirmation — first run or --no-cache can take 2-3 min of heavy I/O.
    if not getattr(args, "yes", False):
        cache_dir = Path(config.general.cache_dir or "./cache")
        cache_ready = (
            use_cache
            and (cache_dir / "meta.json").exists()
            and (cache_dir / "all_files.parquet").exists()
            and (cache_dir / "dependencies.parquet").exists()
        )
        if not cache_ready:
            print()
            print("=" * 60)
            print("  [!] 冷启动模式 -- 需要读取所有 VPK 文件内容")
            print()
            if not use_cache:
                print("  --no-cache 已指定，将跳过 SSD 缓存重建依赖图。")
            else:
                print("  这是首次运行（或缓存已失效），需要解析 VPK 文件。")
            print("  预计耗时：2–3 分钟，期间磁盘 I/O 会很高。")
            print()
            print("  如果已有缓存，去掉 --no-cache 即可秒级启动。")
            print("=" * 60)
            try:
                answer = input("  确认继续？[y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n  已取消。")
                return None, None
            if answer != "y":
                print("  已取消。使用 --yes 跳过此提示。")
                return None, None
            print()

    builder = VfsBuilder(
        game_root, config, use_cache=use_cache, num_workers=num_workers
    )

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
            graph.node_count, graph.edge_count,
        )
    else:
        logger.info("Building file system chain ...")
        chain = builder.get_chain()
        if chain is not None:
            vpk_count = sum(
                1 for s in chain.systems if "vpk" in str(type(s[0])).lower()
            )
            logger.info("FileSystemChain ready (%d VPKs in chain)", vpk_count)
            graph = GraphBuilder(
                chain, vfs, debug=(config.general.log_level == "DEBUG")
            ).build()
            logger.info(
                "Graph ready: %d nodes, %d edges",
                graph.node_count, graph.edge_count,
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
        entry_points = discover_entry_points(vfs, chain=chain)

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

    # 4 -- Run analyzers via ResultStore pipeline
    base_paths = {n.virtual_path for n in vfs.get_all_active() if n.source_type == "game"} if vfs else set()
    analyzers = [
        RedundancyAnalyzer(),
        DeadFileAnalyzer(entry_points=entry_points if entry_points else None),
        HashConflictAnalyzer(),
        DependencyConflictAnalyzer(),
        IsolatedPackageAnalyzer(),
        ImpactAnalyzer(top_n=20),
        CycleDetector(),
        CascadeDetector(),
        GlobalScriptDetector(),
        ImplicitDepDetector(),
        ModClassifier(base_paths=base_paths),
    ]

    # 4a -- Addon dependency checking (requires addoninfo.txt in VFS)
    analyzers.append(AddonDependencyAnalyzer(chain=chain))

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
            analyzers.append(
                MapConflictAnalyzer(
                    target_maps=set(external_maps.keys()),
                    external_sources=external_maps,
                )
            )

    store = ResultStore.from_analysis(
        vfs=vfs,
        graph=graph,
        analyzers=analyzers,
        entry_points=entry_points,
        addon_manifests=None,
    )

    return store, vfs


def cmd_analyze(config: AppConfig, args: argparse.Namespace) -> int:
    """Run full analysis: build VFS, build dep graph, run analyzers, output report."""
    store, vfs = _build_store(config, args)
    if store is None:
        return 1

    # 4c -- sv_pure whitelist integration
    whitelist_path = args.sv_pure or config.entry_points.pure_server_whitelist_path
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
            for fr in (store.files.rows if store.files else []):
                if fr.virtual_path not in allowed_paths:
                    fr.is_pure_allowed = False
                    blocked_count += 1
            logger.info(
                "sv_pure whitelist applied: %d allowed, %d blocked",
                len(allowed_nodes),
                blocked_count,
            )

    # 5 -- Apply resource pollution filter (if --check-* flag given)
    _apply_check_filters(store, args)

    # 5b -- Sort impact by impact_count descending
    if store.impact and store.impact.rows:
        store.impact.rows.sort(key=lambda r: r.impact_count, reverse=True)

    # 6 -- Console summary
    print_summary_from_store(store)

    # 7 -- Save full report
    output_dir = config.output.output_dir or "./reports"
    output_format = config.output.format or "json"
    path = generate_report_from_store(store, output_format, output_dir)
    logger.info("Full report saved to %s", path)

    # 8 -- Run inline query if --query was specified
    if getattr(args, "query", None):
        _run_query_and_print(store, args.query)

    return 0


def cmd_external(config: AppConfig, args: argparse.Namespace) -> int:
    """Analyze an external VPK against the current environment using the query engine."""
    # 1 -- Full analysis pipeline
    store, _vfs = _build_store(config, args)
    if store is None:
        return 1

    # 2 -- Resolve external VPK path
    vpk_path = Path(args.external)
    if not vpk_path.is_absolute():
        vpk_path = Path.cwd() / vpk_path
    vpk_path = vpk_path.resolve()
    if not vpk_path.exists():
        logger.error("External VPK file not found: %s", vpk_path)
        return 1

    # 3 -- Map CLI priority string to integer
    priority = 2000 if args.vpk_priority == "highest" else -100
    ref_name = vpk_path.stem

    # 4 -- Load external VPK into store
    try:
        store.load_reference(ref_name, str(vpk_path), priority=priority)
    except ParallelinesError as e:
        logger.error("%s", e)
        return 1

    ext_count = len(store.external_files) if store.external_files else 0
    logger.info(
        "External VPK '%s' loaded: %d files at priority %d (%s)",
        vpk_path.name, ext_count, priority, args.vpk_priority,
    )

    # 5 -- Run queries using the generic query mechanism
    query_name = getattr(args, "ref_query", "all")
    if query_name == "all":
        queries_to_run = ["external_overrides", "external_overridden", "external_new_files"]
    else:
        # Map old names to new JSON preset names
        name_map = {
            "overrides": "external_overrides",
            "overridden": "external_overridden",
            "new_files": "external_new_files",
        }
        queries_to_run = [name_map.get(query_name, query_name)]

    import json as _json
    results: dict[str, Relation] = {}
    for qname in queries_to_run:
        queries_dir = _find_queries_dir()
        preset_path = queries_dir / f"{qname}.json"
        if preset_path.is_file():
            query_dict = _json.loads(preset_path.read_text(encoding="utf-8"))
            try:
                results[qname] = store.execute(query_dict)
            except Exception as e:
                logger.warning("Query '%s' failed: %s", qname, e)
                # Fallback to empty relation
                results[qname] = Relation(qname, ("virtual_path",), [])
        else:
            logger.warning("Query preset '%s' not found", qname)
            results[qname] = Relation(qname, ("virtual_path",), [])

    # 6 -- Console output
    _print_reference_results(results, ref_name, vpk_path.name, ext_count)

    # 7 -- Save report (JSON)
    output_dir = Path(config.output.output_dir or "./reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    import json
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"parallelines_external_{ref_name}_{timestamp}.json"
    report_data: dict = {
        "external_vpk": vpk_path.name,
        "ref_name": ref_name,
        "total_files": ext_count,
        "priority": priority,
    }
    for qname, rel in results.items():
        report_data[qname] = [dict(zip(rel.columns, r)) for r in rel.rows]
    output_path.write_text(
        json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("External VPK report saved to %s", output_path)

    # 8 -- Run inline query if --query was specified
    if getattr(args, "query", None):
        _run_query_and_print(store, args.query)

    return 0




def _print_reference_results(
    results: dict[str, Relation],
    ref_name: str,
    vpk_filename: str,
    ext_count: int,
) -> None:
    """Print external VPK reference analysis results as PrettyTables."""
    from prettytable import PrettyTable

    print(f"\n{'='*60}")
    print(f"  External VPK: {vpk_filename}  (ref: {ref_name})")
    print(f"  Total files in VPK: {ext_count}")
    print(f"{'='*60}\n")

    for qname, rel in results.items():
        count = len(rel)
        label = {
            "external_overrides": "OVERRIDES (external wins)",
            "external_overridden": "OVERRIDDEN (current wins)",
            "external_new_files": "NEW FILES (no conflict)",
        }.get(qname, qname)

        table = PrettyTable()
        table.title = f"{label}: {count} files"
        table.field_names = list(rel.columns)
        table.align = "l"
        for row in rel.rows:
            if isinstance(row, tuple):
                table.add_row([str(v) for v in row])
            else:
                table.add_row([str(getattr(row, c)) for c in rel.columns])
        print(table)
        print()


# ── Generic query runner (--query / --list-presets) ────────────────


def _find_queries_dir() -> Path:
    """Locate the ``queries/`` directory (project root, cwd, or next to the exe)."""
    from pathlib import Path as _Path
    import sys as _sys

    # When frozen (PyInstaller onedir), queries/ is inside _internal/ next to exe.
    if getattr(_sys, "frozen", False):
        exe_dir = _Path(_sys.executable).resolve().parent
        for sub in ("queries", "_internal/queries"):
            candidate = exe_dir / sub
            if candidate.is_dir():
                return candidate

    # Development: project root (3 levels up from this file in src/parallelines/).
    dev_root = _Path(__file__).resolve().parent.parent.parent
    candidate = dev_root / "queries"
    if candidate.is_dir():
        return candidate

    # Fallback: current working directory.
    return _Path.cwd() / "queries"


def _list_presets() -> None:
    """Print available query presets from the ``queries/`` directory."""
    import json as _json

    queries_dir = _find_queries_dir()
    if not queries_dir.is_dir():
        print(f"No queries/ directory found (looked in: {queries_dir})")
        return

    presets = sorted(
        p for p in queries_dir.glob("*.json") if p.name != "README.md"
    )
    if not presets:
        print("No presets found in queries/.")
        return

    print(f"\n{'='*60}")
    print(f"  Available query presets ({len(presets)}):")
    print(f"{'='*60}")
    for p in presets:
        try:
            data = _json.loads(p.read_text(encoding="utf-8"))
            comment = data.get("_comment", "(no description)")
        except Exception:
            comment = "(invalid JSON)"
        print(f"  {p.stem:<35s} {comment}")
    print()


def _resolve_query(query_spec: str) -> dict:
    """Resolve *query_spec* to a JSON dict.

    - Starts with ``{`` → inline JSON DSL.
    - Otherwise → preset name, loaded from ``queries/<name>.json``.
    """
    import json as _json

    spec = query_spec.strip()
    if spec.startswith("{"):
        return _json.loads(spec)

    # Preset name — try queries/<name>.json
    queries_dir = _find_queries_dir()
    preset_path = queries_dir / f"{spec}.json"
    if not preset_path.is_file():
        # Also try the bare path
        preset_path = Path(spec)
    if not preset_path.is_file():
        raise FileNotFoundError(
            f"Query preset '{spec}' not found in {queries_dir} "
            f"and not an inline JSON query. Use --list-presets to see available presets."
        )
    return _json.loads(preset_path.read_text(encoding="utf-8"))


def _run_query_and_print(store, query_spec: str) -> None:
    """Execute *query_spec* against *store* and print results."""
    from prettytable import PrettyTable

    query_dict = _resolve_query(query_spec)
    result = store.execute(query_dict)

    comment = query_dict.get("_comment", "Query result")
    table = PrettyTable()
    table.title = f"{comment}: {len(result)} rows"
    table.field_names = list(result.columns)
    table.align = "l"
    for row in result.rows:
        if isinstance(row, tuple):
            table.add_row([str(v) for v in row])
        else:
            import dataclasses
            table.add_row([str(getattr(row, c)) for c in result.columns])
    print()
    print(table)
    print()


if __name__ == "__main__":
    sys.exit(main())
