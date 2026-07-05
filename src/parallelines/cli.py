from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from prettytable import PrettyTable

from parallelines.analysis.dead_file import DeadFileAnalyzer
from parallelines.analysis.dep_conflict import DependencyConflictAnalyzer
from parallelines.analysis.engine import AnalyzerEngine
from parallelines.analysis.entry_points import (
    discover_entry_points,
    filter_entry_points,
)
from parallelines.analysis.hash_conflict import HashConflictAnalyzer
from parallelines.analysis.impact import ImpactAnalyzer
from parallelines.analysis.isolated import IsolatedPackageAnalyzer
from parallelines.analysis.redundancy import RedundancyAnalyzer
from parallelines.config import load_config, AppConfig
from parallelines.exceptions import ParallelinesError
from parallelines.graph.builder import GraphBuilder
from parallelines.report.generators import generate_report
from parallelines.types import AnalysisReport
from parallelines.vfs.builder import VfsBuilder
from parallelines.vfs.external import ExternalVpkOverlay
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


def _filter_report(report, exts: set[str] | None):
    """Filter report fragments to only include items matching given extensions.
    Returns the same report if exts is None (no filtering)."""
    if exts is None:
        return report
    for fragment in report.fragments:
        fragment.items = [
            item for item in fragment.items
            if any(
                str(item.get(k, "")).lower().endswith(tuple(exts))
                for k in ("virtual_path", "source_file", "depends_on", "file")
                if k in item
            )
        ]
    report.fragments = [f for f in report.fragments if f.items]
    return report


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
        help="Game root directory (containing gameinfo.txt)",
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
    parser.add_argument(
        "--tui",
        action="store_true",
        default=False,
        help="Launch Textual TUI interface",
    )
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
        action="store_true", default=False,
        help="材质/贴图冲突 — .vmt/.vtf 同名哈希比对",
    )
    parser.add_argument(
        "--check-models",
        action="store_true", default=False,
        help="模型冲突 — .mdl/.vvd/.vtx 覆盖检测",
    )
    parser.add_argument(
        "--check-sounds",
        action="store_true", default=False,
        help="音效冲突 — .wav/.mp3 同名覆盖检测",
    )
    parser.add_argument(
        "--check-scripts",
        action="store_true", default=False,
        help="脚本冲突 — .nut 全局函数覆盖风险",
    )
    parser.add_argument(
        "--check-configs",
        action="store_true", default=False,
        help="配置污染 — .cfg 自动执行覆盖检测",
    )
    parser.add_argument(
        "--check-maps",
        action="store_true", default=False,
        help="地图完整性 — .bsp 缺失依赖/版本不匹配",
    )
    parser.add_argument(
        "--check-manifests",
        action="store_true", default=False,
        help="清单污染 — particles/soundscapes manifest 冲突",
    )
    parser.add_argument(
        "--check-all",
        action="store_true", default=False,
        help="全部资源污染检查 (等价于以上 --check-* 全开)",
    )
    parser.add_argument(
        "--compare-maps",
        type=str, nargs="+", default=None, metavar="VPK",
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

    return parser


def print_summary(report: AnalysisReport) -> None:
    """Display a brief CLI summary using prettytable."""
    if not report.fragments:
        print("[parallelines] No analyzers registered.")
        return

    summary = PrettyTable()
    summary.title = "Analysis Summary"
    summary.field_names = ["Analyzer", "Issues", "Status"]
    summary.align = "l"

    for fragment in report.fragments:
        count = len(fragment.items)
        status = "OK" if count == 0 else f"{count} found"
        summary.add_row(
            [fragment.analyzer_name.replace("Analyzer", ""), str(count), status]
        )

    print(summary)

    # Show top items for analyzers that found issues
    for fragment in report.fragments:
        if not fragment.items:
            continue
        detail = PrettyTable()
        detail.title = f"{fragment.analyzer_name} — Top {min(5, len(fragment.items))} of {len(fragment.items)}"
        detail.field_names = list(fragment.items[0].keys())[:4]
        for item in fragment.items[:5]:
            detail.add_row([str(v)[:60] for v in list(item.values())[:4]])
        detail.align = "l"
        print()
        print(detail)


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
    parser = build_parser()
    args = parser.parse_args(argv)

    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)

    config.general.game = args.game
    if args.game_root:
        config.general.game_root = args.game_root
    if args.log_level:
        config.general.log_level = args.log_level
    if hasattr(args, "format") and args.format:
        config.output.format = args.format
    if hasattr(args, "output_dir") and args.output_dir:
        config.output.output_dir = args.output_dir
    if args.cpu is not None:
        config.general.num_workers = args.cpu
    if args.memory is not None:
        config.general.memory_limit = args.memory
    if args.nolimit:
        config.general.nolimit = True
    if args.debug:
        config.general.log_level = "DEBUG"
        logging.getLogger().setLevel(logging.DEBUG)

    if args.lang:
        set_language(args.lang)

    # Resolve effective worker count
    if config.general.nolimit:
        num_workers = 0  # unlimited
    elif config.general.num_workers == 0:
        import os

        num_workers = max(1, (os.cpu_count() or 2) - 1)
    else:
        num_workers = config.general.num_workers

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

    if not config.general.game_root:
        parser.print_help()
        print(f"\nError: {_('cli.game_root_required')}")
        return 1

    if args.tui:
        from parallelines.tui.app import ParallelinesTUI

        app = ParallelinesTUI(
            game=config.general.game,
            game_root=config.general.game_root,
        )
        app.run()
        return 0

    try:
        if args.analyze:
            return cmd_analyze(config, args)
        elif args.external:
            return cmd_external(config, args)
        else:
            parser.print_help()
            return 0
    except Exception as exc:
        if config.general.log_level == "DEBUG":
            logger.exception(_("error.unexpected").format(msg=exc))
        else:
            logger.error("%s", exc)
        return 1


