"""Oracle-Free adversarial tests — Terminal / Encoding.

Metamorphic relations tested in this module:

    MR-T1  stdout ASCII transparency before/after reconfigure
    MR-T2  Double reconfigure resilience (BytesIO + real PTY)
    MR-T3  Piped output encoding integrity

See ``devdocs/adversarial-path-env-testing.md`` for the full design.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys

import pytest

from parallelines.config import AppConfig
from parallelines.parsers.gameinfo import parse_gameinfo
from parallelines.vfs.builder import VfsBuilder


class TestStdoutReconfigure:
    """stdout UTF-8 reconfigure adversarial tests.

    MR-T1: ASCII transparency after reconfigure
    MR-T2: Double reconfigure resilience
    MR-T3: Piped output encoding
    """

    def _reconfigure(self) -> None:
        """Copy of cli.py:main() stdout reconfigure logic."""
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="surrogateescape")
            except Exception:
                pass
        else:
            try:
                sys.stdout = io.TextIOWrapper(
                    sys.stdout.buffer, encoding="utf-8", errors="surrogateescape"
                )
            except Exception:
                pass

    # MR-T2: Double reconfigure
    def test_double_reconfigure_on_bytesio(self) -> None:
        """Second reconfigure on BytesIO-backed stdout must not crash or lose data."""
        original = sys.stdout
        try:
            buffer = io.BytesIO()
            sys.stdout = io.TextIOWrapper(buffer, encoding="cp936")
            self._reconfigure()
            self._reconfigure()
            print("test message 中文测试", end="")
            sys.stdout.flush()
            buffer.seek(0)
            output = buffer.read().decode("utf-8")
            assert "test message" in output
        finally:
            sys.stdout = original

    def test_double_reconfigure_on_real_pty(self) -> None:
        """Second reconfigure on a REAL pseudo-terminal must not crash.

        Unlike BytesIO, a real PTY has actual TTY semantics:
        - buffer attribute behavior
        - line buffering
        - close propagation
        """
        if not hasattr(os, "openpty"):
            pytest.skip("os.openpty() not available (non-Unix platform)")
        master_fd, slave_fd = os.openpty()
        slave_stream = io.TextIOWrapper(os.fdopen(slave_fd, "wb", buffering=0), encoding="cp936")
        original = sys.stdout
        try:
            sys.stdout = slave_stream
            self._reconfigure()
            self._reconfigure()
            # Print and verify data arrives at master
            print("reconfigure test", end="")
            sys.stdout.flush()
            os.read(master_fd, 1024)  # should not hang or raise
        finally:
            sys.stdout = original
            os.close(master_fd)

    def test_stdout_without_buffer_attribute(self) -> None:
        """stdout without .buffer must not crash reconfigure."""
        original = sys.stdout

        class NoBufferStdout:
            def write(self, s): ...
            def flush(self): ...

        try:
            sys.stdout = NoBufferStdout()  # type: ignore[assignment]
            self._reconfigure()
        except Exception as e:
            pytest.fail(f"reconfigure crashed on buffer-less stdout: {e}")
        finally:
            sys.stdout = original

    # MR-T1: ASCII transparency
    def test_ascii_transparency_after_reconfigure(self) -> None:
        """7-bit ASCII must pass through unchanged after reconfigure."""
        buffer = io.BytesIO()
        original = sys.stdout
        try:
            sys.stdout = io.TextIOWrapper(buffer, encoding="cp936")
            self._reconfigure()
            ascii_msg = "Hello World 123 !@#$%^"
            print(ascii_msg, end="")
            sys.stdout.flush()
            buffer.seek(0)
            assert buffer.read().decode("utf-8") == ascii_msg
        finally:
            sys.stdout = original

    # MR-T3: Piped output
    def test_piped_output_readable_by_subprocess(self) -> None:
        """parallelines --help piped to subprocess must decode correctly."""
        result = subprocess.run(
            [sys.executable, "-m", "parallelines", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert len(result.stdout) > 0
        assert "parallelines" in result.stdout.lower()

    def test_output_with_unicode_file_paths(self) -> None:
        """Unicode text must survive reconfigure without UnicodeEncodeError."""
        buffer = io.BytesIO()
        original = sys.stdout
        try:
            sys.stdout = io.TextIOWrapper(buffer, encoding="cp936")
            self._reconfigure()
            test_str = "文件: materials/纹理/贴图.vtf (来源: 测试mod.vpk)"
            print(test_str, end="")
            sys.stdout.flush()
            buffer.seek(0)
            output = buffer.read().decode("utf-8")
            assert test_str in output
        finally:
            sys.stdout = original


class TestFileEncodingAssumptions:
    """gameinfo.txt / addonlist.txt encoding adversarial tests."""

    def test_gameinfo_cp1252_decodes_correctly(self, tmp_path) -> None:
        """H9 FIXED: cp1252 gameinfo.txt decodes to correct characters."""
        gi = tmp_path / "gameinfo.txt"
        gi.write_bytes(b'GameInfo\n{\n\tgame\t"L\xe9ft 4 Dead"\n}\n')

        result = parse_gameinfo(gi)
        game_name = str(result.get("gameinfo", {}).get("game", ""))

        # Fix: cp1252 0xE9 = é, no more U+FFFD replacement chars
        assert "�" not in game_name, (
            f"H9 FIXED: cp1252 'e' should not produce U+FFFD.\n"
            f"  game={game_name!r}\n"
        )
        assert "é" in game_name, (
            f"H9 FIXED: cp1252 'é' should be decoded correctly.\n"
            f"  game={game_name!r}\n"
        )

    def test_addonlist_without_bom_parses_correctly(self, tmp_path) -> None:
        """addonlist.txt without BOM must parse correctly."""
        game_root = tmp_path / "game"
        game_root.mkdir()
        (game_root / "gameinfo.txt").write_text(
            "GameInfo\n{\n\tFileSystem\n\t{\n\t\tSearchPaths\n\t\t{\n\t\t\tGame\t|gameinfo_path|.\n\t\t}\n\t}\n}\n",
            encoding="utf-8",
        )
        addonlist = game_root / "addonlist.txt"
        addonlist.write_text('"test_addon.vpk"\t\t"1"\n', encoding="utf-8")

        config = AppConfig()
        config.general.game = "l4d2"
        builder = VfsBuilder(game_root, config, use_cache=False, num_workers=1)
        result = builder._read_addonlist()

        assert "test_addon.vpk" in result
        enabled, order = result["test_addon.vpk"]
        assert enabled is True
        assert order == 0
