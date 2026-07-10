"""Extract embedded file list from BSP pakfile (ZIP segment at end of BSP)."""

from __future__ import annotations
import io
import logging
import re
import struct
import zipfile

logger = logging.getLogger(__name__)

# Regexes matching dependency calls in Squirrel (.nut) or CFG scripts.
_NUT_INCLUDE_RE = re.compile(r'IncludeScript\s*\(\s*"([^"]+)"\s*\)')
_NUT_PRECACHE_MODEL_RE = re.compile(r'PrecacheModel\s*\(\s*"([^"]+)"\s*\)')
_NUT_PRECACHE_SOUND_RE = re.compile(r'PrecacheSound\s*\(\s*"([^"]+)"\s*\)')
# Matches "exec <file>" with or without quotes around the filename.
_CFG_EXEC_RE = re.compile(r'^exec\s+"?([^"\s]+)', re.MULTILINE)


def extract_bsp_pakfile_entries(file_content: bytes) -> list[dict]:
    """Return list of {'path': str, 'size': int} for each file embedded in BSP pakfile.

    Returns empty list when BSP has no pakfile or on parse failure.
    """
    try:
        buf = io.BytesIO(file_content)
        with zipfile.ZipFile(buf, "r") as zf:
            result = []
            for info in zf.infolist():
                if not info.is_dir():
                    result.append({
                        "path": info.filename.replace("\\", "/"),
                        "size": info.file_size,
                        "crc": info.CRC,
                    })
            return result
    except (zipfile.BadZipFile, struct.error, Exception) as exc:
        logger.debug("BSP pakfile extraction failed: %s", exc)
        return []


def scan_bsp_scripts(file_content: bytes) -> set[str]:
    """Scan .nut/.cfg files embedded in a BSP pakfile for dependency calls.

    Opens the embedded ZIP once.  Scans each .nut for IncludeScript,
    PrecacheModel, PrecacheSound and each .cfg for ``exec`` calls.

    Returns a set of resource paths found in those calls.
    """
    deps: set[str] = set()
    try:
        buf = io.BytesIO(file_content)
        with zipfile.ZipFile(buf, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                lower = info.filename.lower()
                if not (lower.endswith(".nut") or lower.endswith(".cfg")):
                    continue
                try:
                    text = zf.read(info.filename).decode("utf-8", errors="replace")
                except Exception:
                    continue

                if lower.endswith(".nut"):
                    for m in _NUT_INCLUDE_RE.finditer(text):
                        raw = m.group(1).strip().replace("\\", "/")
                        if "/" not in raw:
                            raw = "scripts/vscripts/" + raw
                        if not raw.endswith(".nut"):
                            raw += ".nut"
                        deps.add(raw)
                    for m in _NUT_PRECACHE_MODEL_RE.finditer(text):
                        deps.add(m.group(1).replace("\\", "/"))
                    for m in _NUT_PRECACHE_SOUND_RE.finditer(text):
                        path = m.group(1).strip().replace("\\", "/")
                        if not path.lower().startswith("sound/"):
                            path = "sound/" + path
                        deps.add(path)
                elif lower.endswith(".cfg"):
                    for m in _CFG_EXEC_RE.finditer(text):
                        raw = m.group(1).strip().replace("\\", "/")
                        if not raw.endswith(".cfg"):
                            raw += ".cfg"
                        if not raw.startswith("cfg/"):
                            raw = "cfg/" + raw
                        deps.add(raw)
    except Exception:
        pass
    return deps
