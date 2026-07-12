"""Argument definitions for the parallelines CLI.

Extracted from the God Module ``cli.py`` (Phase 4 of I/O audit refactoring).
"""

from __future__ import annotations

import argparse


SUPPORTED_GAMES = {
    "l4d2": "Left 4 Dead 2",
    "l4d1": "Left 4 Dead",
    "tf2": "Team Fortress 2",
    "portal2": "Portal 2",
    "portal": "Portal",
    "hl2": "Half-Life 2",
    "hl2ep1": "Half-Life 2: Episode One",
    "hl2ep2": "Half-Life 2: Episode Two",
    "csgo": "Counter-Strike: Global Offensive",
    "css": "Counter-Strike: Source",
    "dods": "Day of Defeat: Source",
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


def get_check_extensions(args: argparse.Namespace) -> set[str] | None:
    """Return file extensions to filter by, or None for all (unfiltered)."""
    exts: set[str] = set()
    for flag, filter_exts in _CHECK_FILTERS.items():
        if getattr(args, flag, False) or args.check_all:
            exts |= filter_exts
    return exts if exts else None


def get_version() -> str:
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
        version=f"%(prog)s {get_version()}",
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
        "--all-maps",
        action="store_true",
        default=False,
        help="Use ALL maps as entry points (default: none; use --maps for specific maps)",
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
        "--yes",
        "-y",
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
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Override query result limit",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=None,
        help="Override query result offset",
    )

    return parser
