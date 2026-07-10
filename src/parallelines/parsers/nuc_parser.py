"""Extract dependencies from .nuc compiled Squirrel bytecode via sq decompiler."""

from __future__ import annotations
import logging
import re
import subprocess
import tempfile
import os

logger = logging.getLogger(__name__)

_INCLUDE_RE = re.compile(r'IncludeScript\s*\(\s*"([^"]+)"\s*\)')
_PRECACHE_MODEL_RE = re.compile(r'PrecacheModel\s*\(\s*"([^"]+)"\s*\)')
_PRECACHE_SOUND_RE = re.compile(r'PrecacheSound\s*\(\s*"([^"]+)"\s*\)')

_SQ_BINARY = "sq"  # 或从 config 读取路径


def _resolve_include(raw: str) -> str:
    path = raw.strip().replace("\\", "/")
    if not path.endswith(".nut"):
        path += ".nut"
    if "/" not in path:
        path = "scripts/vscripts/" + path
    return path


def extract_nuc_dependencies(file_content: bytes) -> set[str]:
    """Decompile .nuc bytecode via ``sq`` and extract deps from the output."""
    try:
        # Write .nuc to temp file
        fd, tmp_path = tempfile.mkstemp(suffix=".nuc")
        os.write(fd, file_content)
        os.close(fd)

        result = subprocess.run(
            [_SQ_BINARY, "-d", tmp_path],
            capture_output=True, text=True, timeout=10,
        )
        os.unlink(tmp_path)

        if result.returncode != 0:
            logger.debug("sq decompile failed for .nuc: %s", result.stderr[:200])
            return set()

        decompiled = result.stdout
        deps: set[str] = set()
        for match in _INCLUDE_RE.finditer(decompiled):
            deps.add(_resolve_include(match.group(1)))
        for match in _PRECACHE_MODEL_RE.finditer(decompiled):
            deps.add(match.group(1))
        for match in _PRECACHE_SOUND_RE.finditer(decompiled):
            path = match.group(1).replace("\\", "/")
            if not path.lower().startswith("sound/"):
                path = "sound/" + path
            deps.add(path)
        return deps
    except FileNotFoundError:
        logger.debug("sq binary not found; skipping .nuc parsing")
        return set()
    except Exception as exc:
        logger.warning("Failed to parse .nuc: %s", exc)
        return set()
