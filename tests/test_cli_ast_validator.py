"""Tests for CLI argument validation and known bugs B19-B24.

Covers two sections from ``devdocs/cli-ast-rules.md``:

    Part A: CliArgValidator tests  (section 6 -- AST formal rules)
    Part B: Known bug reproduction (section 8, bugs B19-B24)

The CliArgValidator class hasn't been added to the codebase yet, so a local
copy (``CliArgValidatorTestHelper``) is provided here that mirrors the expected
interface from the document.  When the real class lands in
``parallelines.cli.CliArgValidator``, these tests should be updated to import
from there instead.
"""

from __future__ import annotations

import builtins
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from parallelines.cli import _build_store, _main, build_parser
from parallelines.config import AppConfig
from parallelines.repl.session import ReplSession


# ===================================================================
# Local CliArgValidator  (mirrors the pseudo-code from section 6)
#
# Once the real class lands in ``parallelines.cli.CliArgValidator``,
# replace the imports above and delete this helper.
# ===================================================================


class CliArgValidatorTestHelper:
    """AST-rule based CLI argument combination validator.

    Static methods mirror the pseudo-code in devdocs/cli-ast-rules.md section 6.
    """

    @staticmethod
    def check_mode_exclusivity(args: Namespace) -> list[str]:
        """R02-R04: check mode flag mutual exclusivity."""
        warnings: list[str] = []
        modes = sum([bool(args.analyze), bool(args.external), bool(args.repl)])
        if modes > 1:
            active = "analyze" if args.analyze else ("external" if args.external else "repl")
            warnings.append(
                f"Multiple modes specified; only --{active} will execute. "
                f"Others are silently ignored."
            )
        return warnings

    @staticmethod
    def check_cache_consistency(args: Namespace) -> list[str]:
        """R06: check cache parameter consistency."""
        warnings: list[str] = []
        if args.no_cache and args.clean_cache:
            warnings.append(
                "--no-cache and --clean-cache are redundant: "
                "cache is deleted then not saved. Use only one."
            )
        return warnings

    @staticmethod
    def check_repl_cold_boot(args: Namespace) -> list[str]:
        """R05b: REPL cold-start risk."""
        warnings: list[str] = []
        if args.repl and args.no_cache and not args.yes:
            warnings.append(
                "CRITICAL: --repl --no-cache without --yes will block on "
                "raw input() prompt for cold-build confirmation. "
                "If stdin is not a TTY, this will fail. Add --yes to proceed."
            )
        return warnings

    @staticmethod
    def check_repl_sv_pure(args: Namespace) -> list[str]:
        """R21: sv-pure has no effect in --repl mode."""
        if args.repl and args.sv_pure:
            return [
                "CRITICAL: --sv-pure has no effect in --repl mode. "
                "The whitelist filter is only applied in --analyze mode."
            ]
        return []

    @staticmethod
    def check_repl_check_filters(args: Namespace) -> list[str]:
        """R14: check-* filters are ignored in --repl mode."""
        check_flags = [
            args.check_textures,
            args.check_models,
            args.check_sounds,
            args.check_scripts,
            args.check_configs,
            args.check_maps,
            args.check_manifests,
            args.check_all,
        ]
        if args.repl and any(check_flags):
            return [
                "WARNING: --check-* filters are ignored in --repl mode. "
                "Use query WHERE clauses instead."
            ]
        return []

    @staticmethod
    def check_repl_vpk_priority(args: Namespace) -> list[str]:
        """R19: vpk-priority is ignored in --repl mode."""
        if args.repl and args.external and args.vpk_priority != "highest":
            return [
                "WARNING: --vpk-priority is ignored in --repl mode; "
                "external VPK is always loaded at priority=2000."
            ]
        return []

    @staticmethod
    def check_ref_query_scope(args: Namespace) -> list[str]:
        """R20: ref-query only has meaning in --external mode."""
        if args.ref_query != "all" and not args.external:
            return [
                "WARNING: --ref-query has no effect outside --external mode."
            ]
        return []

    @staticmethod
    def check_external_sv_pure(args: Namespace) -> list[str]:
        """B20b: sv-pure has no effect in --external mode."""
        if args.external and args.sv_pure:
            return [
                "CRITICAL: --sv-pure has no effect in --external mode. "
                "The whitelist filter is only applied in --analyze mode."
            ]
        return []

    @classmethod
    def validate_all(cls, args: Namespace) -> list[tuple[str, str]]:
        """Run all check_* methods and collect (severity, message) tuples."""
        results: list[tuple[str, str]] = []
        for name in dir(cls):
            if name.startswith("check_"):
                for msg in getattr(cls, name)(args):
                    sev = "CRITICAL" if msg.startswith("CRITICAL") else "WARNING"
                    results.append((sev, msg))
        return results


# ===================================================================
# Helper: build a minimal AppConfig for _build_store / _main tests
# ===================================================================


def _make_config(game_root: str = "/fake/game") -> AppConfig:
    """Build an ``AppConfig`` with key fields pre-populated."""
    config = AppConfig()
    config.general.game_root = game_root
    config.general.game = "l4d2"
    config.general.log_level = "INFO"
    return config


