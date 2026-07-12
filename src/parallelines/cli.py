"""CLI dispatcher — argument parsing, command dispatch, error handling.

Slim shell after Phase 4 refactoring:
  - ``cli_args.py``   — argparse definitions
  - ``pipeline.py``   — VFS→Graph→Analysis orchestration
  - ``query_cli.py``  — query resolution and printing
"""

from __future__ import annotations

import argparse
import json as _json
import logging
import sys
from datetime import datetime
from pathlib import Path

from parallelines.cli_args import SUPPORTED_GAMES, build_parser
from parallelines.config import AppConfig, load_config
from parallelines.engine import Relation
from parallelines.exceptions import ParallelinesError
from parallelines.i18n import _, set_language
from parallelines.io import FileReader, FileWriter, reconfigure_stdout
from parallelines.pipeline import apply_check_filters, build_store, print_summary_from_store
from parallelines.query_cli import (
    find_queries_dir,
    list_presets,
    print_reference_results,
    run_query_and_print,
)
from parallelines.report.generators import generate_report_from_store

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    reconfigure_stdout()
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
        list_presets()
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
    if args.io is not None:
        config.general.io_limit = args.io
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
    io_str = "unlimited" if config.general.io_limit == 0 else str(config.general.io_limit)
    logger.info("Resources: %s workers, memory=%s, io=%s", worker_str, mem_str, io_str)

    if not config.general.game_root:
        parser.print_help()
        print(f"\nError: {_('cli.game_root_required')}")
        return 1

    # ── Flag conflict warnings (B025-B031) ──────────────────────
    mode_flags = sum([args.analyze, bool(args.external), args.repl])
    if mode_flags > 1:
        logger.warning(
            "Multiple mode flags specified (--analyze, --external, --repl). "
            "Only the first in dispatch order (analyze > external > repl) will be honored."
        )
    if args.no_cache and args.clean_cache:
        logger.warning(
            "--no-cache and --clean-cache specified together. "
            "--clean-cache deletes the cache, then --no-cache skips saving."
        )
    if args.repl and args.sv_pure:
        logger.warning(
            "--sv-pure is not applied in REPL mode (only in --analyze mode)"
        )
    if args.repl and args.external:
        logger.warning("--vpk-priority is ignored in REPL mode")
    if not args.external and (getattr(args, "ref_query", "all") != "all" or args.vpk_priority != "highest"):
        pass  # --ref-query and --vpk-priority only meaningful with --external, silently ignored

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


def cmd_analyze(config: AppConfig, args: argparse.Namespace) -> int:
    """Run full analysis: build VFS, build dep graph, run analyzers, output report."""
    store, vfs = build_store(config, args)
    if store is None:
        return 1

    # 5 -- Apply resource pollution filter (if --check-* flag given)
    apply_check_filters(store, args)

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
        run_query_and_print(store, args.query, args=args)

    return 0


def cmd_external(config: AppConfig, args: argparse.Namespace) -> int:
    """Analyze an external VPK against the current environment using the query engine."""
    # 1 -- Full analysis pipeline
    store, _vfs = build_store(config, args)
    if store is None:
        return 1

    # 2 -- Resolve external VPK path
    vpk_path = Path(args.external)
    if not vpk_path.is_absolute():
        vpk_path = Path(config.general.game_root) / vpk_path
        if not vpk_path.exists():
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

    results: dict[str, Relation] = {}
    for qname in queries_to_run:
        queries_dir = find_queries_dir()
        preset_path = queries_dir / f"{qname}.json"
        if preset_path.is_file():
            query_dict = _json.loads(FileReader.read_text(preset_path))
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
    print_reference_results(results, ref_name, vpk_path.name, ext_count)

    # 7 -- Save report (JSON)
    output_dir = Path(config.output.output_dir or "./reports")
    output_dir.mkdir(parents=True, exist_ok=True)
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
    FileWriter.write_json(output_path, report_data)
    logger.info("External VPK report saved to %s", output_path)

    # 8 -- Run inline query if --query was specified
    if getattr(args, "query", None):
        run_query_and_print(store, args.query, args=args)

    return 0


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main())
