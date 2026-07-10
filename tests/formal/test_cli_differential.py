"""Layer 3 — 差分测试：CLI 参数验证。

直接用 argparse 解析验证，不手写 Z3 布尔表达式。
"""
from __future__ import annotations

import argparse

import pytest


def _build_parser():
    from parallelines.cli import build_parser

    return build_parser()


class TestCliDifferential:
    """用 argparse 直接验证 CLI 规则。"""

    def test_game_required(self):
        """--game 是必需的。"""
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--analyze"])

    def test_analyze_flag(self):
        """--analyze 标志位。"""
        parser = _build_parser()
        args = parser.parse_args(["--game", "l4d2", "--analyze"])
        assert args.analyze is True

    def test_external_flag(self):
        """--external 接受 vpk 路径。"""
        parser = _build_parser()
        args = parser.parse_args(
            ["--game", "l4d2", "--external", "path/to/file.vpk"]
        )
        assert args.external == "path/to/file.vpk"

    def test_repl_flag(self):
        """--repl 标志位。"""
        parser = _build_parser()
        args = parser.parse_args(["--game", "l4d2", "--repl"])
        assert args.repl is True

    def test_game_root_default(self):
        """--game-root 默认值为空字符串。"""
        parser = _build_parser()
        args = parser.parse_args(["--game", "l4d2", "--analyze"])
        assert args.game_root == ""

    def test_game_root_set(self):
        """--game-root 可设置。"""
        parser = _build_parser()
        args = parser.parse_args(
            ["--game", "l4d2", "--analyze", "--game-root", "C:/games/l4d2"]
        )
        assert args.game_root == "C:/games/l4d2"

    def test_no_cache_flag(self):
        """--no-cache 必须与 --yes 配合才能跳过确认。"""
        parser = _build_parser()
        args = parser.parse_args(
            ["--game", "l4d2", "--analyze", "--no-cache", "--yes"]
        )
        assert args.no_cache is True
        assert args.yes is True

    def test_sv_pure_analyze_only(self):
        """--sv-pure 接受 whitelist 文件路径。"""
        parser = _build_parser()
        args = parser.parse_args(
            [
                "--game",
                "l4d2",
                "--analyze",
                "--sv-pure",
                "pure_server_whitelist.txt",
            ]
        )
        assert args.sv_pure == "pure_server_whitelist.txt"

    def test_output_formats(self):
        """--format 接受 json/csv/text/html。"""
        parser = _build_parser()
        for fmt in ("json", "csv", "text", "html"):
            args = parser.parse_args(["--game", "l4d2", "--analyze", "--format", fmt])
            assert args.format == fmt

    def test_invalid_format_rejected(self):
        """--format 拒绝无效值。"""
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--game", "l4d2", "--analyze", "--format", "xml"])

    def test_config_default_empty(self):
        """--config 默认值为空字符串。"""
        parser = _build_parser()
        args = parser.parse_args(["--game", "l4d2", "--analyze"])
        assert args.config == ""

    def test_config_path(self):
        """--config 接受路径。"""
        parser = _build_parser()
        args = parser.parse_args(
            ["--game", "l4d2", "--analyze", "--config", "my_config.toml"]
        )
        assert args.config == "my_config.toml"

    def test_entry_points(self):
        """--entry-points 接受多个值。"""
        parser = _build_parser()
        args = parser.parse_args(
            [
                "--game",
                "l4d2",
                "--analyze",
                "--entry-points",
                "a.txt",
                "b.txt",
            ]
        )
        assert args.entry_points == ["a.txt", "b.txt"]

    def test_external_with_priority(self):
        """--external + --vpk-priority。"""
        parser = _build_parser()
        args = parser.parse_args(
            [
                "--game",
                "l4d2",
                "--external",
                "x.vpk",
                "--vpk-priority",
                "lowest",
            ]
        )
        assert args.external == "x.vpk"
        assert args.vpk_priority == "lowest"

    def test_language_options(self):
        """--lang 接受 zh/en。"""
        parser = _build_parser()
        for lang in ("zh", "en"):
            args = parser.parse_args(["--game", "l4d2", "--analyze", "--lang", lang])
            assert args.lang == lang

    def test_debug_flag(self):
        """--debug 标志。"""
        parser = _build_parser()
        args = parser.parse_args(["--game", "l4d2", "--debug"])
        assert args.debug is True

    def test_cpu_flag(self):
        """--cpu 接受整数。"""
        parser = _build_parser()
        args = parser.parse_args(["--game", "l4d2", "--analyze", "--cpu", "4"])
        assert args.cpu == 4

    def test_memory_flag(self):
        """--memory 接受字符串。"""
        parser = _build_parser()
        args = parser.parse_args(["--game", "l4d2", "--analyze", "--memory", "4GB"])
        assert args.memory == "4GB"