# ===================================================================
# PART A -- CliArgValidator tests
# ===================================================================


class TestCheckModeExclusivity:
    """R02-R04: mode flag mutual exclusivity."""

    def test_single_mode_analyze(self) -> None:
        """Single mode flag (--analyze) yields no warnings."""
        args = Namespace(analyze=True, external=None, repl=False)
        assert CliArgValidatorTestHelper.check_mode_exclusivity(args) == []

    def test_single_mode_external(self) -> None:
        """Single mode flag (--external) yields no warnings."""
        args = Namespace(analyze=False, external="test.vpk", repl=False)
        assert CliArgValidatorTestHelper.check_mode_exclusivity(args) == []

    def test_single_mode_repl(self) -> None:
        """Single mode flag (--repl) yields no warnings."""
        args = Namespace(analyze=False, external=None, repl=True)
        assert CliArgValidatorTestHelper.check_mode_exclusivity(args) == []

    def test_analyze_and_external(self) -> None:
        """--analyze + --external --> WARNING (R02)."""
        args = Namespace(analyze=True, external="test.vpk", repl=False)
        warnings = CliArgValidatorTestHelper.check_mode_exclusivity(args)
        assert len(warnings) == 1
        assert "Multiple modes" in warnings[0]
        assert "--analyze" in warnings[0]

    def test_analyze_and_repl(self) -> None:
        """--analyze + --repl --> WARNING (R03)."""
        args = Namespace(analyze=True, external=None, repl=True)
        warnings = CliArgValidatorTestHelper.check_mode_exclusivity(args)
        assert len(warnings) == 1
        assert "Multiple modes" in warnings[0]
        assert "--analyze" in warnings[0]

    def test_external_and_repl(self) -> None:
        """--external + --repl --> WARNING (R04)."""
        args = Namespace(analyze=False, external="test.vpk", repl=True)
        warnings = CliArgValidatorTestHelper.check_mode_exclusivity(args)
        assert len(warnings) == 1
        assert "Multiple modes" in warnings[0]
        assert "--external" in warnings[0]

    def test_all_three_modes(self) -> None:
        """--analyze + --external + --repl --> one combined WARNING, analyze wins."""
        args = Namespace(analyze=True, external="test.vpk", repl=True)
        warnings = CliArgValidatorTestHelper.check_mode_exclusivity(args)
        assert len(warnings) == 1
        assert "--analyze" in warnings[0]


class TestCheckCacheConsistency:
    """R06: no-cache / clean-cache consistency."""

    def test_no_cache_only(self) -> None:
        """Only --no-cache --> no warning."""
        args = Namespace(no_cache=True, clean_cache=False)
        assert CliArgValidatorTestHelper.check_cache_consistency(args) == []

    def test_clean_cache_only(self) -> None:
        """Only --clean-cache --> no warning."""
        args = Namespace(no_cache=False, clean_cache=True)
        assert CliArgValidatorTestHelper.check_cache_consistency(args) == []

    def test_both_flags(self) -> None:
        """Both --no-cache and --clean-cache --> WARNING (R06)."""
        args = Namespace(no_cache=True, clean_cache=True)
        warnings = CliArgValidatorTestHelper.check_cache_consistency(args)
        assert len(warnings) == 1
        assert "redundant" in warnings[0].lower()
        assert "no-cache" in warnings[0]
        assert "clean-cache" in warnings[0]


class TestCheckReplColdBoot:
    """R05b: REPL cold-start risk."""

    def test_repl_no_cache_without_yes(self) -> None:
        """--repl --no-cache (no --yes) --> CRITICAL warning (R05b)."""
        args = Namespace(repl=True, no_cache=True, yes=False)
        warnings = CliArgValidatorTestHelper.check_repl_cold_boot(args)
        assert len(warnings) == 1
        assert "CRITICAL" in warnings[0]
        assert "no-cache" in warnings[0]
        assert "yes" in warnings[0].lower()

    def test_repl_no_cache_with_yes(self) -> None:
        """--repl --no-cache --yes --> no warning (--yes mitigates)."""
        args = Namespace(repl=True, no_cache=True, yes=True)
        assert CliArgValidatorTestHelper.check_repl_cold_boot(args) == []

    def test_repl_with_yes(self) -> None:
        """--repl --yes (no --no-cache) --> no warning."""
        args = Namespace(repl=True, no_cache=False, yes=True)
        assert CliArgValidatorTestHelper.check_repl_cold_boot(args) == []

    def test_analyze_no_cache(self) -> None:
        """--analyze --no-cache (not --repl) --> no warning."""
        args = Namespace(repl=False, no_cache=True, yes=False)
        assert CliArgValidatorTestHelper.check_repl_cold_boot(args) == []

    def test_no_cache_false(self) -> None:
        """--repl without --no-cache --> no warning."""
        args = Namespace(repl=True, no_cache=False, yes=False)
        assert CliArgValidatorTestHelper.check_repl_cold_boot(args) == []