def cmd_analyze(config: AppConfig, args: argparse.Namespace) -> int:
    """Run full analysis: build VFS, build dep graph, run analyzers, output report."""
    game_root = Path(config.general.game_root).resolve()
    if not (game_root / "gameinfo.txt").exists():
        logger.error("gameinfo.txt not found in %s", game_root)
        return 1

    # 1 -- Build VFS (with optional cache)
    use_cache = not getattr(args, "no_cache", False)

    builder = VfsBuilder(game_root, config, use_cache=use_cache)

    if getattr(args, "clean_cache", False):
        builder.invalidate_cache()

    logger.info("Building VFS from '%s' (game=%s) ...", game_root, config.general.game)
    vfs = builder.build()

    if builder.cache_hit:
        logger.info(
            "VFS loaded from SSD cache (%s) — use --no-cache to force rebuild",
            builder.cache_size(),
        )
        logger.info("  💡 清理缓存: python -m parallelines ... analyze --clean-cache")
    else:
        logger.info("VFS built from disk, cache saved (%s)", builder.cache_size())

    logger.info("VFS ready: %d active files", len(vfs.get_all_active()))

    # 2 -- Build FileSystemChain for content reading
    logger.info("Building file system chain ...")
    chain = builder.get_chain()
    if chain is not None:
        vpk_count = sum(1 for s in chain.systems if "vpk" in str(type(s[0])).lower())  # type: ignore[union-attr]
        logger.info("FileSystemChain ready (%d VPKs in chain)", vpk_count)

    # 3 -- Build dependency graph
    logger.info("Building dependency graph ...")
    if chain is not None:
        graph_builder = GraphBuilder(
            chain, vfs, debug=(config.general.log_level == "DEBUG")
        )
        graph = graph_builder.build()
        logger.info(
            "Graph ready: %d nodes, %d edges", graph.node_count, graph.edge_count
        )
    else:
        logger.warning("srctools FileSystem not available; graph will be empty")
        graph = None

    # 3a -- Generate Graphviz .dot if requested
    if hasattr(args, "graphviz") and args.graphviz and graph is not None:
        from parallelines.report.graphviz import generate_dot

        dot_path = generate_dot(graph, args.graphviz)
        logger.info("Graphviz .dot saved to %s", dot_path)

    # 3 -- Discover entry points (unless user provided explicit ones)
    #     Pass the chain so manifest content can be read for deeper discovery.
    if args.entry_points:
        entry_points = set(args.entry_points)
    else:
        entry_points = discover_entry_points(vfs, chain=chain)

    # 3b -- If --maps was provided, expand to maps/{name}.bsp and add to set.
    if hasattr(args, "maps") and args.maps:
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
        logger.info("No entry points — dead file analysis will be skipped")

    # 4 -- Run analyzers
    engine = AnalyzerEngine()
    engine.register(RedundancyAnalyzer())
    engine.register(
        DeadFileAnalyzer(entry_points=entry_points if entry_points else None)
    )
    engine.register(HashConflictAnalyzer())
    engine.register(DependencyConflictAnalyzer())
    engine.register(IsolatedPackageAnalyzer())
    engine.register(ImpactAnalyzer(top_n=20))

    # 4a -- Addon dependency checking (requires addoninfo.txt in VFS)
    from parallelines.analysis.addon_dep import AddonDependencyAnalyzer

    engine.register(AddonDependencyAnalyzer())

    # 4b -- Map version conflict analysis
    if args.compare_maps:
        from parallelines.analysis.map_conflict import MapConflictAnalyzer
        from parallelines.parsers.vpk_parser import parse_vpk_index

        # 解析每个指定 VPK，提取其中的 .bsp 路径
        external_maps: dict[str, str] = {}  # virtual_path → source_name
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
            logger.info("Map conflict analysis: %d maps from %d VPK(s)",
                        len(external_maps), len(args.compare_maps))
            engine.register(MapConflictAnalyzer(
                target_maps=set(external_maps.keys()),
                external_sources=external_maps,
            ))

    report = engine.run(vfs, graph)

    # 5 -- Apply resource pollution filter (if --check-* flag given)
    check_exts = _get_check_extensions(args)
    if check_exts:
        report = _filter_report(report, check_exts)
        logger.info("Filtered to %d issues matching check scope", sum(len(f.items) for f in report.fragments))

    # 6 -- Console summary
    print_summary(report)

    # 6 -- Save full report
    output_dir = config.output.output_dir or "./reports"
    output_format = config.output.format or "json"
    path = generate_report(report, output_format, output_dir)
    logger.info("Full report saved to %s", path)

    return 0


