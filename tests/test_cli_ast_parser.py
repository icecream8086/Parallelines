"""Tests for parallelines.cli — section 1 of cli-ast-rules.md: all 35 parameters.

Verifies every CLI parameter is correctly registered in build_parser()
with the right type, default, and constraints.  Also covers basic
parse_args round-trips and edge cases (invalid choices, required
params, short forms, nargs semantics).

References:

    devdocs/cli-ast-rules.md  §1  (parameter universe table)
    src/parallelines/cli.py        build_parser() implementation
"""

from __future__ import annotations

import io
import sys
import unittest
from argparse import Namespace

from parallelines.cli import build_parser


# ── helpers ──────────────────────────────────────────────────────────


def _parse(argv: list[str]) -> Namespace:
    """Return the parsed namespace for *argv* (assumes --game is given)."""
    return build_parser().parse_args(argv)


# ======================================================================
# §1.1 — Mode selection  (P1 – P3)
# ======================================================================


class TestModeParameters(unittest.TestCase):
    """P1 --analyze, P2 --external, P3 --repl."""

    def setUp(self) -> None:
        self.parser = build_parser()

    # -- P1: --analyze -------------------------------------------------

    def test_p1_analyze_default_false(self) -> None:
        """--analyze defaults to False."""
        args = self.parser.parse_args(["--game", "l4d2"])
        self.assertFalse(args.analyze)

    def test_p1_analyze_flag_sets_true(self) -> None:
        """--analyze is a bool flag (store_true)."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertTrue(args.analyze)

    # -- P2: --external ------------------------------------------------

    def test_p2_external_default_none(self) -> None:
        """--external defaults to None."""
        args = self.parser.parse_args(["--game", "l4d2"])
        self.assertIsNone(args.external)

    def test_p2_external_accepts_path(self) -> None:
        """--external accepts a VPK path string."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--external", "/path/to/addon.vpk"]
        )
        self.assertEqual(args.external, "/path/to/addon.vpk")

    def test_p2_external_requires_value(self) -> None:
        """--external requires a value (next token)."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["--game", "l4d2", "--external"])

    # -- P3: --repl ----------------------------------------------------

    def test_p3_repl_default_false(self) -> None:
        """--repl defaults to False."""
        args = self.parser.parse_args(["--game", "l4d2"])
        self.assertFalse(args.repl)

    def test_p3_repl_flag_sets_true(self) -> None:
        """--repl is a bool flag (store_true)."""
        args = self.parser.parse_args(["--game", "l4d2", "--repl"])
        self.assertTrue(args.repl)


# ======================================================================
# §1.2 — Game environment  (P4 – P6)
# ======================================================================


class TestGameEnvironmentParameters(unittest.TestCase):
    """P4 --game (required), P5 --game-root, P6 --config."""

    def setUp(self) -> None:
        self.parser = build_parser()

    # -- P4: --game ----------------------------------------------------

    def test_p4_game_required(self) -> None:
        """--game is required; calling parser without it raises SystemExit."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["--analyze"])

    def test_p4_game_accepts_valid_id(self) -> None:
        """--game accepts a valid game ID (e.g. l4d2)."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertEqual(args.game, "l4d2")

    def test_p4_game_rejects_invalid_id(self) -> None:
        """--game rejects an unsupported game ID."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["--game", "invalid_game", "--analyze"])

    def test_p4_game_choices_are_sorted(self) -> None:
        """The choices list should be sorted (argparse displays sorted in help)."""
        action = [a for a in self.parser._actions if a.dest == "game"][0]
        self.assertEqual(action.choices, sorted(action.choices))

    # -- P5: --game-root -----------------------------------------------

    def test_p5_game_root_default_empty(self) -> None:
        """--game-root defaults to empty string."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertEqual(args.game_root, "")

    def test_p5_game_root_accepts_path(self) -> None:
        """--game-root accepts a directory path string."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--game-root", "C:/games/l4d2/left4dead2", "--analyze"]
        )
        self.assertEqual(args.game_root, "C:/games/l4d2/left4dead2")

    # -- P6: --config --------------------------------------------------

    def test_p6_config_default_empty(self) -> None:
        """--config defaults to empty string."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertEqual(args.config, "")

    def test_p6_config_accepts_path(self) -> None:
        """--config accepts a TOML file path string."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--config", "/cfg/parallelines.toml", "--analyze"]
        )
        self.assertEqual(args.config, "/cfg/parallelines.toml")