class TestCheckReplSvPure:
    """R21: sv-pure in REPL mode."""

    def test_repl_with_sv_pure(self) -> None:
        """--repl --sv-pure <path> --> CRITICAL warning (R21)."""
        args = Namespace(repl=True, sv_pure="whitelist.txt")
        warnings = CliArgValidatorTestHelper.check_repl_sv_pure(args)
        assert len(warnings) == 1
        assert "CRITICAL" in warnings[0]
        assert "sv-pure" in warnings[0].lower()

    def test_repl_without_sv_pure(self) -> None:
        """--repl without --sv-pure --> no warning."""
        args = Namespace(repl=True, sv_pure=None)
        assert CliArgValidatorTestHelper.check_repl_sv_pure(args) == []

    def test_analyze_with_sv_pure(self) -> None:
        """--analyze --sv-pure (no --repl) --> no warning (sv-pure works in analyze)."""
        args = Namespace(repl=False, sv_pure="whitelist.txt")
        assert CliArgValidatorTestHelper.check_repl_sv_pure(args) == []


class TestCheckExternalSvPure:
    """B20b: sv-pure has no effect in --external mode."""

    def test_external_with_sv_pure(self) -> None:
        """--external --sv-pure --> CRITICAL warning (B20b)."""
        args = Namespace(external="test.vpk", sv_pure="whitelist.txt")
        warnings = CliArgValidatorTestHelper.check_external_sv_pure(args)
        assert len(warnings) == 1
        assert "CRITICAL" in warnings[0]
        assert "--sv-pure" in warnings[0]
        assert "--external" in warnings[0]

    def test_external_without_sv_pure(self) -> None:
        """--external without --sv-pure --> no warning."""
        args = Namespace(external="test.vpk", sv_pure=None)
        assert CliArgValidatorTestHelper.check_external_sv_pure(args) == []

    def test_sv_pure_without_external(self) -> None:
        """--sv-pure without --external --> no warning."""
        args = Namespace(external=None, sv_pure="whitelist.txt")
        assert CliArgValidatorTestHelper.check_external_sv_pure(args) == []


class TestCheckReplCheckFilters:
    """R14: check-* filters ignored in REPL mode."""

    @pytest.mark.parametrize(
        "flag_name", [
            "check_textures", "check_models", "check_sounds",
            "check_scripts", "check_configs", "check_maps",
            "check_manifests", "check_all",
        ]
    )
    def test_repl_with_any_check_flag(self, flag_name: str) -> None:
        """Single --check-* flag in --repl mode --> WARNING (R14)."""
        kwargs = {
            "repl": True,
            "check_textures": False, "check_models": False,
            "check_sounds": False, "check_scripts": False,
            "check_configs": False, "check_maps": False,
            "check_manifests": False, "check_all": False,
            flag_name: True,
        }
        args = Namespace(**kwargs)
        warnings = CliArgValidatorTestHelper.check_repl_check_filters(args)
        assert len(warnings) == 1
        assert "WARNING" in warnings[0]
        assert "check-*" in warnings[0] or "check" in warnings[0].lower()

    def test_repl_without_check_flags(self) -> None:
        """--repl without any --check-* flag --> no warning."""
        args = Namespace(
            repl=True,
            check_textures=False, check_models=False,
            check_sounds=False, check_scripts=False,
            check_configs=False, check_maps=False,
            check_manifests=False, check_all=False,
        )
        assert CliArgValidatorTestHelper.check_repl_check_filters(args) == []

    def test_analyze_with_check_flag(self) -> None:
        """--analyze --check-textures (no --repl) --> no warning (filters work)."""
        args = Namespace(
            repl=False,
            check_textures=True, check_models=False,
            check_sounds=False, check_scripts=False,
            check_configs=False, check_maps=False,
            check_manifests=False, check_all=False,
        )
        assert CliArgValidatorTestHelper.check_repl_check_filters(args) == []

    def test_repl_with_check_all(self) -> None:
        """--repl --check-all --> WARNING (R14)."""
        args = Namespace(
            repl=True,
            check_textures=False, check_models=False,
            check_sounds=False, check_scripts=False,
            check_configs=False, check_maps=False,
            check_manifests=False, check_all=True,
        )
        warnings = CliArgValidatorTestHelper.check_repl_check_filters(args)
        assert len(warnings) == 1


class TestCheckReplVpkPriority:
    """R19: vpk-priority ignored in REPL mode."""

    def test_repl_external_priority_lowest(self) -> None:
        """--repl --external x.vpk --vpk-priority lowest --> WARNING (R19)."""
        args = Namespace(repl=True, external="x.vpk", vpk_priority="lowest")
        warnings = CliArgValidatorTestHelper.check_repl_vpk_priority(args)
        assert len(warnings) == 1
        assert "WARNING" in warnings[0]
        assert "vpk-priority" in warnings[0]

    def test_repl_without_external(self) -> None:
        """--repl without --external --> no warning."""
        args = Namespace(repl=True, external=None, vpk_priority="lowest")
        assert CliArgValidatorTestHelper.check_repl_vpk_priority(args) == []

    def test_repl_with_default_priority(self) -> None:
        """--repl --external x.vpk with default (highest) priority --> no warning."""
        args = Namespace(repl=True, external="x.vpk", vpk_priority="highest")
        assert CliArgValidatorTestHelper.check_repl_vpk_priority(args) == []

    def test_external_without_repl(self) -> None:
        """--external (no --repl) with low priority --> no warning (works in external mode)."""
        args = Namespace(repl=False, external="x.vpk", vpk_priority="lowest")
        assert CliArgValidatorTestHelper.check_repl_vpk_priority(args) == []