def cmd_external(config: AppConfig, args: argparse.Namespace) -> int:
    """Analyze an external vpk against the current environment."""
    game_root = Path(config.general.game_root).resolve()
    if not (game_root / "gameinfo.txt").exists():
        logger.error("gameinfo.txt not found in %s", game_root)
        return 1

    # 1 -- Build base VFS (use cache for performance)
    builder = VfsBuilder(game_root, config, use_cache=True)
    logger.info(
        "Building base VFS from '%s' (game=%s) ...", game_root, config.general.game
    )
    vfs = builder.build()
    logger.info("Base VFS ready: %d active files", len(vfs.get_all_active()))

    # 2 -- Resolve external VPK path
    vpk_path = Path(args.external)
    if not vpk_path.is_absolute():
        vpk_path = Path.cwd() / vpk_path

    vpk_path = vpk_path.resolve()
    if not vpk_path.exists():
        logger.error("External VPK file not found: %s", vpk_path)
        return 1

    # 3 -- Map CLI priority string to integer
    if args.vpk_priority == "highest":
        priority = 2000  # Above all base-game priorities (1000 max)
    else:
        priority = -100  # Below all base-content priorities

    # 4 -- Build overlay and run analysis
    overlay = ExternalVpkOverlay(vfs, vpk_path, priority=priority)
    logger.info(
        "Analyzing %s at priority %d (%s) ...",
        vpk_path.name,
        priority,
        args.vpk_priority,
    )
    result = overlay.analyze()

    summary = result["summary"]

    # 5 -- Display summary table
    print()
    summary_table = PrettyTable()
    summary_table.title = f"External VPK Analysis: {result['external_vpk']}"
    summary_table.field_names = ["Metric", "Count"]
    summary_table.align = "l"
    summary_table.add_row(["Total files in VPK", summary["total_files_in_vpk"]])
    summary_table.add_row(["Will override (external wins)", summary["will_override"]])
    summary_table.add_row(
        ["Will be overridden (existing wins)", summary["will_be_overridden"]]
    )
    summary_table.add_row(["New files (no conflict)", summary["new_files"]])
    print(summary_table)

    # Show top 10 overrides if any exist
    if summary["will_override"] > 0:
        override_table = PrettyTable()
        override_table.title = f"Overrides — Top {min(10, summary['will_override'])} of {summary['will_override']}"
        override_table.field_names = ["Virtual Path", "Existing Source", "Ext Hash"]
        override_table.align = "l"
        for item in result["overrides"][:10]:
            override_table.add_row(
                [
                    item["virtual_path"][:70],
                    item.get("existing_source", "")[:30],
                    (item.get("external_hash") or "")[:12],
                ]
            )
        print()
        print(override_table)

    # 6 -- Save JSON report
    output_dir = config.output.output_dir or "./reports"
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_filename = f"external_vpk_report_{timestamp}.json"
    report_path = output_path / report_filename

    json_text = json.dumps(result, indent=2, ensure_ascii=False)
    json_text = json_text.encode("utf-8", errors="replace").decode("utf-8")
    report_path.write_text(json_text, encoding="utf-8")

    logger.info("External VPK report saved to %s", report_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