# ======================================================================
# §1.3 — Cache control  (P7 – P9)
# ======================================================================


class TestCacheParameters(unittest.TestCase):
    """P7 --no-cache, P8 --clean-cache, P9 --yes / -y."""

    def setUp(self) -> None:
        self.parser = build_parser()

    # -- P7: --no-cache ------------------------------------------------

    def test_p7_no_cache_default_false(self) -> None:
        """--no-cache defaults to False."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertFalse(args.no_cache)

    def test_p7_no_cache_flag_sets_true(self) -> None:
        """--no-cache is a bool flag (store_true)."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--no-cache"]
        )
        self.assertTrue(args.no_cache)

    # -- P8: --clean-cache ---------------------------------------------

    def test_p8_clean_cache_default_false(self) -> None:
        """--clean-cache defaults to False."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertFalse(args.clean_cache)

    def test_p8_clean_cache_flag_sets_true(self) -> None:
        """--clean-cache is a bool flag (store_true)."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--clean-cache"]
        )
        self.assertTrue(args.clean_cache)

    # -- P9: --yes / -y ------------------------------------------------

    def test_p9_yes_default_false(self) -> None:
        """--yes defaults to False."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertFalse(args.yes)

    def test_p9_yes_long_form(self) -> None:
        """--yes (long form) sets True."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--yes"]
        )
        self.assertTrue(args.yes)

    def test_p9_yes_short_form_y(self) -> None:
        """-y (short form) sets True."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze", "-y"])
        self.assertTrue(args.yes)


# ======================================================================
# §1.4 — Resource limits  (P10 – P12)
# ======================================================================


class TestResourceLimitParameters(unittest.TestCase):
    """P10 --cpu, P11 --memory, P12 --nolimit."""

    def setUp(self) -> None:
        self.parser = build_parser()

    # -- P10: --cpu ----------------------------------------------------

    def test_p10_cpu_default_none(self) -> None:
        """--cpu defaults to None."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertIsNone(args.cpu)

    def test_p10_cpu_accepts_positive_int(self) -> None:
        """--cpu accepts a positive integer."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--cpu", "4"]
        )
        self.assertEqual(args.cpu, 4)

    def test_p10_cpu_accepts_zero(self) -> None:
        """--cpu accepts 0 (auto)."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--cpu", "0"]
        )
        self.assertEqual(args.cpu, 0)

    def test_p10_cpu_rejects_non_int(self) -> None:
        """--cpu rejects a non-integer value."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["--game", "l4d2", "--analyze", "--cpu", "auto"])

    # NOTE: argparse type=int accepts negative integers.  Validation
    # of cpu >= 0 is done in application code (cli.py:_main), not
    # at the parser level, so there is no parser-level rejection test
    # for negative values.

    # -- P11: --memory -------------------------------------------------

    def test_p11_memory_default_none(self) -> None:
        """--memory defaults to None."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertIsNone(args.memory)

    def test_p11_memory_accepts_string(self) -> None:
        """--memory accepts a string value like '4GB'."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--memory", "4GB"]
        )
        self.assertEqual(args.memory, "4GB")

    def test_p11_memory_accepts_zero(self) -> None:
        """--memory accepts '0' (no limit)."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--memory", "0"]
        )
        self.assertEqual(args.memory, "0")

    # -- P12: --nolimit ------------------------------------------------

    def test_p12_nolimit_default_none(self) -> None:
        """--nolimit defaults to None (not False)."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertIsNone(args.nolimit)

    def test_p12_nolimit_flag_sets_true(self) -> None:
        """--nolimit is a bool flag that sets True when given."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--nolimit"]
        )
        self.assertTrue(args.nolimit)


# ======================================================================
# §1.5 — Output control  (P13 – P15)
# ======================================================================