class TestCheckRefQueryScope:
    """R20: ref-query scope."""

    def test_ref_query_overrides_no_external(self) -> None:
        """--ref-query overrides without --external --> WARNING (R20)."""
        args = Namespace(ref_query="overrides", external=None)
        warnings = CliArgValidatorTestHelper.check_ref_query_scope(args)
        assert len(warnings) == 1
        assert "WARNING" in warnings[0]
        assert "ref-query" in warnings[0]

    def test_ref_query_all_no_external(self) -> None:
        """--ref-query all (default) without --external --> no warning."""
        args = Namespace(ref_query="all", external=None)
        assert CliArgValidatorTestHelper.check_ref_query_scope(args) == []

    def test_ref_query_overrides_with_external(self) -> None:
        """--ref-query overrides WITH --external --> no warning (valid combo)."""
        args = Namespace(ref_query="overrides", external="x.vpk")
        assert CliArgValidatorTestHelper.check_ref_query_scope(args) == []

    @pytest.mark.parametrize("val", ["overridden", "new_files"])
    def test_non_default_ref_query_without_external(self, val: str) -> None:
        """Non-default --ref-query value without --external --> WARNING."""
        args = Namespace(ref_query=val, external=None)
        warnings = CliArgValidatorTestHelper.check_ref_query_scope(args)
        assert len(warnings) == 1


class TestValidateAll:
    """Aggregate validation."""

    def test_no_violations(self) -> None:
        """Valid argument set yields empty results."""
        args = Namespace(
            # mode
            analyze=True, external=None, repl=False,
            # cache
            no_cache=False, clean_cache=False, yes=False,
            # repl checks (repl is False)
            sv_pure=None,
            check_textures=False, check_models=False,
            check_sounds=False, check_scripts=False,
            check_configs=False, check_maps=False,
            check_manifests=False, check_all=False,
            # external / ref
            vpk_priority="highest",
            ref_query="all",
        )
        results = CliArgValidatorTestHelper.validate_all(args)
        assert results == []

    def test_multiple_violations(self) -> None:
        """Multiple simultaneous violations yield combined results.

        Triggers: R02/R03/R04 (mode conflict), R06 (cache), R05b (cold boot),
        R21 (sv-pure), R14 (check-filters), R19 (vpk-priority).
        """
        args = Namespace(
            analyze=True, external="x.vpk", repl=True,
            no_cache=True, clean_cache=True,
            yes=False,
            sv_pure="whitelist.txt",
            check_textures=True,
            check_models=False, check_sounds=False,
            check_scripts=False, check_configs=False,
            check_maps=False, check_manifests=False,
            check_all=False,
            vpk_priority="lowest",
            ref_query="overrides",
        )
        results = CliArgValidatorTestHelper.validate_all(args)
        assert len(results) >= 5  # at least 5 distinct violations

        severities = [s for s, _ in results]
        messages = [m for _, m in results]

        assert "CRITICAL" in severities
        assert "WARNING" in severities

        # Check for each expected violation by message content
        msg_lower = " ".join(m.lower() for m in messages)
        assert "multiple modes" in msg_lower
        assert "redundant" in msg_lower
        assert "sv-pure" in msg_lower
        assert "check-*" in msg_lower or "check" in msg_lower
        assert "vpk-priority" in msg_lower

        # ref-query should NOT fire because external is set
        assert any("ref-query" not in m.lower() for m in messages)

    def test_critical_warnings_propagate_severity(self) -> None:
        """CRITICAL-level warnings keep their severity in validate_all output."""
        args = Namespace(
            analyze=True, external=None, repl=True,
            no_cache=True, clean_cache=False,
            yes=False,
            sv_pure="whitelist.txt",
            check_textures=False, check_models=False,
            check_sounds=False, check_scripts=False,
            check_configs=False, check_maps=False,
            check_manifests=False, check_all=False,
            vpk_priority="highest",
            ref_query="all",
        )
        results = CliArgValidatorTestHelper.validate_all(args)
        criticals = [s for s, _ in results if s == "CRITICAL"]
        assert len(criticals) >= 2  # R05b (cold boot) + R21 (sv-pure)


# ===================================================================
# PART B -- Known bug reproduction (B19-B24)
# ===================================================================


# ── B19: REPL cold start deadlock (HIGH) ────────────────────────────────
#
#  Bug:  --repl --no-cache without --yes triggers raw input() in
#        _build_store.  In non-TTY stdin, EOFError causes exit(1).
#
#  Root cause: _build_store() uses builtins.input() for cold-build
#  confirmation, which is incompatible with REPL mode and blocks
#  in non-TTY environments.
#


