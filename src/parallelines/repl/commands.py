"""REPL meta-command handlers."""
from __future__ import annotations
import json
from pathlib import Path
from parallelines.engine.store import Relation


def cmd_help(session, args: str) -> bool:
    print("Parallelines REPL -- interactive query mode\n")
    print("Meta-commands (prefix with .):")
    print("  .help                  Show this help")
    print("  .tables                List available relations")
    print("  .schema [table]        Show relation columns")
    print("  .mode <table|vertical|json|csv>  Set output format")
    print("  .pager <on|off>        Toggle paging (>50 rows)")
    print("  .print <on|off>        Toggle auto-print results")
    print("  .echo <on|off>         Toggle query echo (debug)")
    print("  .history               Show command history")
    print("  .save <file.json>      Save store to JSON file")
    print("  .load <file.json>      Load store from saved JSON report")
    print("  .external <vpk_path>   Load external VPK for comparison")
    print("  .unload <ref>          Remove external VPK reference")
    print("  .analyze               Re-run full analysis pipeline")
    print("  .stores                List active stores")
    print("  .exit / .quit          Exit REPL\n")
    print("Queries:")
    print("  Enter JSON: {\"select\":[\"*\"],\"from\":\"files\"}")
    print("  Enter preset name: dead_by_source")
    return True


def cmd_tables(session, args: str) -> bool:
    if session.store is None:
        print("No store loaded.")
        return True
    names = []
    for attr in (
        "files", "dependencies", "addons", "hash_conflicts",
        "dep_conflicts", "isolated", "impact", "entry_points",
        "dependency_cycles", "cascade_overrides", "global_scripts",
        "implicit_deps", "mod_types", "external_files",
    ):
        rel = getattr(session.store, attr, None)
        if rel is not None and isinstance(rel, Relation):
            names.append(f"{attr:<25s} ({len(rel)} rows)")
    print(f"Available relations ({len(names)}):")
    for n in names:
        print(f"  {n}")
    return True


def cmd_schema(session, args: str) -> bool:
    if session.store is None:
        print("No store loaded.")
        return True
    name = args.strip()
    if not name:
        print("Usage: .schema <table_name>")
        return True
    rel = getattr(session.store, name, None)
    if rel is None or not isinstance(rel, Relation):
        print(f"Relation '{name}' not found.")
        return True
    print(f"Table: {name} ({len(rel)} rows)")
    print(f"Columns ({len(rel.columns)}):")
    for col in rel.columns:
        print(f"  {col}")
    return True


def cmd_mode(session, args: str) -> bool:
    mode = args.strip().lower()
    if mode in ("table", "vertical", "json", "csv"):
        session.output_mode = mode
        print(f"Output mode set to {mode}.")
    else:
        print(f"Unknown mode '{mode}'. Use: table, vertical, json, csv")
    return True


def cmd_pager(session, args: str) -> bool:
    val = args.strip().lower()
    if val == "on":
        session.pager_enabled = True
        print("Pager enabled.")
    elif val == "off":
        session.pager_enabled = False
        print("Pager disabled.")
    else:
        current = "on" if session.pager_enabled else "off"
        print(f"Usage: .pager <on|off> (current: {current})")
    return True


def cmd_print(session, args: str) -> bool:
    val = args.strip().lower()
    if val == "on":
        session.print_enabled = True
        print("Auto-print enabled.")
    elif val == "off":
        session.print_enabled = False
        print("Auto-print disabled.")
    else:
        current = "on" if session.print_enabled else "off"
        print(f"Usage: .print <on|off> (current: {current})")
    return True


def cmd_echo(session, args: str) -> bool:
    val = args.strip().lower()
    session.echo_enabled = val == "on"
    print(f"Echo {'enabled' if session.echo_enabled else 'disabled'}.")
    return True


def cmd_history(session, args: str) -> bool:
    """Print recent command history from the prompt_toolkit session."""
    if session._prompt_session is None:
        print("History unavailable (prompt_toolkit not loaded).")
        return True
    try:
        hist = session._prompt_session.history
        items = list(hist.load_history_strings())
        if not items:
            print("No history.")
            return True
        width = len(str(len(items)))
        for i, item in enumerate(items[-50:], 1):
            print(f"  {i:>{width}}  {item}")
    except Exception as e:
        print(f"Cannot read history: {e}")
    return True


def cmd_save(session, args: str) -> bool:
    if session.store is None:
        print("No store to save.")
        return True
    path = args.strip() or "repl_store.json"
    try:
        data = session.store.to_dict()
        Path(path).write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        print(f"Store saved to {path}.")
    except Exception as e:
        print(f"Save failed: {e}")
    return True