class TestOutputControlParameters(unittest.TestCase):
    """P13 --format, P14 --output-dir, P15 --graphviz."""

    def setUp(self) -> None:
        self.parser = build_parser()

    # -- P13: --format -------------------------------------------------

    def test_p13_format_default_none(self) -> None:
        """--format defaults to None."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertIsNone(args.format)

    def test_p13_format_accepts_json(self) -> None:
        """--format accepts 'json'."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--format", "json"]
        )
        self.assertEqual(args.format, "json")

    def test_p13_format_accepts_csv(self) -> None:
        """--format accepts 'csv'."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--format", "csv"]
        )
        self.assertEqual(args.format, "csv")

    def test_p13_format_accepts_text(self) -> None:
        """--format accepts 'text'."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--format", "text"]
        )
        self.assertEqual(args.format, "text")

    def test_p13_format_accepts_html(self) -> None:
        """--format accepts 'html'."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--format", "html"]
        )
        self.assertEqual(args.format, "html")

    def test_p13_format_rejects_invalid(self) -> None:
        """--format rejects a value not in [json, csv, text, html]."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(
                ["--game", "l4d2", "--analyze", "--format", "xml"]
            )

    # -- P14: --output-dir ---------------------------------------------

    def test_p14_output_dir_default_none(self) -> None:
        """--output-dir defaults to None."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertIsNone(args.output_dir)

    def test_p14_output_dir_accepts_path(self) -> None:
        """--output-dir accepts a directory path string."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--output-dir", "./reports"]
        )
        self.assertEqual(args.output_dir, "./reports")

    # -- P15: --graphviz -----------------------------------------------

    def test_p15_graphviz_default_none(self) -> None:
        """--graphviz defaults to None."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertIsNone(args.graphviz)

    def test_p15_graphviz_accepts_path(self) -> None:
        """--graphviz accepts a .dot output path string."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--graphviz", "/tmp/graph.dot"]
        )
        self.assertEqual(args.graphviz, "/tmp/graph.dot")


# ======================================================================
# §1.6 — Resource pollution check filters  (P16 – P23)
# ======================================================================


class TestCheckFilterParameters(unittest.TestCase):
    """P16 --check-textures … P23 --check-all."""

    def setUp(self) -> None:
        self.parser = build_parser()

    CHECK_FLAGS = [
        ("check_textures", "--check-textures"),
        ("check_models", "--check-models"),
        ("check_sounds", "--check-sounds"),
        ("check_scripts", "--check-scripts"),
        ("check_configs", "--check-configs"),
        ("check_maps", "--check-maps"),
        ("check_manifests", "--check-manifests"),
        ("check_all", "--check-all"),
    ]

    def test_p16_to_p23_defaults_false(self) -> None:
        """All --check-* flags default to False."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        for attr, _flag in self.CHECK_FLAGS:
            with self.subTest(attr=attr):
                self.assertFalse(getattr(args, attr))

    def test_p16_to_p23_flags_set_true(self) -> None:
        """Each --check-* flag sets its attribute to True."""
        for attr, flag in self.CHECK_FLAGS:
            with self.subTest(flag=flag):
                args = self.parser.parse_args(
                    ["--game", "l4d2", "--analyze", flag]
                )
                self.assertTrue(getattr(args, attr))

    def test_p16_to_p23_are_independent(self) -> None:
        """Individual --check-* flags do not affect each other."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--check-textures", "--check-models"]
        )
        self.assertTrue(args.check_textures)
        self.assertTrue(args.check_models)
        self.assertFalse(args.check_sounds)
        self.assertFalse(args.check_scripts)
        self.assertFalse(args.check_configs)
        self.assertFalse(args.check_maps)
        self.assertFalse(args.check_manifests)
        self.assertFalse(args.check_all)


# ======================================================================
# §1.7 — Analysis configuration  (P24 – P30)
# ======================================================================


