"""Comprehensive pytest tests for CLI AST rules R01-R28 from devdocs/cli-ast-rules.md.

Covers sections 3 (AST constraint rules), 4 (orthogonal verification), and
7 (coverage matrix).  Each rule R01-R28 has at least one dedicated test.

Known bugs are marked with ``@pytest.mark.xfail(strict=True)`` – when the
underlying bug is fixed the test will start passing and pytest will report
an "unexpected pass" (XPASS), reminding us to remove the marker.
"""

from __future__ import annotations

import argparse
import logging
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from parallelines.cli import (
    _apply_check_filters,
    _build_store,
    _get_check_extensions,
    _main,
    _parse_memory_limit,
    build_parser,
    cmd_analyze,
    cmd_external,
)
from parallelines.config import AppConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_args(**overrides: object) -> argparse.Namespace:
    """Create a mock ``argparse.Namespace`` with sensible defaults."""
    defaults: dict[str, object] = {
        "analyze": False,
        "external": None,
        "repl": False,
        "game": "l4d2",
        "game_root": "",
        "config": "",
        "no_cache": False,
        "clean_cache": False,
        "yes": False,
        "cpu": None,
        "memory": None,
        "nolimit": None,
        "format": None,
        "output_dir": None,
        "graphviz": None,
        "check_textures": False,
        "check_models": False,
        "check_sounds": False,
        "check_scripts": False,
        "check_configs": False,
        "check_maps": False,
        "check_manifests": False,
        "check_all": False,
        "entry_points": None,
        "maps": None,
        "compare_maps": None,
        "sv_pure": None,
        "query": None,
        "vpk_priority": "highest",
        "ref_query": "all",
        "debug": False,
        "log_level": None,
        "lang": None,
        "list_presets": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def make_config(**overrides: object) -> AppConfig:
    """Create an ``AppConfig`` with fields overridable by keyword args."""
    config = AppConfig()
    config.general.game = str(overrides.get("game", "l4d2"))
    config.general.game_root = str(overrides.get("game_root", "/games/l4d2"))
    config.general.num_workers = int(overrides.get("num_workers", 0))
    config.general.memory_limit = str(overrides.get("memory_limit", ""))
    config.general.log_level = str(overrides.get("log_level", "INFO"))
    config.general.nolimit = bool(overrides.get("nolimit", False))
    config.general.cache_dir = str(overrides.get("cache_dir", "./cache"))
    config.output.format = str(overrides.get("format", "json"))
    config.output.output_dir = str(overrides.get("output_dir", "./reports"))
    return config


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config() -> AppConfig:
    """Return a bare-bones ``AppConfig`` with ``game_root`` set."""
    return make_config()


@pytest.fixture
def mock_main_deps():
    """Patch all top-level dependencies called from ``_main``.

    This lets mode-dispatch tests verify which function gets called
    without actually building a VFS or running analyzers.
    """
    with (
        patch("parallelines.cli.load_config") as mock_load_config,
        patch("parallelines.cli.set_language") as mock_set_language,
        patch("parallelines.cli.logging.basicConfig") as mock_logging,
        patch("parallelines.cli.cmd_analyze") as mock_cmd_analyze,
        patch("parallelines.cli.cmd_external") as mock_cmd_external,
        # ReplSession is imported LOCALLY inside _main (not a module-level attr),
        # so we patch the class at its definition site in parallelines.repl.
        patch("parallelines.repl.ReplSession") as mock_repl_cls,
    ):
        mock_load_config.return_value = make_config()
        mock_cmd_analyze.return_value = 0
        mock_cmd_external.return_value = 0
        mock_repl_instance = MagicMock()
        mock_repl_instance.run.return_value = 0
        mock_repl_cls.return_value = mock_repl_instance

        yield {
            "load_config": mock_load_config,
            "set_language": mock_set_language,
            "logging": mock_logging,
            "cmd_analyze": mock_cmd_analyze,
            "cmd_external": mock_cmd_external,
            "ReplSession": mock_repl_cls,
            "repl_instance": mock_repl_instance,
        }


@pytest.fixture
def mock_build_store_deps():
    """Patch all internal imports of ``_build_store``.

    Because those imports are **local** (inside the function body), they must
    be patched at their **source** modules rather than at ``parallelines.cli``.
    """
    _TARGETS = [
        "parallelines.vfs.builder.VfsBuilder",
        "parallelines.graph.builder.GraphBuilder",
        "parallelines.analysis.entry_points.discover_entry_points",
        "parallelines.analysis.entry_points.filter_entry_points",
        "parallelines.cli.ResultStore.from_analysis",
        "parallelines.report.generators.generate_report_from_store",
        # All analyzer constructors that appear in _build_store's analyzer list
        "parallelines.analysis.redundancy.RedundancyAnalyzer",
        "parallelines.analysis.dead_file.DeadFileAnalyzer",
        "parallelines.analysis.hash_conflict.HashConflictAnalyzer",
        "parallelines.analysis.dep_conflict.DependencyConflictAnalyzer",
        "parallelines.analysis.isolated.IsolatedPackageAnalyzer",
        "parallelines.analysis.impact.ImpactAnalyzer",
        "parallelines.analysis.cycle_detector.CycleDetector",
        "parallelines.analysis.cascade_detector.CascadeDetector",
        "parallelines.analysis.global_script_detector.GlobalScriptDetector",
        "parallelines.analysis.implicit_dep_detector.ImplicitDepDetector",
        "parallelines.analysis.mod_classify.ModClassifier",
        "parallelines.analysis.addon_dep.AddonDependencyAnalyzer",
        "pathlib.Path.exists",
    ]
    # Enter all patches and collect their mock objects
    with _CompoundPatchContext(_TARGETS) as mocks:
        mock_vfs_builder_cls = mocks["parallelines.vfs.builder.VfsBuilder"]
        mock_graph_builder_cls = mocks["parallelines.graph.builder.GraphBuilder"]
        mock_discover_eps = mocks[
            "parallelines.analysis.entry_points.discover_entry_points"
        ]
        mock_filter_eps = mocks[
            "parallelines.analysis.entry_points.filter_entry_points"
        ]
        mock_from_analysis = mocks["parallelines.cli.ResultStore.from_analysis"]
        mock_exists = mocks["pathlib.Path.exists"]

        # VfsBuilder instance plumbing
        mock_vfs_instance = MagicMock()
        mock_vfs_instance.build.return_value = MagicMock()
        mock_vfs_instance.cache_hit = False
        mock_vfs_instance.cache_size.return_value = "0 B"
        mock_vfs_instance.get_all_active.return_value = []
        mock_vfs_instance.get_all_files.return_value = []
        mock_vfs_builder_cls.return_value = mock_vfs_instance

        # GraphBuilder
        mock_graph_instance = MagicMock()
        mock_graph_instance.node_count = 0
        mock_graph_instance.edge_count = 0
        mock_graph_builder_cls.build_from_cached.return_value = mock_graph_instance
        mock_graph_builder_cls.return_value.build.return_value = mock_graph_instance

        # Entry-point discovery
        mock_discover_eps.return_value = set()
        # filter_entry_points is called in _build_store after entry_points
        # are collected.  Return the input set unchanged by default so that
        # tests which pass explicit entry_points/maps see them preserved.
        mock_filter_eps.side_effect = lambda eps, vfs, graph: eps

        # ResultStore
        mock_store = MagicMock()
        mock_store.files = None
        mock_store.hash_conflicts = None
        mock_store.dep_conflicts = None
        mock_store.isolated = None
        mock_store.impact = None
        mock_from_analysis.return_value = mock_store

        # Everything exists (gameinfo.txt, cache files, etc.)
        mock_exists.return_value = True

        yield {
            "vfs_builder_cls": mock_vfs_builder_cls,
            "vfs_instance": mock_vfs_instance,
            "graph_builder_cls": mock_graph_builder_cls,
            "graph_instance": mock_graph_instance,
            "discover_eps": mock_discover_eps,
            "filter_eps": mock_filter_eps,
            "from_analysis": mock_from_analysis,
            "store": mock_store,
            "exists": mock_exists,
        }


class _CompoundPatchContext:
    """Context manager that enters many patches and indexes mocks by target name.

    Accepts a list of **full dotted target strings** (e.g.
    ``"parallelines.vfs.builder.VfsBuilder"``) rather than already-created
    ``patch`` objects so that the returned dict can use the full path as key.
    """

    def __init__(self, target_strings: list[str]):
        self._target_strings = target_strings
        self._patches: list[patch] = []

    def __enter__(self) -> dict[str, MagicMock]:
        result: dict[str, MagicMock] = {}
        for target in self._target_strings:
            p = patch(target)
            mock_obj = p.start()
            self._patches.append(p)
            result[target] = mock_obj
        return result

    def __exit__(self, *exc_info: object) -> None:
        for p in reversed(self._patches):
            p.stop()


# ===================================================================
# 3.1  Mode dispatch  (R01-R04)
# ===================================================================


def test_r01_mode_help(mock_main_deps) -> None:
    """R01: No mode flag given → print help and return 0."""
    result = _main(["--game", "l4d2"])
    assert result == 0
    mock_main_deps["cmd_analyze"].assert_not_called()
    mock_main_deps["cmd_external"].assert_not_called()
    mock_main_deps["ReplSession"].assert_not_called()


@pytest.mark.xfail(strict=True, reason="BUG R02: no WARNING when --analyze and --external both given")
def test_r02_analyze_wins_over_external(mock_main_deps, caplog) -> None:
    """R02 (BUG): --analyze + --external → --analyze wins, but no WARNING printed."""
    caplog.set_level(logging.WARNING)
    result = _main(["--game", "l4d2", "--analyze", "--external", "test.vpk"])
    assert result == 0
    mock_main_deps["cmd_analyze"].assert_called_once()
    mock_main_deps["cmd_external"].assert_not_called()
    # A WARNING should have been emitted about the conflicting modes
    assert any(
        "analyze" in msg.lower() and "external" in msg.lower()
        for msg in caplog.messages
    ), "Expected a WARNING about --analyze and --external conflict"


@pytest.mark.xfail(strict=True, reason="BUG R03: no WARNING when --analyze and --repl both given")
def test_r03_analyze_wins_over_repl(mock_main_deps, caplog) -> None:
    """R03 (BUG): --analyze + --repl → --analyze wins, but no WARNING printed."""
    caplog.set_level(logging.WARNING)
    result = _main(["--game", "l4d2", "--analyze", "--repl"])
    assert result == 0
    mock_main_deps["cmd_analyze"].assert_called_once()
    mock_main_deps["ReplSession"].assert_not_called()
    assert any(
        "analyze" in msg.lower() and "repl" in msg.lower()
        for msg in caplog.messages
    ), "Expected a WARNING about --analyze and --repl conflict"


@pytest.mark.xfail(strict=True, reason="BUG R04: no WARNING when --external and --repl both given")
def test_r04_external_wins_over_repl(mock_main_deps, caplog) -> None:
    """R04 (BUG): --external + --repl → --external wins, but no WARNING printed."""
    caplog.set_level(logging.WARNING)
    result = _main(["--game", "l4d2", "--external", "test.vpk", "--repl"])
    assert result == 0
    mock_main_deps["cmd_external"].assert_called_once()
    mock_main_deps["ReplSession"].assert_not_called()
    assert any(
        "external" in msg.lower() and "repl" in msg.lower()
        for msg in caplog.messages
    ), "Expected a WARNING about --external and --repl conflict"


# ===================================================================
# 3.2  Cache interactions  (R05-R08)
# ===================================================================


def test_r05a_no_cache_eof_error(mock_build_store_deps) -> None:
    """R05a: --no-cache without --yes, non-TTY stdin → input() EOFError → (None, None)."""
    config = make_config()
    args = make_args(no_cache=True, yes=False)
    with patch("builtins.input", side_effect=EOFError("EOF")):
        store, vfs = _build_store(config, args)
    assert store is None
    assert vfs is None


def test_r05b_repl_no_cache_cold_boot(mock_main_deps) -> None:
    """R05b: --repl --no-cache without --yes → cold-boot confirmation shown.

    This test verifies that ReplSession is launched with the no_cache and
    yes=False args; the actual cold-boot prompt lives inside ``_build_store``
    which ReplSession.run() calls internally.
    """
    _main(["--game", "l4d2", "--repl", "--no-cache"])
    mock_main_deps["ReplSession"].assert_called_once()
    _args_passed = mock_main_deps["ReplSession"].call_args[0][1]
    assert _args_passed.no_cache is True
    assert _args_passed.yes is False


@pytest.mark.xfail(strict=True, reason="BUG R06: no WARNING when --no-cache and --clean-cache both given")
def test_r06_no_cache_and_clean_cache(mock_build_store_deps, caplog) -> None:
    """R06 (BUG): --no-cache + --clean-cache → redundant, no WARNING emitted."""
    caplog.set_level(logging.WARNING)
    config = make_config()
    args = make_args(no_cache=True, clean_cache=True)
    _build_store(config, args)
    # Should warn that the combination is redundant
    assert any(
        "no-cache" in msg.lower() and "clean" in msg.lower()
        for msg in caplog.messages
    ), "Expected a WARNING about --no-cache and --clean-cache redundancy"


def test_r07_repl_clean_cache(mock_build_store_deps) -> None:
    """R07: --repl --clean-cache is valid — cache deleted, rebuilt, then saved.

    The updated doc clarifies that ``--clean-cache`` alone is one-shot:
    delete → rebuild → save.  Only when combined with ``--no-cache``
    (use_cache=False) is the cache persistently cold.
    """
    config = make_config()
    args = make_args(repl=True, clean_cache=True)
    store, vfs = _build_store(config, args)
    assert store is not None
    # _build_store should have called invalidate_cache on the builder
    mock_build_store_deps["vfs_instance"].invalidate_cache.assert_called_once()
    # Builder should have been created with use_cache=True (cache is saved
    # after rebuild).  The VfsBuilder constructor is called as:
    #   VfsBuilder(game_root, config, use_cache=use_cache, num_workers=num_workers)
    # where use_cache defaults to True for --clean-cache without --no-cache.
    _call_kwargs = mock_build_store_deps["vfs_builder_cls"].call_args[1]
    assert _call_kwargs.get("use_cache", False) is True, (
        "--clean-cache without --no-cache should build with use_cache=True"
    )


def test_r08_repl_yes_skips_confirmation(mock_build_store_deps) -> None:
    """R08: --repl --yes skips cold-boot confirmation (no input() call)."""
    config = make_config()
    args = make_args(repl=True, yes=True, no_cache=True)
    with patch("builtins.input") as mock_input:
        store, vfs = _build_store(config, args)
    assert store is not None
    mock_input.assert_not_called()


# ===================================================================
# 3.3  Resource limits  (R09-R11)
# ===================================================================


def test_r09_nolimit_overrides_cpu(mock_main_deps) -> None:
    """R09: --nolimit overrides --cpu → num_workers=0 (unlimited)."""
    mock_main_deps["load_config"].return_value = make_config(num_workers=4)
    _main(["--game", "l4d2", "--analyze", "--cpu", "8", "--nolimit"])
    config_arg = mock_main_deps["cmd_analyze"].call_args[0][0]
    assert config_arg.general.num_workers == 0, "nolimit should force 0 workers"


def test_r09_nolimit_overrides_memory(mock_main_deps) -> None:
    """R09: --nolimit overrides --memory — worker count set to 0 regardless."""
    mock_main_deps["load_config"].return_value = make_config(num_workers=2)
    _main(["--game", "l4d2", "--analyze", "--memory", "4GB", "--nolimit"])
    config_arg = mock_main_deps["cmd_analyze"].call_args[0][0]
    assert config_arg.general.num_workers == 0


def test_r10_cpu_zero_is_auto(mock_main_deps) -> None:
    """R10: --cpu 0 → auto (cpu_count-1)."""
    mock_main_deps["load_config"].return_value = make_config(num_workers=0)
    _main(["--game", "l4d2", "--analyze", "--cpu", "0"])
    config_arg = mock_main_deps["cmd_analyze"].call_args[0][0]
    expected = max(1, (__import__("os").cpu_count() or 2) - 1)
    assert config_arg.general.num_workers == expected


def test_r11_memory_zero_parse() -> None:
    """R11: --memory "0" → _parse_memory_limit returns 0 (bypass)."""
    assert _parse_memory_limit("0") == 0


def test_r11_memory_none_returns_none() -> None:
    """Empty memory string returns None from _parse_memory_limit."""
    assert _parse_memory_limit("") is None
    assert _parse_memory_limit(None) is None  # type: ignore[arg-type]


# ===================================================================
# 3.4  Check filters  (R12-R14)
# ===================================================================


def test_r12_check_all_dominates_single() -> None:
    """R12: --check-all + --check-textures → check-all dominates (all exts returned)."""
    args = make_args(check_all=True, check_textures=True)
    exts = _get_check_extensions(args)
    assert exts is not None
    # All known extensions should be present
    all_known: set[str] = {
        ".vmt", ".vtf", ".tga", ".png", ".jpg",
        ".mdl", ".vvd", ".vtx", ".phy", ".ani",
        ".wav", ".mp3", ".ogg",
        ".nut", ".nuc",
        ".cfg", ".txt", ".res",
        ".bsp",
        "_manifest.txt",
    }
    assert exts == all_known


def test_r12_check_all_without_single() -> None:
    """--check-all alone also returns all extensions."""
    args = make_args(check_all=True)
    exts = _get_check_extensions(args)
    all_known = {".vmt", ".vtf", ".tga", ".png", ".jpg",
                 ".mdl", ".vvd", ".vtx", ".phy", ".ani",
                 ".wav", ".mp3", ".ogg",
                 ".nut", ".nuc",
                 ".cfg", ".txt", ".res",
                 ".bsp",
                 "_manifest.txt"}
    assert exts == all_known


def test_r13_check_filters_called_in_cmd_analyze() -> None:
    """R13: analyze mode calls _apply_check_filters (via cmd_analyze)."""
    with (
        patch("parallelines.cli._build_store") as mock_build,
        patch("parallelines.cli.print_summary_from_store"),
        patch("parallelines.cli.generate_report_from_store", return_value="/rpt"),
        patch("parallelines.cli._apply_check_filters") as mock_apply,
    ):
        mock_build.return_value = (MagicMock(), MagicMock())
        config = make_config()
        args = make_args(analyze=True, check_textures=True)
        cmd_analyze(config, args)
        mock_apply.assert_called_once()


@pytest.mark.xfail(strict=True, reason="BUG R14: --check-* filters silently ignored in REPL mode")
def test_r14_repl_check_filters_ignored(mock_main_deps, caplog) -> None:
    """R14 (BUG): --repl --check-textures → filter NOT applied, no WARNING."""
    caplog.set_level(logging.WARNING)
    _main(["--game", "l4d2", "--repl", "--check-textures"])
    mock_main_deps["ReplSession"].assert_called_once()
    # Should warn that check-* filters are ignored in REPL mode
    assert any(
        "check" in msg.lower() and "repl" in msg.lower()
        for msg in caplog.messages
    ), "Expected a WARNING about --check-* being ignored in REPL"


# ===================================================================
# 3.5  Output parameters  (R15-R17)
# ===================================================================


def test_r15_help_with_output_params(mock_main_deps) -> None:
    """R15: help mode + output params → no report generated (harmless)."""
    result = _main(["--game", "l4d2", "--format", "html", "--output-dir", "/tmp"])
    assert result == 0
    mock_main_deps["cmd_analyze"].assert_not_called()
    mock_main_deps["cmd_external"].assert_not_called()


def test_r16_repl_format_ignored(mock_main_deps) -> None:
    """R16: --repl --format html → format set on config but ignored by REPL."""
    _main(["--game", "l4d2", "--repl", "--format", "html"])
    config_arg = mock_main_deps["ReplSession"].call_args[0][0]
    assert config_arg.output.format == "html"


def test_r17_graphviz_in_analyze_mode(mock_build_store_deps) -> None:
    """R17: --analyze --graphviz → graphviz generated in _build_store."""
    with patch("parallelines.report.graphviz.generate_dot") as mock_gen_dot:
        mock_gen_dot.return_value = "/tmp/graph.dot"
        config = make_config()
        args = make_args(analyze=True, graphviz="/tmp/graph.dot")
        store, vfs = _build_store(config, args)
        assert store is not None
        mock_gen_dot.assert_called_once()


def test_r17_graphviz_in_external_mode(mock_build_store_deps) -> None:
    """R17: --external --graphviz → graphviz generated in _build_store."""
    with patch("parallelines.report.graphviz.generate_dot") as mock_gen_dot:
        mock_gen_dot.return_value = "/tmp/graph.dot"
        config = make_config()
        args = make_args(external="test.vpk", graphviz="/tmp/graph.dot")
        store, vfs = _build_store(config, args)
        assert store is not None
        mock_gen_dot.assert_called_once()


def test_r17_graphviz_in_repl_mode(mock_build_store_deps) -> None:
    """R17: --repl --graphviz → graphviz generated in _build_store.

    The updated doc confirms graphviz works in ALL three modes since
    the ``.dot`` generation happens inside ``_build_store()``.
    """
    with patch("parallelines.report.graphviz.generate_dot") as mock_gen_dot:
        mock_gen_dot.return_value = "/tmp/graph.dot"
        config = make_config()
        args = make_args(repl=True, graphviz="/tmp/graph.dot")
        store, vfs = _build_store(config, args)
        assert store is not None
        mock_gen_dot.assert_called_once()


# ===================================================================
# 3.6  External VPK  (R18-R20)
# ===================================================================


def test_r18_external_vpk_priority_lowest(mock_build_store_deps) -> None:
    """R18: --external --vpk-priority lowest → priority=-100 in cmd_external.

    We test this by patching _build_store and calling cmd_external directly.
    """
    from parallelines.engine import Relation

    mock_store = MagicMock()
    mock_store.load_reference = MagicMock()
    mock_store.external_files = MagicMock()
    mock_store.external_files.__len__.return_value = 10
    # _print_reference_results iterates execute() results as Relations.
    mock_store.execute.return_value = Relation(
        "result", ("virtual_path",), [("maps/test.bsp",)]
    )

    with (
        patch("parallelines.cli._build_store") as mock_build,
        patch("parallelines.cli.Path.exists", return_value=True),
        patch("parallelines.cli.Path.is_absolute", return_value=True),
    ):
        mock_build.return_value = (mock_store, MagicMock())

        config = make_config()
        args = make_args(external="/path/to/test.vpk", vpk_priority="lowest")

        # Patch _find_queries_dir to return a temp dir with preset JSON files.
        import json
        import pathlib
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir_str:
            tmpdir = pathlib.Path(tmpdir_str)
            for preset in ("external_overrides", "external_overridden", "external_new_files"):
                (tmpdir / f"{preset}.json").write_text(
                    json.dumps({"columns": ["virtual_path"], "rows": [["maps/test.bsp"]]}),
                    encoding="utf-8",
                )
            with patch("parallelines.cli._find_queries_dir", return_value=tmpdir):
                result = cmd_external(config, args)
        assert result == 0

        # Verify priority was set to -100 for "lowest"
        load_call = mock_store.load_reference.call_args
        assert load_call is not None
        # load_reference(name, path, priority=...) → priority is a kwarg
        assert load_call.kwargs.get("priority") == -100, (
            "vpk_priority='lowest' should map to priority=-100"
        )


@pytest.mark.xfail(strict=True, reason="BUG R19: vpk-priority ignored in REPL mode (hardcoded 2000)")
def test_r19_repl_external_vpk_priority_hardcoded() -> None:
    """R19 (BUG): --repl --external --vpk-priority lowest → priority=2000 hardcoded.

    ReplSession.load_external_vpk() always passes priority=2000 regardless
    of the --vpk-priority CLI argument.
    """
    from parallelines.repl.session import ReplSession

    config = make_config()
    args = make_args(repl=True, external="test.vpk", vpk_priority="lowest")
    store = MagicMock()
    store.load_reference = MagicMock()

    session = ReplSession(config, args)
    session.store = store  # bypass _build_store
    import tempfile, pathlib
    tmp_vpk = pathlib.Path(tempfile.mktemp(suffix=".vpk"))
    tmp_vpk.write_text("not a real vpk")
    try:
        session.load_external_vpk(str(tmp_vpk))
    finally:
        tmp_vpk.unlink()

    store.load_reference.assert_called_once()
    # The correct behaviour would be priority=-100 (from --vpk-priority lowest).
    # The bug: load_external_vpk hardcodes priority=2000, ignoring the flag.
    call_kwargs = store.load_reference.call_args[1]
    assert call_kwargs.get("priority") == -100, (
        "BUG: load_external_vpk hardcodes priority=2000, ignoring --vpk-priority"
    )


@pytest.mark.xfail(strict=True, reason="BUG R20: --ref-query outside --external silently ignored, no warning")
def test_r20_ref_query_outside_external(mock_main_deps, caplog) -> None:
    """R20 (BUG): --ref-query overrides without --external → silently ignored."""
    caplog.set_level(logging.WARNING)
    _main(["--game", "l4d2", "--analyze", "--ref-query", "overrides"])
    mock_main_deps["cmd_analyze"].assert_called_once()
    # Should warn that --ref-query only applies in --external mode
    assert any(
        "ref-query" in msg.lower() or "ref_query" in msg.lower()
        for msg in caplog.messages
    ), "Expected a WARNING about --ref-query having no effect outside --external"


# ===================================================================
# 3.7  Entry points & analysis extensions  (R21-R24)
# ===================================================================


@pytest.mark.xfail(strict=True, reason="BUG R21: --sv-pure has no effect in REPL mode")
def test_r21_repl_sv_pure_ignored(mock_main_deps, caplog) -> None:
    """R21 (CRITICAL BUG): --repl --sv-pure → whitelist NOT applied.

    The sv-pure filtering only runs inside cmd_analyze() (cli.py lines 807-828).
    REPL mode dispatches to ReplSession which never enters cmd_analyze.
    """
    caplog.set_level(logging.WARNING)
    _main(["--game", "l4d2", "--repl", "--sv-pure", "/path/to/whitelist.txt"])
    mock_main_deps["ReplSession"].assert_called_once()
    mock_main_deps["cmd_analyze"].assert_not_called()
    # Should at minimum warn that --sv-pure is ineffective in REPL
    assert any(
        "sv_pure" in msg.lower() or "sv-pure" in msg.lower() or "whitelist" in msg.lower()
        for msg in caplog.messages
    ), "Expected a WARNING about --sv-pure being ignored in REPL mode"


def test_r21_repl_compare_maps_works(mock_build_store_deps) -> None:
    """R21 exception: --compare-maps works in REPL mode.

    The updated doc explicitly carves out ``--compare-maps`` from the REPL
    restriction: ``compare-maps 在 _build_store() 中处理，在 REPL 模式下正常工作``.
    """
    with patch("parallelines.parsers.vpk_parser.parse_vpk_index") as mock_parse:
        mock_parse.return_value = []
        config = make_config()
        args = make_args(repl=True, compare_maps=["addon1.vpk"])
        store, vfs = _build_store(config, args)
    assert store is not None
    mock_parse.assert_called_once()


def test_r22_no_entry_points_or_maps_auto_discover(mock_build_store_deps) -> None:
    """R22: No entry-points or maps → discover_entry_points() called."""
    config = make_config()
    args = make_args(entry_points=None, maps=None)
    _build_store(config, args)
    mock_build_store_deps["discover_eps"].assert_called_once()


def test_r23_entry_points_and_maps_merged(mock_build_store_deps) -> None:
    """R23: Both entry-points and maps → merged set passed to ResultStore."""
    config = make_config()
    args = make_args(entry_points=["root/script.nut"], maps=["c1m1_hotel"])
    store, vfs = _build_store(config, args)
    assert store is not None
    # discover_entry_points should NOT be called when explicit entry_points given
    mock_build_store_deps["discover_eps"].assert_not_called()
    # The merged set should contain both sources
    call_kwargs = mock_build_store_deps["from_analysis"].call_args[1]
    merged = call_kwargs["entry_points"]
    assert "root/script.nut" in merged
    assert "maps/c1m1_hotel.bsp" in merged


def test_r24_external_with_entry_points(mock_build_store_deps) -> None:
    """R24: --external with entry-points still works (entry_points honored)."""
    config = make_config()
    args = make_args(external="test.vpk", entry_points=["custom/path.txt"])
    store, vfs = _build_store(config, args)
    assert store is not None
    call_kwargs = mock_build_store_deps["from_analysis"].call_args[1]
    assert "custom/path.txt" in call_kwargs["entry_points"]


# ===================================================================
# 3.8  Global constraints  (R25-R28)
# ===================================================================


def test_r25_empty_game_root(mock_main_deps) -> None:
    """R25: --game-root "" without --list-presets → print_help + exit(1)."""
    mock_main_deps["load_config"].return_value = make_config(game_root="")
    result = _main(["--game", "l4d2", "--analyze"])
    assert result == 1


def test_r26_debug_overrides_log_level(mock_main_deps) -> None:
    """R26: --debug overrides --log-level WARNING → log_level=DEBUG."""
    mock_main_deps["load_config"].return_value = make_config(log_level="WARNING")
    _main(["--game", "l4d2", "--analyze", "--debug", "--log-level", "WARNING"])
    config_arg = mock_main_deps["cmd_analyze"].call_args[0][0]
    assert config_arg.general.log_level == "DEBUG"


def test_r27_lang_zh(mock_main_deps) -> None:
    """R27: --lang zh → set_language('zh') called."""
    _main(["--game", "l4d2", "--analyze", "--lang", "zh"])
    mock_main_deps["set_language"].assert_called_once_with("zh")


def test_r27_lang_en(mock_main_deps) -> None:
    """--lang en → set_language('en') called."""
    _main(["--game", "l4d2", "--analyze", "--lang", "en"])
    mock_main_deps["set_language"].assert_called_once_with("en")


def test_r28_version_exits_immediately() -> None:
    """R28: --version exits immediately; all other params ignored.

    argparse's ``action="version"`` triggers SystemExit before any required-
    argument check, so --game is not needed.
    """
    for argv in [
        ["--version"],
        ["--version", "--analyze"],
        ["--version", "--repl", "--no-cache", "--game", "l4d2"],
        ["--version", "--external", "test.vpk"],
    ]:
        with pytest.raises(SystemExit) as exc_info:
            build_parser().parse_args(argv)
        assert exc_info.value.code == 0


# ===================================================================
# 3.2 (supplement)  _build_store with EOFError → exit(1) via cmd_analyze
# ===================================================================


def test_r05a_exit_via_cmd_analyze() -> None:
    """Verify that _build_store returning (None, None) makes cmd_analyze return 1."""
    with patch("parallelines.cli._build_store", return_value=(None, None)):
        result = cmd_analyze(make_config(), make_args(analyze=True))
    assert result == 1


# ===================================================================
# 3.5 (supplement)  _apply_check_filters functional test
# ===================================================================


def test_apply_check_filters_hash_conflicts() -> None:
    """_apply_check_filters correctly filters hash_conflicts by extension."""
    from parallelines.engine import Relation

    mock_hash_rel = Relation(
        "hash_conflicts",
        ("virtual_path", "priority", "source_name"),
        [
            SimpleNamespace(virtual_path="maps/c1m1.bsp", priority=10, source_name="addon1"),
            SimpleNamespace(virtual_path="materials/wall.vmt", priority=10, source_name="addon1"),
            SimpleNamespace(virtual_path="sound/boom.wav", priority=10, source_name="addon2"),
        ],
    )
    mock_dep_rel = Relation(
        "dep_conflicts",
        ("from_path", "to_path", "priority"),
        [],
    )
    store = MagicMock()
    store.hash_conflicts = mock_hash_rel
    store.dep_conflicts = mock_dep_rel

    args = make_args(check_textures=True)
    _apply_check_filters(store, args)

    # Only .vmt rows should remain in hash_conflicts
    assert store.hash_conflicts is not None
    remaining = list(store.hash_conflicts.rows)
    assert len(remaining) == 1
    assert remaining[0].virtual_path == "materials/wall.vmt"


# ===================================================================
# 7.  Coverage matrix – meta test
# ===================================================================

# Every rule R01-R28 mapped to the primary test function(s) that cover it.
# When adding a new test for a rule, update this dict so the meta-test stays
# in sync.
COVERAGE_MAP: dict[str, list[str]] = {
    "R01": ["test_r01_mode_help"],
    "R02": ["test_r02_analyze_wins_over_external"],
    "R03": ["test_r03_analyze_wins_over_repl"],
    "R04": ["test_r04_external_wins_over_repl"],
    "R05": ["test_r05a_no_cache_eof_error", "test_r05a_exit_via_cmd_analyze", "test_r05b_repl_no_cache_cold_boot"],
    "R05a": ["test_r05a_no_cache_eof_error", "test_r05a_exit_via_cmd_analyze"],
    "R05b": ["test_r05b_repl_no_cache_cold_boot"],
    "R06": ["test_r06_no_cache_and_clean_cache"],
    "R07": ["test_r07_repl_clean_cache"],
    "R08": ["test_r08_repl_yes_skips_confirmation"],
    "R09": ["test_r09_nolimit_overrides_cpu", "test_r09_nolimit_overrides_memory"],
    "R10": ["test_r10_cpu_zero_is_auto"],
    "R11": ["test_r11_memory_zero_parse", "test_r11_memory_none_returns_none"],
    "R12": ["test_r12_check_all_dominates_single", "test_r12_check_all_without_single"],
    "R13": ["test_r13_check_filters_called_in_cmd_analyze"],
    "R14": ["test_r14_repl_check_filters_ignored"],
    "R15": ["test_r15_help_with_output_params"],
    "R16": ["test_r16_repl_format_ignored"],
    "R17": [
        "test_r17_graphviz_in_analyze_mode",
        "test_r17_graphviz_in_external_mode",
        "test_r17_graphviz_in_repl_mode",
    ],
    "R18": ["test_r18_external_vpk_priority_lowest"],
    "R19": ["test_r19_repl_external_vpk_priority_hardcoded"],
    "R20": ["test_r20_ref_query_outside_external"],
    "R21": ["test_r21_repl_sv_pure_ignored", "test_r21_repl_compare_maps_works"],
    "R22": ["test_r22_no_entry_points_or_maps_auto_discover"],
    "R23": ["test_r23_entry_points_and_maps_merged"],
    "R24": ["test_r24_external_with_entry_points"],
    "R25": ["test_r25_empty_game_root"],
    "R26": ["test_r26_debug_overrides_log_level"],
    "R27": ["test_r27_lang_zh", "test_r27_lang_en"],
    "R28": ["test_r28_version_exits_immediately"],
}


def test_coverage_matrix() -> None:
    """Section 7 meta-test: verify every R01-R28 has at least one test defined.

    This test fails if:
    - A rule in COVERAGE_MAP references a non-existent test function.
    - There are uncovered rules (missing from COVERAGE_MAP).
    """
    this_module = sys.modules[__name__]

    # All rules 01-28 must appear in the map
    expected_rules = {f"R{i:02d}" for i in range(1, 29)}
    actual_rules = set(COVERAGE_MAP.keys())
    missing = expected_rules - actual_rules
    assert not missing, f"Rules missing from COVERAGE_MAP: {sorted(missing)}"

    # Every referenced test must exist in the module
    for rule, test_names in COVERAGE_MAP.items():
        for tname in test_names:
            assert hasattr(this_module, tname), (
                f"{rule}: test function '{tname}' not found in test module"
            )