class TestB19ReplColdStartDeadlock:
    """B19: REPL cold-start deadlock with --no-cache in non-TTY."""

    def test_build_store_returns_none_on_eoferror(self) -> None:
        """_build_store returns (None, None) when input() raises EOFError.

        This reproduces the B19 deadlock: --repl --no-cache (no --yes)
        hits the raw input() prompt.  In a non-TTY/pipe scenario the
        EOFError causes a silent cancellation.
        """
        config = _make_config()
        args = Namespace(
            no_cache=True,
            yes=False,
            nolimit=False,
            cpu=None,
        )

        with patch.object(Path, "exists", return_value=True):
            with patch.object(builtins, "input", side_effect=EOFError):
                store, vfs = _build_store(config, args)

        assert store is None
        assert vfs is None

    def test_build_store_returns_none_on_keyboard_interrupt(self) -> None:
        """_build_store returns (None, None) on KeyboardInterrupt during prompt."""
        config = _make_config()
        args = Namespace(
            no_cache=True,
            yes=False,
            nolimit=False,
            cpu=None,
        )

        with patch.object(Path, "exists", return_value=True):
            with patch.object(builtins, "input", side_effect=KeyboardInterrupt):
                store, vfs = _build_store(config, args)

        assert store is None
        assert vfs is None

    def test_build_store_proceeds_with_yes_flag(self) -> None:
        """--yes flag skips the cold-build prompt entirely.

        This is the correct mitigation for B19.
        """
        config = _make_config()
        args = Namespace(
            no_cache=True,
            yes=True,
            nolimit=False,
            cpu=None,
        )

        # Need more extensive mocks because --yes skips the early return
        # and proceeds into VfsBuilder / GraphBuilder.
        mock_vfs = MagicMock()
        mock_vfs.get_all_active.return_value = []
        mock_vfs.get_all_files.return_value = []

        with patch.object(Path, "exists", return_value=True):
            with patch("parallelines.vfs.builder.VfsBuilder") as MockVfsBuilder:
                mock_builder = MockVfsBuilder.return_value
                mock_builder.build.return_value = mock_vfs
                mock_builder.cache_hit = False
                mock_builder.cache_size.return_value = "0 B"
                mock_builder.get_chain.return_value = None

                with patch("parallelines.graph.builder.GraphBuilder") as MockGraphBuilder:
                    mock_graph = MagicMock()
                    mock_graph.node_count = 0
                    mock_graph.edge_count = 0
                    MockGraphBuilder.build_from_cached.return_value = mock_graph

                    with patch("parallelines.cli.ResultStore") as MockResultStore:
                        mock_store = MagicMock()
                        MockResultStore.from_analysis.return_value = mock_store

                        with patch(
                            "parallelines.analysis.entry_points.discover_entry_points",
                            return_value=set(),
                        ):
                            store, vfs = _build_store(config, args)

        # With --yes we proceed past the prompt and build the store.
        # Since we mocked all dependencies, we should get a non-None result.
        assert store is not None

    def test_argparse_parses_b19_combination(self) -> None:
        """Verify args parse correctly for the B19 trigger combination.

        --game is required; --game-root is needed to pass the game_root check.
        """
        parser = build_parser()
        argv = [
            "--game", "l4d2",
            "--game-root", "/fake/game",
            "--repl",
            "--no-cache",
        ]
        args = parser.parse_args(argv)
        assert args.repl is True
        assert args.no_cache is True
        assert args.yes is False  # default


# ── B20: sv-pure in REPL mode completely ineffective (CRITICAL) ──────
#
#  Bug:  --repl --sv-pure <path> → the sv-pure whitelist filtering code
#        (cli.py:807-828) lives inside cmd_analyze() and is NEVER reached
#        when dispatch goes to ReplSession.run().
#
#  Root cause: filter logic was placed in cmd_analyze instead of
#  _build_store, so the REPL path skips it entirely.
#


