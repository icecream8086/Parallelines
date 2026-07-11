"""Query resolution and printing for the parallelines CLI.

Extracted from the God Module ``cli.py`` (Phase 4 of I/O audit refactoring).
"""

from __future__ import annotations

import argparse
import json as _json
from pathlib import Path

from parallelines.engine.store import Relation
from parallelines.io import FileReader


def find_queries_dir() -> Path:
    """Locate the ``queries/`` directory (project root, cwd, or next to the exe)."""
    import sys as _sys

    # When frozen (PyInstaller onedir), queries/ is inside _internal/ next to exe.
    if getattr(_sys, "frozen", False):
        exe_dir = Path(_sys.executable).resolve().parent
        for sub in ("queries", "_internal/queries"):
            candidate = exe_dir / sub
            if candidate.is_dir():
                return candidate

    # Development: project root (3 levels up from this file in src/parallelines/).
    dev_root = Path(__file__).resolve().parent.parent.parent
    candidate = dev_root / "queries"
    if candidate.is_dir():
        return candidate

    # Fallback: current working directory.
    return Path.cwd() / "queries"


def list_presets() -> None:
    """Print available query presets from the ``queries/`` directory."""
    queries_dir = find_queries_dir()
    if not queries_dir.is_dir():
        print(f"No queries/ directory found (looked in: {queries_dir})")
        return

    presets = sorted(p for p in queries_dir.glob("*.json") if p.name != "README.md")
    if not presets:
        print("No presets found in queries/.")
        return

    print(f"\n{'=' * 60}")
    print(f"  Available query presets ({len(presets)}):")
    print(f"{'=' * 60}")
    for p in presets:
        try:
            data = _json.loads(FileReader.read_text(p))
            comment = data.get("_comment", "(no description)")
        except Exception:
            comment = "(invalid JSON)"
        print(f"  {p.stem:<35s} {comment}")
    print()


def resolve_query(query_spec: str) -> dict:
    """Resolve *query_spec* to a JSON dict.

    - Starts with ``{`` → inline JSON DSL.
    - Otherwise → preset name, loaded from ``queries/<name>.json``.
    """
    spec = query_spec.strip()
    if spec.startswith("{"):
        return _json.loads(spec)

    # Preset name — try queries/<name>.json
    queries_dir = find_queries_dir()
    preset_path = queries_dir / f"{spec}.json"
    if not preset_path.is_file():
        # Also try the bare path
        preset_path = Path(spec)
    if not preset_path.is_file():
        raise FileNotFoundError(
            f"Query preset '{spec}' not found in {queries_dir} "
            f"and not an inline JSON query. Use --list-presets to see available presets."
        )
    return _json.loads(FileReader.read_text(preset_path))


def run_query_and_print(store, query_spec: str, args: argparse.Namespace | None = None) -> None:
    """Execute *query_spec* against *store* and print results."""
    from prettytable import PrettyTable

    query_dict = resolve_query(query_spec)

    # Apply CLI overrides for limit/offset if provided
    if args is not None:
        if args.limit is not None:
            query_dict["limit"] = args.limit
        if args.offset is not None:
            query_dict["offset"] = args.offset

    result = store.execute(query_dict)

    comment = query_dict.get("_comment", "Query result")

    # Large result protection: if output is to terminal, show first N rows
    MAX_TERMINAL_ROWS = 200
    total_rows = len(result.rows)
    if total_rows > MAX_TERMINAL_ROWS:
        display_rows = result.rows[:MAX_TERMINAL_ROWS]
        truncated = True
    else:
        display_rows = result.rows
        truncated = False

    table = PrettyTable()
    table.title = f"{comment}: {min(total_rows, MAX_TERMINAL_ROWS)} rows"
    table.field_names = list(result.columns)
    table.align = "l"
    for row in display_rows:
        if isinstance(row, tuple):
            table.add_row([str(v) for v in row])
        else:
            table.add_row([str(getattr(row, c)) for c in result.columns])
    print()
    print(table)
    if truncated:
        print(
            f"... and {total_rows - MAX_TERMINAL_ROWS} more rows. Use --format json for full export."
        )
    print()


def print_reference_results(
    results: dict[str, Relation],
    ref_name: str,
    vpk_filename: str,
    ext_count: int,
) -> None:
    """Print external VPK reference analysis results as PrettyTables."""
    from prettytable import PrettyTable

    print(f"\n{'=' * 60}")
    print(f"  External VPK: {vpk_filename}  (ref: {ref_name})")
    print(f"  Total files in VPK: {ext_count}")
    print(f"{'=' * 60}\n")

    for qname, rel in results.items():
        count = len(rel)
        label = {
            "external_overrides": "OVERRIDES (external wins)",
            "external_overridden": "OVERRIDEN (current wins)",
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