def cmd_load(session, args: str) -> bool:
    """Restore a store from a previously saved JSON report.

    Note: graph is not serialized, so graph-dependent queries
    (descendants_of, ancestors_of, ancestor_is_map) will return empty.
    """
    from parallelines.engine.schema import (
        FileRow, DependencyRow, HashConflictRow, DepConflictRow,
        IsolatedPackageRow, ImpactRow, EntryPointRow,
        DependencyCycleRow, CascadeOverrideRow, GlobalScriptRow,
        ImplicitDepRow, ModTypeRow, AddonRow, ExternalFileRow,
    )
    from parallelines.engine.store import Relation, ResultStore

    path = args.strip()
    if not path:
        print("Usage: .load <file.json>")
        return True
    p = Path(path)
    if not p.is_file():
        print(f"File not found: {p}")
        return True
    try:
        data = json.loads(p.read_text("utf-8"))
    except Exception as e:
        print(f"Failed to read JSON: {e}")
        return True

    store = ResultStore()
    _row_types = {
        "files": FileRow, "dependencies": DependencyRow,
        "addons": AddonRow, "hash_conflicts": HashConflictRow,
        "dep_conflicts": DepConflictRow, "isolated": IsolatedPackageRow,
        "impact": ImpactRow, "entry_points": EntryPointRow,
        "dependency_cycles": DependencyCycleRow,
        "cascade_overrides": CascadeOverrideRow,
        "global_scripts": GlobalScriptRow,
        "implicit_deps": ImplicitDepRow, "mod_types": ModTypeRow,
        "external_files": ExternalFileRow,
    }
    loaded = 0
    skipped = []
    for attr, row_type in _row_types.items():
        rows_data = data.get(attr, [])
        if rows_data:
            try:
                typed_rows = [row_type(**r) for r in rows_data]
                setattr(store, attr, Relation.from_rows(attr, typed_rows))
                loaded += 1
            except Exception:
                skipped.append(attr)
    if skipped:
        print(f"  Warning: skipped {skipped} (schema mismatch)")

    old = len(session.store.files) if (session.store and session.store.files) else 0
    new = len(store.files) if store.files else 0
    print(f"Store replaced: {old} → {new} files ({loaded} relations loaded)")
    session.store = store
    session.externals = []
    session.refresh_completer()
    return True


def cmd_external(session, args: str) -> bool:
    import shlex
    parts = shlex.split(args.strip()) if args.strip() else []
    if not parts:
        print("Usage: .external <vpk_path>")
        print("       .external --replace <vpk_path>")
        return True
    replace = False
    if parts[0] == "--replace":
        replace = True
        parts = parts[1:]
    if not parts:
        print("Usage: .external <vpk_path>")
        return True
    try:
        session.load_external_vpk(parts[0], replace=replace)
        session.refresh_completer()
    except Exception as e:
        print(f"Failed: {e}")
    return True


def cmd_unload(session, args: str) -> bool:
    ref = args.strip()
    if not ref:
        print("Usage: .unload <ref_name>")
        return True
    if ref in session.externals:
        session.externals.remove(ref)
        if not session.externals and session.store is not None:
            session.store.external_files = None
        print(f"Unloaded external reference: {ref}")
        session.refresh_completer()
    else:
        print(f"No external reference named '{ref}' loaded.")
    return True


def cmd_analyze(session, args: str) -> bool:
    """Re-run the full analysis pipeline, replacing the in-memory store."""
    from parallelines.cli import _build_store, print_summary_from_store

    print("Re-running analysis ...")
    store, _vfs = _build_store(session.config, session.args)
    if store is None:
        print("Analysis failed.")
        return True
    session.store = store
    session.externals = []
    print_summary_from_store(store)
    session.refresh_completer()
    print("Analysis complete.")
    return True


def cmd_stores(session, args: str) -> bool:
    if session.store is None:
        print("No store loaded.")
        return True
    count = len(session.store.files) if session.store.files else 0
    print(f"Active store: {count} files")
    if session.externals:
        print(f"  External refs: {', '.join(session.externals)}")
    return True


def cmd_exit(session, args: str) -> bool:
    return False


COMMANDS = {
    "help": cmd_help,
    "tables": cmd_tables,
    "schema": cmd_schema,
    "mode": cmd_mode,
    "pager": cmd_pager,
    "print": cmd_print,
    "echo": cmd_echo,
    "history": cmd_history,
    "save": cmd_save,
    "load": cmd_load,
    "external": cmd_external,
    "unload": cmd_unload,
    "analyze": cmd_analyze,
    "stores": cmd_stores,
    "exit": cmd_exit,
    "quit": cmd_exit,
}