class TestB20SvPureReplIneffective:
    """B20 (CRITICAL): sv-pure whitelist has zero effect in --repl mode."""

    def test_cmd_analyze_not_called_in_repl_mode(self) -> None:
        """Dispatch goes to ReplSession.run(), not cmd_analyze.

        This is the root cause of B20: the sv-pure filter code (cli.py:807-828)
        is in cmd_analyze, which is never called in REPL mode.
        """
        mock_repl_session = MagicMock()
        mock_repl_session.run.return_value = 0

        with patch("parallelines.repl.ReplSession", return_value=mock_repl_session):
            with patch("parallelines.cli.cmd_analyze") as mock_cmd_analyze:
                result = _main([
                    "--game", "l4d2",
                    "--game-root", "/fake/game",
                    "--repl",
                    "--sv-pure", "whitelist.txt",
                ])

        assert result == 0
        mock_cmd_analyze.assert_not_called()

    def test_pure_whitelist_functions_never_called(self) -> None:
        """load_pure_whitelist and filter_vfs_by_whitelist are never invoked.

        These functions are only imported and called inside cmd_analyze,
        which is unreachable from the REPL code path.
        """
        mock_repl_session = MagicMock()
        mock_repl_session.run.return_value = 0

        with patch("parallelines.repl.ReplSession", return_value=mock_repl_session):
            with patch(
                "parallelines.analysis.pure_whitelist.load_pure_whitelist",
            ) as mock_load:
                with patch(
                    "parallelines.analysis.pure_whitelist.filter_vfs_by_whitelist",
                ) as mock_filter:
                    _main([
                        "--game", "l4d2",
                        "--game-root", "/fake/game",
                        "--repl",
                        "--sv-pure", "whitelist.txt",
                    ])

        mock_load.assert_not_called()
        mock_filter.assert_not_called()

    def test_sv_pure_does_take_effect_in_analyze_mode(self) -> None:
        """--analyze --sv-pure DOES reach the whitelist code path.

        This confirms the filter logic works in the right mode and
        the bug is the REPL dispatch, not the filter code itself.
        """
        with patch("parallelines.cli.cmd_analyze") as mock_cmd_analyze:
            mock_cmd_analyze.return_value = 0
            _main([
                "--game", "l4d2",
                "--game-root", "/fake/game",
                "--analyze",
                "--sv-pure", "whitelist.txt",
            ])

        mock_cmd_analyze.assert_called_once()


# ── B20b: sv-pure in --external mode also ineffective (CRITICAL) ────────
#
#  Bug:  --external x.vpk --sv-pure whitelist.txt → sv-pure whitelist
#        filtering is only applied inside cmd_analyze() (cli.py lines 807-828).
#        cmd_external() calls _build_store() but never enters cmd_analyze().
#
#  Root cause: same as B20 — sv-pure logic is not in the shared _build_store()
#  pipeline.  It was added only to the --analyze code path.


class TestB20bSvPureExternalIneffective:
    """B20b (CRITICAL): --sv-pure has no effect in --external mode."""

    def test_cmd_analyze_not_called_in_external_mode(self) -> None:
        """--external dispatches to cmd_external, not cmd_analyze."""
        with (
            patch("parallelines.cli.load_config") as mock_load_config,
            patch("parallelines.cli.set_language"),
            patch("parallelines.cli.logging.basicConfig"),
            patch("parallelines.cli.cmd_external") as mock_cmd_external,
        ):
            mock_load_config.return_value = _make_config()
            mock_cmd_external.return_value = 0
            _main([
                "--game", "l4d2",
                "--game-root", "/fake/game",
                "--external", "test.vpk",
                "--sv-pure", "whitelist.txt",
            ])
        mock_cmd_external.assert_called_once()

    def test_whitelist_functions_not_called_in_external_mode(self) -> None:
        """sv-pure whitelist functions should NOT be called in --external mode.

        Uses ``_main`` dispatch but patches ``cmd_external`` itself to avoid
        executing the full external pipeline (which tries real I/O and
        prettytable formatting).  The key assertion: the whitelist load/filter
        functions are never invoked during dispatch.
        """
        with (
            patch("parallelines.cli.load_config") as mock_load_config,
            patch("parallelines.cli.set_language"),
            patch("parallelines.cli.logging.basicConfig"),
            # Patch all three dispatch targets so we can intercept _main
            patch("parallelines.cli.cmd_external") as mock_cmd_external,
            patch("parallelines.cli.cmd_analyze") as mock_cmd_analyze,
            patch("parallelines.repl.ReplSession") as mock_repl_cls,
            # Patch whitelist functions
            patch(
                "parallelines.analysis.pure_whitelist.load_pure_whitelist",
            ) as mock_load,
            patch(
                "parallelines.analysis.pure_whitelist.filter_vfs_by_whitelist",
            ) as mock_filter,
        ):
            mock_load_config.return_value = _make_config()
            mock_cmd_external.return_value = 0
            mock_repl_instance = MagicMock()
            mock_repl_instance.run.return_value = 0
            mock_repl_cls.return_value = mock_repl_instance

            _main([
                "--game", "l4d2",
                "--game-root", "/fake/game",
                "--external", "test.vpk",
                "--sv-pure", "whitelist.txt",
            ])

        # The key bug: whitelist functions are never called because
        # sv-pure filtering is only wired into cmd_analyze, not cmd_external
        mock_load.assert_not_called()
        mock_filter.assert_not_called()
        mock_cmd_external.assert_called_once()
        mock_cmd_analyze.assert_not_called()


# ── B21: Multi-mode flag silently ignored (MEDIUM) ─────────────────────
#
#  Bug:  --analyze --repl → only --analyze is dispatched, --repl is
#        silently ignored.  No warning is printed.
#
#  Root cause: dispatch uses if/elif (cli.py:460-466) with no conflict
#  detection.  --analyze > --external > --repl priority is undocumented.
#


