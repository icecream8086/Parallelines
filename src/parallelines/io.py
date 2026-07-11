"""Unified I/O layer for Parallelines.

Consolidates all file reading/writing conventions (encoding, error handling,
atomicity) into a single module. All other modules should go through these
classes rather than calling ``Path.read_text`` / ``json.load`` directly.

Encoding constants defined here are the single source of truth for the entire
codebase.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from parallelines.error_policy import parse_failure

logger = logging.getLogger(__name__)

# ── Encoding conventions (single source of truth) ──

GAME_FILE_ENCODING = "utf-8"
GAME_FILE_ERRORS = "replace"       # game files may not be clean UTF-8
CONFIG_FILE_ENCODING = "utf-8"
WRITE_FILE_ERRORS = "surrogateescape"  # preserve undecodable bytes in paths


class FileReader:
    """Unified file reading.

    Every module that needs to read a file should use one of these methods
    instead of calling ``Path()`` / ``open()`` directly.
    """

    @staticmethod
    def read_text(path: str | Path, *, encoding: str = CONFIG_FILE_ENCODING,
                  errors: str | None = None) -> str:
        """Read a text file.  Default encoding is UTF-8 (strict).

        Pass ``errors="surrogateescape"`` to survive undecodable bytes,
        matching the write path.
        """
        if errors is not None:
            return Path(path).read_text(encoding=encoding, errors=errors)
        return Path(path).read_text(encoding=encoding)

    @staticmethod
    def read_game_text(path: str | Path) -> str:
        """Read a game config file (gameinfo.txt, addoninfo, manifest, …).

        Tolerates non-UTF-8 bytes via ``errors="replace"``.
        """
        return Path(path).read_text(
            encoding=GAME_FILE_ENCODING, errors=GAME_FILE_ERRORS
        )

    @staticmethod
    def read_json(path: str | Path) -> dict:
        """Read a JSON file.  Encoding is always UTF-8."""
        with open(path, encoding=CONFIG_FILE_ENCODING) as f:
            return json.load(f)

    @staticmethod
    def read_binary(path: str | Path) -> bytes:
        """Read a file as raw bytes."""
        return Path(path).read_bytes()

    @staticmethod
    def read_vfs_text(file_obj) -> str | None:
        """Read text from a VFS file object, returning ``None`` on failure.

        This is intentionally lenient — callers should not have to catch
        exceptions when probing files that may not exist or may be corrupt.
        """
        try:
            return file_obj.open_str().read()
        except Exception as exc:
            parse_failure(exc, "read_vfs_text")
            return None

    @staticmethod
    def read_vfs_bytes(file_obj) -> bytes | None:
        """Read binary from a VFS file object, returning ``None`` on failure."""
        try:
            return file_obj.open_bin().read()
        except Exception as exc:
            parse_failure(exc, "read_vfs_bytes")
            return None


class FileWriter:
    """Unified file writing.

    Every module that writes a file should use one of these methods to ensure
    consistent encoding, directory creation, and (where appropriate) atomicity.
    """

    @staticmethod
    def write_text(
        path: str | Path, content: str, *, encoding: str = CONFIG_FILE_ENCODING,
        errors: str = WRITE_FILE_ERRORS,
    ) -> None:
        """Write a text file, creating parent directories if needed."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(content, encoding=encoding, errors=errors)

    @staticmethod
    def write_json(path: str | Path, data: dict) -> None:
        """Write a JSON file (pretty-printed, non-ASCII preserved)."""
        FileWriter.write_text(path, json.dumps(data, indent=2, ensure_ascii=False))

    @staticmethod
    def atomic_write_text(
        path: str | Path, content: str, *, encoding: str = CONFIG_FILE_ENCODING,
        errors: str = WRITE_FILE_ERRORS,
    ) -> None:
        """Atomically write a text file.

        Writes to a temporary file first, then renames it over *path*.  This
        guarantees the target file is never left in a partial/corrupt state,
        even if the process crashes mid-write.
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
        try:
            os.write(fd, content.encode(encoding, errors=errors))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, target)  # atomic on both Windows and Linux


def reconfigure_stdout() -> None:
    """Force UTF-8 encoding on ``sys.stdout`` for cross-platform Unicode support.

    游戏文件路径和输出可能包含任意 Unicode（含中文），而 Windows 终端经常使
    用 cp936/GB2312 code page。本函数在 CLI 入口点被调用一次，避免此后每个
    ``print()`` 因为编码问题抛出 ``UnicodeEncodeError``。
    """
    import io
    import sys

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
