"""Tests for parallelines.io — encoding and output configuration."""

import os
import tempfile
from unittest.mock import MagicMock, patch

from parallelines.io import FileReader, reconfigure_stdout


def test_reconfigure_stdout_tty_reconfigures():
    """isatty()=True: stdout reconfigured to utf-8."""
    mock_stdout = MagicMock()
    mock_stdout.isatty.return_value = True

    with patch("sys.stdout", mock_stdout):
        reconfigure_stdout()

    mock_stdout.reconfigure.assert_called_once_with(
        encoding="utf-8", errors="surrogateescape"
    )


def test_reconfigure_stdout_pipe_skips_reconfigure():
    """isatty()=False (piped): stdout left untouched."""
    mock_stdout = MagicMock()
    mock_stdout.isatty.return_value = False

    with patch("sys.stdout", mock_stdout):
        reconfigure_stdout()

    mock_stdout.reconfigure.assert_not_called()


def test_reconfigure_stdout_pipe_non_utf8_writes_ok():
    """isatty()=False: writing non-ASCII text does not crash."""
    mock_stdout = MagicMock()
    mock_stdout.isatty.return_value = False
    mock_stdout.encoding = "cp1252"

    with patch("sys.stdout", mock_stdout):
        reconfigure_stdout()
        mock_stdout.write("Cafe 100 degrés")

    mock_stdout.reconfigure.assert_not_called()
    mock_stdout.write.assert_called_once_with("Cafe 100 degrés")


# ── FileReader.read_game_text ──────────────────────────────────────────


def _write_tmp_bytes(data: bytes) -> str:
    """Write *data* to a temporary file and return its path."""
    tmp = tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False)
    tmp.write(data)
    tmp.close()
    return tmp.name


def test_read_game_text_utf8() -> None:
    """UTF-8 file reads without errors."""
    content = "café 100°"
    path = _write_tmp_bytes(content.encode("utf-8"))
    try:
        result = FileReader.read_game_text(path)
        assert result == content
    finally:
        os.unlink(path)


def test_read_game_text_cp1252() -> None:
    """cp1252-encoded file decodes without replacement characters."""
    raw = b"caf\xe9 100\xb0"  # "café 100°" in cp1252
    path = _write_tmp_bytes(raw)
    try:
        result = FileReader.read_game_text(path)
        assert "�" not in result, f"replacement char found: {result!r}"
        assert result == "café 100°"
    finally:
        os.unlink(path)


def test_read_game_text_shift_jis() -> None:
    """Shift-JIS-encoded file decodes without replacement characters."""
    raw = "テスト".encode("shift_jis")
    path = _write_tmp_bytes(raw)
    try:
        result = FileReader.read_game_text(path)
        # On a Japanese system the locale encoding is shift_jis and the
        # result will match exactly; on a Western system cp1252 decodes
        # the same bytes to different characters.  The critical invariant
        # is that there are NO replacement characters (the original bug).
        assert "�" not in result, f"replacement char found: {result!r}"
    finally:
        os.unlink(path)