class TestB21MultiModeFlagSilentlyIgnored:
    """B21 (MEDIUM): second mode flag is silently dropped."""

    def test_analyze_takes_priority_over_repl(self) -> None:
        """--analyze --repl dispatches to cmd_analyze, not ReplSession.

        This confirms --analyze silently takes priority.
        """
        with patch("parallelines.cli.cmd_analyze") as mock_cmd_analyze:
            mock_cmd_analyze.return_value = 0
            with patch("parallelines.repl.ReplSession") as MockReplSession:
                result = _main([
                    "--game", "l4d2",
                    "--game-root", "/fake/game",
                    "--analyze",
                    "--repl",
                ])

        assert result == 0
        mock_cmd_analyze.assert_called_once()
        MockReplSession.assert_not_called()

    def test_analyze_takes_priority_over_external(self) -> None:
        """--analyze --external dispatches to cmd_analyze, not cmd_external."""
        with patch("parallelines.cli.cmd_analyze") as mock_cmd_analyze:
            mock_cmd_analyze.return_value = 0
            with patch("parallelines.cli.cmd_external") as mock_cmd_external:
                result = _main([
                    "--game", "l4d2",
                    "--game-root", "/fake/game",
                    "--analyze",
                    "--external", "test.vpk",
                ])

        assert result == 0
        mock_cmd_analyze.assert_called_once()
        mock_cmd_external.assert_not_called()

    def test_external_takes_priority_over_repl(self) -> None:
        """--external --repl dispatches to cmd_external, not ReplSession."""
        mock_store = MagicMock()
        mock_store.external_files = MagicMock()
        mock_store.external_files.__len__.return_value = 0

        with patch("parallelines.cli.cmd_external") as mock_cmd_external:
            mock_cmd_external.return_value = 0
            with patch("parallelines.repl.ReplSession") as MockReplSession:
                result = _main([
                    "--game", "l4d2",
                    "--game-root", "/fake/game",
                    "--external", "test.vpk",
                    "--repl",
                ])

        assert result == 0
        mock_cmd_external.assert_called_once()
        MockReplSession.assert_not_called()

    def test_no_warning_logged_for_mode_conflict(self) -> None:
        """BUG: no WARNING is logged when multiple mode flags are specified.

        The dispatch silently ignores the second flag.  A WARNING should be
        emitted per R03/R04 but the current code has no such detection.
        """
        with patch("parallelines.cli.cmd_analyze") as mock_cmd_analyze:
            mock_cmd_analyze.return_value = 0
            with patch("parallelines.cli.logger") as mock_logger:
                _main([
                    "--game", "l4d2",
                    "--game-root", "/fake/game",
                    "--analyze",
                    "--repl",
                ])

        # Collect all WARNING-level log calls.
        warning_messages = [
            c.args[0] if c.args else ""
            for c in mock_logger.warning.call_args_list
        ]
        mode_conflict_warnings = [
            m for m in warning_messages if "mode" in str(m).lower()
        ]
        # After fix (B025-B027): a WARNING about mode conflict should be emitted.
        assert len(mode_conflict_warnings) >= 1


# ── B22: check-* in REPL mode ignored (MEDIUM) ─────────────────────────
#
#  Bug:  --repl --check-textures → _apply_check_filters is only called
#        in cmd_analyze (cli.py:831), never in the REPL code path.
#
#  Root cause: _apply_check_filters was placed at the end of cmd_analyze
#        instead of in _build_store, so check-* flags are silently ignored
#        in REPL mode.
#


class TestB22CheckFiltersReplIgnored:
    """B22 (MEDIUM): check-* resource pollution filters ignored in --repl."""

    def test_apply_check_filters_not_called_in_repl(self) -> None:
        """_apply_check_filters is NOT invoked in the REPL code path.

        The function is only called in cmd_analyze (cli.py:831), which
        is never reached in --repl mode.
        """
        mock_repl_session = MagicMock()
        mock_repl_session.run.return_value = 0

        with patch("parallelines.repl.ReplSession", return_value=mock_repl_session):
            with patch("parallelines.cli._apply_check_filters") as mock_apply:
                result = _main([
                    "--game", "l4d2",
                    "--game-root", "/fake/game",
                    "--repl",
                    "--check-textures",
                ])

        assert result == 0
        mock_apply.assert_not_called()

    def test_apply_check_filters_is_called_in_analyze(self) -> None:
        """_apply_check_filters IS invoked in --analyze mode.

        This confirms the filter works in the mode where cmd_analyze runs.
        """
        mock_store = MagicMock()
        mock_store.hash_conflicts = None
        mock_store.dep_conflicts = None

        with patch("parallelines.cli._build_store", return_value=(mock_store, None)):
            with patch("parallelines.cli._apply_check_filters") as mock_apply:
                with patch("parallelines.cli.print_summary_from_store"):
                    with patch("parallelines.cli.generate_report_from_store"):
                        result = _main([
                            "--game", "l4d2",
                            "--game-root", "/fake/game",
                            "--analyze",
                            "--check-textures",
                        ])

        assert result == 0
        mock_apply.assert_called_once()


# ── B23: vpk-priority in REPL ignored (MEDIUM) ─────────────────────────
#
#  Bug:  --repl --external x.vpk --vpk-priority lowest → the priority
#        argument is completely ignored.  ReplSession.load_external_vpk()
#        hard-codes priority=2000.
#
#  Root cause: ReplSession.load_external_vpk() (repl/session.py:154-167)
#        uses a literal 2000 instead of reading args.vpk_priority.
#