class TestAnalysisConfigParameters(unittest.TestCase):
    """P24 --entry-points … P30 --ref-query."""

    def setUp(self) -> None:
        self.parser = build_parser()

    # -- P24: --entry-points (nargs="*") --------------------------------

    def test_p24_entry_points_default_none(self) -> None:
        """--entry-points defaults to None when not provided."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertIsNone(args.entry_points)

    def test_p24_entry_points_accepts_zero_values(self) -> None:
        """--entry-points with no following tokens yields empty list."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--entry-points"]
        )
        self.assertEqual(args.entry_points, [])

    def test_p24_entry_points_accepts_multiple_values(self) -> None:
        """--entry-points accepts multiple space-separated virtual paths."""
        args = self.parser.parse_args(
            [
                "--game", "l4d2", "--analyze",
                "--entry-points", "maps/c1m1_hotel.bsp", "maps/c2m1_highway.bsp",
            ]
        )
        self.assertEqual(
            args.entry_points,
            ["maps/c1m1_hotel.bsp", "maps/c2m1_highway.bsp"],
        )

    # -- P25: --maps (nargs="*") ---------------------------------------

    def test_p25_maps_default_none(self) -> None:
        """--maps defaults to None when not provided."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertIsNone(args.maps)

    def test_p25_maps_accepts_zero_values(self) -> None:
        """--maps with no following tokens yields empty list."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--maps"]
        )
        self.assertEqual(args.maps, [])

    def test_p25_maps_accepts_multiple_values(self) -> None:
        """--maps accepts multiple space-separated map names."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--maps", "c1m1_hotel", "c2m1_highway"]
        )
        self.assertEqual(args.maps, ["c1m1_hotel", "c2m1_highway"])

    # -- P26: --compare-maps (nargs="+") -------------------------------

    def test_p26_compare_maps_default_none(self) -> None:
        """--compare-maps defaults to None when not provided."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertIsNone(args.compare_maps)

    def test_p26_compare_maps_requires_at_least_one(self) -> None:
        """--compare-maps (nargs='+') rejects zero following tokens."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(
                ["--game", "l4d2", "--analyze", "--compare-maps"]
            )

    def test_p26_compare_maps_accepts_multiple(self) -> None:
        """--compare-maps accepts one or more VPK file paths."""
        args = self.parser.parse_args(
            [
                "--game", "l4d2", "--analyze",
                "--compare-maps", "addon1.vpk", "addon2.vpk",
            ]
        )
        self.assertEqual(args.compare_maps, ["addon1.vpk", "addon2.vpk"])

    def test_p26_compare_maps_accepts_single(self) -> None:
        """--compare-maps accepts exactly one VPK path."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--compare-maps", "addon.vpk"]
        )
        self.assertEqual(args.compare_maps, ["addon.vpk"])

    # -- P27: --sv-pure ------------------------------------------------

    def test_p27_sv_pure_default_none(self) -> None:
        """--sv-pure defaults to None."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertIsNone(args.sv_pure)

    def test_p27_sv_pure_accepts_path(self) -> None:
        """--sv-pure accepts a whitelist file path string."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--sv-pure", "/cfg/whitelist.txt"]
        )
        self.assertEqual(args.sv_pure, "/cfg/whitelist.txt")

    # -- P28: --query --------------------------------------------------

    def test_p28_query_default_none(self) -> None:
        """--query defaults to None."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertIsNone(args.query)

    def test_p28_query_accepts_preset_name(self) -> None:
        """--query accepts a preset name string."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--query", "dead_files"]
        )
        self.assertEqual(args.query, "dead_files")

    def test_p28_query_accepts_inline_json(self) -> None:
        """--query accepts an inline JSON DSL string."""
        args = self.parser.parse_args(
            [
                "--game", "l4d2", "--analyze",
                "--query", '{"_comment": "inline query"}',
            ]
        )
        self.assertEqual(args.query, '{"_comment": "inline query"}')

    # -- P29: --vpk-priority -------------------------------------------

    def test_p29_vpk_priority_default_highest(self) -> None:
        """--vpk-priority defaults to 'highest'."""
        args = self.parser.parse_args(["--game", "l4d2", "--external", "test.vpk"])
        self.assertEqual(args.vpk_priority, "highest")

    def test_p29_vpk_priority_accepts_highest(self) -> None:
        """--vpk-priority accepts 'highest'."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--external", "test.vpk", "--vpk-priority", "highest"]
        )
        self.assertEqual(args.vpk_priority, "highest")

    def test_p29_vpk_priority_accepts_lowest(self) -> None:
        """--vpk-priority accepts 'lowest'."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--external", "test.vpk", "--vpk-priority", "lowest"]
        )
        self.assertEqual(args.vpk_priority, "lowest")

    def test_p29_vpk_priority_rejects_invalid(self) -> None:
        """--vpk-priority rejects values not in [highest, lowest]."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(
                ["--game", "l4d2", "--external", "test.vpk", "--vpk-priority", "medium"]
            )

    # -- P30: --ref-query ----------------------------------------------

    def test_p30_ref_query_default_all(self) -> None:
        """--ref-query defaults to 'all'."""
        args = self.parser.parse_args(["--game", "l4d2", "--external", "test.vpk"])
        self.assertEqual(args.ref_query, "all")

    def test_p30_ref_query_accepts_all(self) -> None:
        """--ref-query accepts 'all'."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--external", "test.vpk", "--ref-query", "all"]
        )
        self.assertEqual(args.ref_query, "all")

    def test_p30_ref_query_accepts_overrides(self) -> None:
        """--ref-query accepts 'overrides'."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--external", "test.vpk", "--ref-query", "overrides"]
        )
        self.assertEqual(args.ref_query, "overrides")

    def test_p30_ref_query_accepts_overridden(self) -> None:
        """--ref-query accepts 'overridden'."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--external", "test.vpk", "--ref-query", "overridden"]
        )
        self.assertEqual(args.ref_query, "overridden")

    def test_p30_ref_query_accepts_new_files(self) -> None:
        """--ref-query accepts 'new_files'."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--external", "test.vpk", "--ref-query", "new_files"]
        )
        self.assertEqual(args.ref_query, "new_files")

    def test_p30_ref_query_rejects_invalid(self) -> None:
        """--ref-query rejects values not in [all, overrides, overridden, new_files]."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(
                ["--game", "l4d2", "--external", "test.vpk", "--ref-query", "invalid"]
            )


