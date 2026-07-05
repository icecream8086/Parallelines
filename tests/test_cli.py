"""Tests for parallelines.cli — argument parsing."""

from __future__ import annotations

import unittest
from io import StringIO

from parallelines.cli import build_parser


class TestCLI(unittest.TestCase):
    """Verify CLI argument parser configuration."""

    def setUp(self) -> None:
        self.parser = build_parser()

    def test_parser_game_required(self) -> None:
        """--game flag should be required."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args([])

    def test_parser_game_root_default(self) -> None:
        """--game-root should default to empty string."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertEqual(args.game_root, "")

    def test_parser_game_root_provided(self) -> None:
        """--game-root should accept a path value."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--game-root", "/games/l4d2", "--analyze"]
        )
        self.assertEqual(args.game_root, "/games/l4d2")

    def test_subcommand_analyze(self) -> None:
        """--analyze flag should be registered and accessible."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertTrue(args.analyze)

    def test_subcommand_external(self) -> None:
        """--external flag should be registered and accessible."""
        args = self.parser.parse_args(["--game", "l4d2", "--external", "test.vpk"])
        self.assertEqual(args.external, "test.vpk")

    def test_analyze_format_option(self) -> None:
        """--analyze flag should have --format option."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--format", "csv"]
        )
        self.assertEqual(args.format, "csv")

    def test_analyze_format_default(self) -> None:
        """--analyze flag --format should default to None."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertIsNone(args.format)

    def test_external_vpk_required(self) -> None:
        """--external flag should require a VPK argument."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["--game", "l4d2", "--external"])

    def test_external_vpk_provided(self) -> None:
        """--external flag should accept a VPK path."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--external", "/path/to/file.vpk"]
        )
        self.assertEqual(args.external, "/path/to/file.vpk")

    def test_external_priority_default(self) -> None:
        """--external --vpk-priority should default to 'highest'."""
        args = self.parser.parse_args(["--game", "l4d2", "--external", "test.vpk"])
        self.assertEqual(args.vpk_priority, "highest")

    def test_external_priority_options(self) -> None:
        """--external --vpk-priority should accept 'highest' or 'lowest'."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--external", "test.vpk", "--vpk-priority", "lowest"]
        )
        self.assertEqual(args.vpk_priority, "lowest")

    def test_analyze_output_dir(self) -> None:
        """--analyze flag should have --output-dir option."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--output-dir", "/tmp/reports"]
        )
        self.assertEqual(args.output_dir, "/tmp/reports")

    def test_analyze_no_cache(self) -> None:
        """--analyze flag should have --no-cache flag."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze"])
        self.assertFalse(args.no_cache)

        args = self.parser.parse_args(["--game", "l4d2", "--analyze", "--no-cache"])
        self.assertTrue(args.no_cache)

    def test_analyze_clean_cache(self) -> None:
        """--analyze flag should have --clean-cache flag."""
        args = self.parser.parse_args(["--game", "l4d2", "--analyze", "--clean-cache"])
        self.assertTrue(args.clean_cache)

    def test_analyze_maps(self) -> None:
        """--analyze flag should accept --maps with space-separated names."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--analyze", "--maps", "c1m1_hotel", "c2m1_highway"]
        )
        self.assertEqual(args.maps, ["c1m1_hotel", "c2m1_highway"])

    def test_game_choices(self) -> None:
        """--game should only accept supported game IDs."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["--game", "unsupported_game", "--analyze"])

    def test_log_level(self) -> None:
        """--log-level should accept valid levels."""
        args = self.parser.parse_args(
            ["--game", "l4d2", "--log-level", "DEBUG", "--analyze"]
        )
        self.assertEqual(args.log_level, "DEBUG")

    def test_nolimit_flag(self) -> None:
        """--nolimit flag should be accessible."""
        args = self.parser.parse_args(["--game", "l4d2", "--nolimit", "--analyze"])
        self.assertTrue(args.nolimit)


if __name__ == "__main__":
    unittest.main()