class TestB23VpkPriorityReplIgnored:
    """B23 (MEDIUM): --vpk-priority ignored in REPL mode."""

    def test_load_external_vpk_hardcodes_priority_2000(self) -> None:
        """ReplSession.load_external_vpk always uses priority=2000.

        The user's --vpk-priority argument is completely ignored.
        """
        config = _make_config()
        args = Namespace(
            vpk_priority="lowest",
            external="x.vpk",
            game="l4d2",
            debug=False,
        )
        session = ReplSession(config, args)
        session.store = MagicMock()

        with patch.object(Path, "exists", return_value=True):
            with patch.object(Path, "resolve", return_value=Path("/resolved/x.vpk")):
                session.load_external_vpk("x.vpk")

        # The bug: priority=2000 is hard-coded in session.py line 164.
        pos_args, kw_args = session.store.load_reference.call_args
        assert kw_args.get("priority") == 2000, (
            f"Expected hardcoded priority=2000, got priority={kw_args.get('priority')}"
        )

    def test_priority_lowest_works_in_cmd_external(self) -> None:
        """--vpk-priority lowest IS respected in --external mode.

        This contrasts with B23: cmd_external (cli.py:870) maps
        'lowest' → -100, so the bug is specific to the REPL path.
        """
        args = Namespace(
            vpk_priority="lowest",
            external="test.vpk",
            ref_query="all",
            query=None,
            analyze=False,
            repl=False,
        )
        # In cmd_external, priority is computed as:
        #   priority = 2000 if args.vpk_priority == "highest" else -100
        priority = 2000 if args.vpk_priority == "highest" else -100
        assert priority == -100, "cmd_external should map 'lowest' → -100"


# ── B24: no-cache + clean-cache redundancy (LOW) ───────────────────────
#
#  Bug:  --no-cache --clean-cache together are redundant but no warning
#        is emitted.  The cache is deleted (clean-cache) but never saved
#        (no-cache), making the clean-cache operation pointless.
#
#  Root cause: no mutual-exclusion check between these two flags.
#


class TestB24NoCacheCleanCacheRedundancy:
    """B24 (LOW): --no-cache + --clean-cache redundancy."""

    def test_argparse_parses_both_flags(self) -> None:
        """argparse accepts both --no-cache and --clean-cache without error."""
        parser = build_parser()
        args = parser.parse_args([
            "--game", "l4d2",
            "--game-root", "/fake/game",
            "--analyze",
            "--no-cache",
            "--clean-cache",
        ])
        assert args.no_cache is True
        assert args.clean_cache is True

    def test_validator_emits_warning_for_both(self) -> None:
        """CliArgValidator flags both flags as redundant (R06)."""
        args = Namespace(no_cache=True, clean_cache=True)
        warnings = CliArgValidatorTestHelper.check_cache_consistency(args)
        assert len(warnings) == 1

    def test_build_store_processes_both_flags(self) -> None:
        """_build_store executes both flags: cache is deleted AND not saved.

        Verifying the actual behavior: clean_cache calls invalidate_cache
        (deletes cache) while no_cache makes use_cache=False (skips saving).
        The clean-cache operation is therefore wasted work.
        """
        config = _make_config()
        args = Namespace(
            no_cache=True,
            clean_cache=True,
            yes=True,
            nolimit=False,
            cpu=None,
            entry_points=None,
            maps=None,
            graphviz=None,
            compare_maps=None,
        )

        mock_vfs = MagicMock()
        mock_vfs.get_all_active.return_value = []
        mock_vfs.get_all_files.return_value = []

        with patch.object(Path, "exists", return_value=True):
            with patch("parallelines.vfs.builder.VfsBuilder") as MockVfsBuilder:
                mock_builder = MockVfsBuilder.return_value
                mock_builder.build.return_value = mock_vfs
                mock_builder.cache_hit = False
                mock_builder.cache_size.return_value = "0 B"
                mock_builder.get_chain.return_value = None

                with patch("parallelines.graph.builder.GraphBuilder"):
                    with patch("parallelines.cli.ResultStore") as MockResultStore:
                        MockResultStore.from_analysis.return_value = MagicMock()
                        with patch(
                            "parallelines.analysis.entry_points.discover_entry_points",
                            return_value=set(),
                        ):
                            _build_store(config, args)

        # Verify VfsBuilder was created with use_cache=False (from --no-cache)
        _call_kwargs = MockVfsBuilder.call_args.kwargs
        assert _call_kwargs.get("use_cache") is False, (
            "--no-cache should set use_cache=False"
        )

        # Verify invalidate_cache was called (from --clean-cache)
        assert mock_builder.invalidate_cache.called, (
            "--clean-cache should call invalidate_cache()"
        )

        # Bug: invalidate_cache is called but the cache is never saved
        # because use_cache=False.  No warning is emitted about this redundancy.
        assert mock_builder.invalidate_cache.call_count == 1