# ======================================================================
# §1.8 — Other  (P31 – P35)
# ======================================================================


class TestOtherParameters(unittest.TestCase):
    """P31 --debug, P32 --log-level, P33 --lang, P34 --list-presets,
    P35 --version."""

    def setUp(self) -> None:
        self.parser = build_parser()

    # -- P31: --debug --------------------------------------------------

    def test_p31_debug_default_false(self) -> None:
        """--debug defaults to False."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertFalse(args.debug)

    def test_p31_debug_flag_sets_true(self) -> None:
        """--debug is a bool flag (store_true)."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--debug"]
        )
        self.assertTrue(args.debug)

    # -- P32: --log-level ----------------------------------------------

    def test_p32_log_level_default_none(self) -> None:
        """--log-level defaults to None."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertIsNone(args.log_level)

    def test_p32_log_level_accepts_debug(self) -> None:
        """--log-level accepts 'DEBUG'."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--log-level", "DEBUG"]
        )
        self.assertEqual(args.log_level, "DEBUG")

    def test_p32_log_level_accepts_info(self) -> None:
        """--log-level accepts 'INFO'."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--log-level", "INFO"]
        )
        self.assertEqual(args.log_level, "INFO")

    def test_p32_log_level_accepts_warning(self) -> None:
        """--log-level accepts 'WARNING'."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--log-level", "WARNING"]
        )
        self.assertEqual(args.log_level, "WARNING")

    def test_p32_log_level_accepts_error(self) -> None:
        """--log-level accepts 'ERROR'."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--log-level", "ERROR"]
        )
        self.assertEqual(args.log_level, "ERROR")

    def test_p32_log_level_rejects_invalid(self) -> None:
        """--log-level rejects values not in [DEBUG, INFO, WARNING, ERROR]."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(
                ["--game", "l4d2", "--analyze", "--log-level", "TRACE"]
            )

    def test_p32_log_level_rejects_lowercase(self) -> None:
        """--log-level is case-sensitive and rejects 'debug'."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(
                ["--game", "l4d2", "--analyze", "--log-level", "debug"]
            )

    # -- P33: --lang ---------------------------------------------------

    def test_p33_lang_default_none(self) -> None:
        """--lang defaults to None."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertIsNone(args.lang)

    def test_p33_lang_accepts_zh(self) -> None:
        """--lang accepts 'zh'."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--lang", "zh"]
        )
        self.assertEqual(args.lang, "zh")

    def test_p33_lang_accepts_en(self) -> None:
        """--lang accepts 'en'."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--lang", "en"]
        )
        self.assertEqual(args.lang, "en")

    def test_p33_lang_rejects_invalid(self) -> None:
        """--lang rejects values not in [zh, en]."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(
                ["--game", "l4d2", "--analyze", "--lang", "fr"]
            )

    # -- P34: --list-presets -------------------------------------------

    def test_p34_list_presets_default_false(self) -> None:
        """--list-presets defaults to False."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertFalse(args.list_presets)

    def test_p34_list_presets_flag_sets_true(self) -> None:
        """--list-presets is a bool flag (store_true)."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--list-presets"]
        )
        self.assertTrue(args.list_presets)

    # -- P35: --version (action="version") -----------------------------

    def test_p35_version_exits_zero(self) -> None:
        """--version exits with code 0 and prints version string."""
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            with self.assertRaises(SystemExit) as cm:
                self.parser.parse_args(["--version"])
            self.assertEqual(cm.exception.code, 0)
        finally:
            sys.stdout = old_stdout
        output = captured.getvalue()
        self.assertIn("parallelines", output)

    def test_p35_version_does_not_require_game(self) -> None:
        """--version works without --game (no required-param conflict)."""
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            with self.assertRaises(SystemExit) as cm:
                self.parser.parse_args(["--version"])
            self.assertEqual(cm.exception.code, 0)
        finally:
            sys.stdout = old_stdout


# ======================================================================
# §1 cross-cutting — Combined parameter interaction smoke tests
# ======================================================================


class TestParameterCombinations(unittest.TestCase):
    """Smoke tests verifying that parameters from different sections
    can be combined without argparse errors."""

    def setUp(self) -> None:
        self.parser = build_parser()

    def test_analyze_with_all_check_flags(self) -> None:
        """All --check-* flags can be combined with --analyze."""
        args = self.parser.parse_args(
            [
                "--game", "l4d2", "--analyze",
                "--check-textures", "--check-models", "--check-sounds",
                "--check-scripts", "--check-configs", "--check-maps",
                "--check-manifests",
            ]
        )
        self.assertTrue(args.analyze)
        self.assertTrue(args.check_textures)
        self.assertTrue(args.check_manifests)

    def test_analyze_with_cache_and_output(self) -> None:
        """Cache + output params combine cleanly with --analyze."""
        args = self.parser.parse_args(
            [
                "--game", "l4d2", "--analyze",
                "--no-cache", "--clean-cache",
                "--format", "json", "--output-dir", "./out",
                "--graphviz", "graph.dot",
            ]
        )
        self.assertTrue(args.no_cache)
        self.assertTrue(args.clean_cache)
        self.assertEqual(args.format, "json")
        self.assertEqual(args.output_dir, "./out")
        self.assertEqual(args.graphviz, "graph.dot")

    def test_external_with_full_config(self) -> None:
        """--external with --vpk-priority, --ref-query, and resource flags."""
        args = self.parser.parse_args(
            [
                "--game", "l4d2",
                "--external", "addon.vpk",
                "--vpk-priority", "lowest",
                "--ref-query", "overrides",
                "--cpu", "2",
                "--memory", "2GB",
            ]
        )
        self.assertEqual(args.external, "addon.vpk")
        self.assertEqual(args.vpk_priority, "lowest")
        self.assertEqual(args.ref_query, "overrides")
        self.assertEqual(args.cpu, 2)
        self.assertEqual(args.memory, "2GB")

    def test_repl_with_debug_and_lang(self) -> None:
        """--repl combines with --debug, --lang, --log-level."""
        args = self.parser.parse_args(
            [
                "--game", "l4d2", "--repl",
                "--debug", "--lang", "zh",
                "--log-level", "WARNING",
            ]
        )
        self.assertTrue(args.repl)
        self.assertTrue(args.debug)
        self.assertEqual(args.lang, "zh")
        self.assertEqual(args.log_level, "WARNING")

    def test_entry_points_and_maps_combine(self) -> None:
        """--entry-points and --maps can be specified together."""
        args = self.parser.parse_args(
            [
                "--game", "l4d2", "--analyze",
                "--entry-points", "maps/c1m1_hotel.bsp",
                "--maps", "c2m1_highway",
            ]
        )
        self.assertEqual(args.entry_points, ["maps/c1m1_hotel.bsp"])
        self.assertEqual(args.maps, ["c2m1_highway"])

    def test_nolimit_with_cpu_and_memory(self) -> None:
        """--nolimit can coexist with --cpu and --memory (nolimit wins in logic)."""
        args = self.parser.parse_args(
            [
                "--game", "l4d2", "--analyze",
                "--nolimit", "--cpu", "8", "--memory", "16GB",
            ]
        )
        self.assertTrue(args.nolimit)
        self.assertEqual(args.cpu, 8)
        self.assertEqual(args.memory, "16GB")

    def test_yes_short_form_with_no_cache(self) -> None:
        """-y (short form) with --no-cache: no argparse error."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--no-cache", "-y"]
        )
        self.assertTrue(args.no_cache)
        self.assertTrue(args.yes)


