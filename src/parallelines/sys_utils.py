from __future__ import annotations

import logging
import sys

from parallelines.config import AppConfig

logger = logging.getLogger(__name__)


def parse_memory_limit(limit_str: str) -> int | None:
    """Parse a memory limit string into bytes.

    Accepts formats like ``"4GB"``, ``"2048MB"``, ``"0"`` (no limit).
    Returns ``None`` if the string is empty, ``0`` if explicitly disabled,
    or the byte count otherwise.
    """
    if not limit_str:
        return None
    limit_str = limit_str.strip().upper()
    if limit_str == "0":
        return 0
    if limit_str.endswith("GB"):
        try:
            return int(limit_str.removesuffix("GB")) * 1_073_741_824
        except ValueError:
            return None
    if limit_str.endswith("MB"):
        try:
            return int(limit_str.removesuffix("MB")) * 1_048_576
        except ValueError:
            return None
    if limit_str.endswith("KB"):
        try:
            return int(limit_str.removesuffix("KB")) * 1024
        except ValueError:
            return None
    try:
        return int(limit_str)
    except ValueError:
        return None


def check_memory_available(config: AppConfig, logger: logging.Logger) -> None:
    """Log a warning if ``memory_limit`` is set but cannot be verified.

    This is purely advisory -- actual memory enforcement is left to the OS.
    """
    raw = config.general.memory_limit
    if not raw:
        return
    limit_bytes = parse_memory_limit(raw)
    if limit_bytes is None:
        logger.warning("Unrecognised memory limit format '%s' -- ignoring", raw)
        return
    if limit_bytes == 0:
        return  # explicitly disabled

    # Try optional psutil first, then platform-specific fallbacks
    mem_available: int | None = None
    try:
        import psutil  # type: ignore[import-untyped]

        mem_available = psutil.virtual_memory().available
    except ImportError:
        pass

    if mem_available is None and sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            mem_status_buf = (ctypes.c_uint8 * 64)()
            # MEMORYSTATUSEX structure: 64 bytes, dwLength + state fields
            ctypes.c_uint64.from_buffer(mem_status_buf).value = 64
            if kernel32.GlobalMemoryStatusEx(mem_status_buf):
                # ullAvailPhys is at offset 8+8 = 16 on x64
                mem_available = ctypes.c_uint64.from_buffer(mem_status_buf, 16).value
        except Exception:
            pass

    if mem_available is None and sys.platform == "linux":
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            mem_available = int(parts[1]) * 1024
                        break
        except Exception:
            pass

    if mem_available is not None and limit_bytes > mem_available:
        logger.warning(
            "Memory limit (%s) exceeds available memory (%s MB) -- "
            "system may swap or OOM",
            raw,
            round(mem_available / 1_048_576),
        )
    elif mem_available is not None and limit_bytes > mem_available * 0.8:
        logger.info(
            "Memory limit (%s) is close to available memory (%s MB)",
            raw,
            round(mem_available / 1_048_576),
        )