# ======================================================================
# §1x — Edge cases & argparse internals
# ======================================================================


class TestEdgeCases(unittest.TestCase):
    """Edge cases for argparse registration correctness."""

    def setUp(self) -> None:
        self.parser = build_parser()

    def test_invalid_choice_vpk_priority(self) -> None:
        """--vpk-priority rejects 'medium' (not in [highest, lowest])."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(
                ["--game", "l4d2", "--external", "t.vpk", "--vpk-priority", "medium"]
            )

    def test_invalid_choice_ref_query(self) -> None:
        """--ref-query rejects 'none' (not in valid choices)."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(
                ["--game", "l4d2", "--external", "t.vpk", "--ref-query", "none"]
            )

    def test_invalid_choice_format(self) -> None:
        """--format rejects 'pdf' (not in valid choices)."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(
                ["--game", "l4d2", "--analyze", "--format", "pdf"]
            )

    def test_invalid_choice_log_level(self) -> None:
        """--log-level rejects 'FATAL' (not in valid choices)."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(
                ["--game", "l4d2", "--analyze", "--log-level", "FATAL"]
            )

    def test_invalid_choice_lang(self) -> None:
        """--lang rejects 'ja' (not in [zh, en])."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(
                ["--game", "l4d2", "--analyze", "--lang", "ja"]
            )

    def test_unknown_flag_raises_error(self) -> None:
        """An unrecognised flag raises SystemExit."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(
                ["--game", "l4d2", "--analyze", "--nonexistent-flag"]
            )

    def test_required_game_missing_with_analyze(self) -> None:
        """--analyze without --game raises SystemExit."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["--analyze"])

    def test_required_game_missing_with_external(self) -> None:
        """--external without --game raises SystemExit."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["--external", "test.vpk"])

    def test_required_game_missing_with_repl(self) -> None:
        """--repl without --game raises SystemExit."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["--repl"])

    def test_unknown_argument_before_game(self) -> None:
        """Unknown argument before --game is still caught."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["--bogus", "--game", "l4d2"])

    def test_no_args_prints_help_and_exits(self) -> None:
        """No arguments at all triggers help (argparse error due to --game)."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args([])

    def test_external_with_no_value_after_flag(self) -> None:
        """--external as the last token with no value raises SystemExit."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["--game", "l4d2", "--external"])

    def test_entry_points_empty_string_is_kept(self) -> None:
        """--entry-points with an empty string arg yields ['']."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--entry-points", ""]
        )
        self.assertEqual(args.entry_points, [""])


# ======================================================================
# §1z — Verify all 35 parameter destinations exist on the namespace
# ======================================================================


class TestAll35ParametersRegistered(unittest.TestCase):
    """Exhaustive check that every attribute from the 35-parameter table
    exists on the parsed namespace and has the expected type/default."""

    def setUp(self) -> None:
        self.parser = build_parser()

    def test_all_35_attributes_exist(self) -> None:
        """Every parameter from the AST table is present on the namespace."""
        args = self.parser.parse_args(["--game", "l4d2"])

        # §1.1 — Mode selection (P1-P3)
        self.assertTrue(hasattr(args, "analyze"))
        self.assertTrue(hasattr(args, "external"))
        self.assertTrue(hasattr(args, "repl"))

        # §1.2 — Game environment (P4-P6)
        self.assertTrue(hasattr(args, "game"))
        self.assertTrue(hasattr(args, "game_root"))
        self.assertTrue(hasattr(args, "config"))

        # §1.3 — Cache control (P7-P9)
        self.assertTrue(hasattr(args, "no_cache"))
        self.assertTrue(hasattr(args, "clean_cache"))
        self.assertTrue(hasattr(args, "yes"))

        # §1.4 — Resource limits (P10-P12)
        self.assertTrue(hasattr(args, "cpu"))
        self.assertTrue(hasattr(args, "memory"))
        self.assertTrue(hasattr(args, "nolimit"))

        # §1.5 — Output control (P13-P15)
        self.assertTrue(hasattr(args, "format"))
        self.assertTrue(hasattr(args, "output_dir"))
        self.assertTrue(hasattr(args, "graphviz"))

        # §1.6 — Resource pollution check filters (P16-P23)
        self.assertTrue(hasattr(args, "check_textures"))
        self.assertTrue(hasattr(args, "check_models"))
        self.assertTrue(hasattr(args, "check_sounds"))
        self.assertTrue(hasattr(args, "check_scripts"))
        self.assertTrue(hasattr(args, "check_configs"))
        self.assertTrue(hasattr(args, "check_maps"))
        self.assertTrue(hasattr(args, "check_manifests"))
        self.assertTrue(hasattr(args, "check_all"))

        # §1.7 — Analysis configuration (P24-P30)
        self.assertTrue(hasattr(args, "entry_points"))
        self.assertTrue(hasattr(args, "maps"))
        self.assertTrue(hasattr(args, "compare_maps"))
        self.assertTrue(hasattr(args, "sv_pure"))
        self.assertTrue(hasattr(args, "query"))
        self.assertTrue(hasattr(args, "vpk_priority"))
        self.assertTrue(hasattr(args, "ref_query"))

        # §1.8 — Other (P31-P35)
        self.assertTrue(hasattr(args, "debug"))
        self.assertTrue(hasattr(args, "log_level"))
        self.assertTrue(hasattr(args, "lang"))
        self.assertTrue(hasattr(args, "list_presets"))
        # P35 --version is an action, not stored on namespace

    def test_default_values_match_spec(self) -> None:
        """All default values match the cli-ast-rules.md table exactly."""
        args = self.parser.parse_args(["--game", "l4d2"])

        # bool flags defaulting to False
        self.assertIs(args.analyze, False)
        self.assertIs(args.repl, False)
        self.assertIs(args.no_cache, False)
        self.assertIs(args.clean_cache, False)
        self.assertIs(args.yes, False)
        self.assertIs(args.check_textures, False)
        self.assertIs(args.check_models, False)
        self.assertIs(args.check_sounds, False)
        self.assertIs(args.check_scripts, False)
        self.assertIs(args.check_configs, False)
        self.assertIs(args.check_maps, False)
        self.assertIs(args.check_manifests, False)
        self.assertIs(args.check_all, False)
        self.assertIs(args.debug, False)
        self.assertIs(args.list_presets, False)

        # str params defaulting to "" (empty string)
        self.assertEqual(args.game_root, "")
        self.assertEqual(args.config, "")

        # str params defaulting to None
        self.assertIsNone(args.external)
        self.assertIsNone(args.format)
        self.assertIsNone(args.output_dir)
        self.assertIsNone(args.graphviz)
        self.assertIsNone(args.sv_pure)
        self.assertIsNone(args.query)
        self.assertIsNone(args.log_level)
        self.assertIsNone(args.lang)

        # int param defaulting to None
        self.assertIsNone(args.cpu)

        # str param defaulting to None (stored as str type)
        self.assertIsNone(args.memory)

        # store_true with explicit default=None
        self.assertIsNone(args.nolimit)

        # nargs="*" / nargs="+" defaulting to None
        self.assertIsNone(args.entry_points)
        self.assertIsNone(args.maps)
        self.assertIsNone(args.compare_maps)

        # str params with non-None defaults
        self.assertEqual(args.vpk_priority, "highest")
        self.assertEqual(args.ref_query, "all")

        # --game was provided, so it has a value
        self.assertEqual(args.game, "l4d2")

    def test_check_filters_section_count(self) -> None:
        """There are exactly 8 --check-* parameters (P16-P23)."""
        check_dests = [
            "check_textures", "check_models", "check_sounds",
            "check_scripts", "check_configs", "check_maps",
            "check_manifests", "check_all",
        ]
        args = self.parser.parse_args(["--game", "l4d2"])
        for dest in check_dests:
            self.assertTrue(
                hasattr(args, dest),
                f"Missing check parameter: {dest}",
            )

    def test_choice_parameters_have_correct_choices(self) -> None:
        """Choice-restricted parameters have the correct choice sets."""
        # Inspect argparse actions directly
        actions = {a.dest: a for a in self.parser._actions}

        self.assertEqual(
            sorted(actions["format"].choices),
            ["csv", "html", "json", "text"],
        )
        self.assertEqual(
            sorted(actions["log_level"].choices),
            ["DEBUG", "ERROR", "INFO", "WARNING"],
        )
        self.assertEqual(
            sorted(actions["lang"].choices),
            ["en", "zh"],
        )
        self.assertEqual(
            sorted(actions["vpk_priority"].choices),
            ["highest", "lowest"],
        )
        self.assertEqual(
            sorted(actions["ref_query"].choices),
            ["all", "new_files", "overridden", "overrides"],
        )
        # --game choices come from sorted(SUPPORTED_GAMES.keys())
        self.assertIn("l4d2", actions["game"].choices)


if __name__ == "__main__":
    unittest.main()
