"""ResourceMonitor — system resource probe + admission control.

Simplified Banker-style: before allocating workers or issuing I/O, check
if resources are available.  Falls back gracefully when psutil is absent.

Ponytail: global semaphore, no per-account tracking.  Add per-worker
budgets if OOM persists.
"""

from __future__ import annotations

import logging
import os
import sys
import threading

logger = logging.getLogger(__name__)

_PER_WORKER_MIB = 500  # conservative per-VPK-worker estimate


class ResourceMonitor:
    """Probes system memory and clamps worker count accordingly.

    The ``memory_limit`` is enforced by capping parallelism rather than
    tracking per-worker consumption — fine-grained tracking is unnecessary
    for this I/O-bound workload.
    """

    def __init__(
        self,
        memory_limit_bytes: int | None = None,
        nolimit: bool = False,
    ) -> None:
        self._memory_limit = memory_limit_bytes
        self._nolimit = nolimit

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def clamp_workers(self, requested: int) -> int:
        """Reduce *requested* worker count based on 90 % of available memory."""
        if self._nolimit or not self._memory_limit:
            return requested

        avail = self._available_memory_bytes()
        if avail is None:
            return requested  # can't probe, trust the caller

        budget = avail * 0.9  # ponytail: 90 % cap, per-spec
        max_by_mem = max(1, int(budget / (_PER_WORKER_MIB * 1_048_576)))
        clamped = min(requested, max_by_mem)
        if clamped < requested:
            logger.info(
                "Memory budget: reduced workers %d→%d (%.1f GB avail @ 90%%",
                requested,
                clamped,
                avail / 1_073_741_824,
            )
        return clamped

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _available_memory_bytes(self) -> int | None:
        try:
            import psutil  # type: ignore[import-untyped]

            return psutil.virtual_memory().available
        except ImportError:
            pass

        if os.name == "nt":
            try:
                import ctypes

                kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
                buf = (ctypes.c_uint8 * 64)()
                ctypes.c_uint64.from_buffer(buf).value = 64
                if kernel32.GlobalMemoryStatusEx(buf):
                    return ctypes.c_uint64.from_buffer(buf, 16).value
            except Exception:
                pass

        if sys.platform == "linux":
            try:
                with open("/proc/meminfo") as f:
                    for line in f:
                        if line.startswith("MemAvailable:"):
                            parts = line.split()
                            if len(parts) >= 2:
                                return int(parts[1]) * 1024
                            break
            except Exception:
                pass

        return None


class IoThrottle:
    """Semaphore-based I/O concurrency throttle.

    Limits the number of concurrent file writes instead of byte-level
    rate limiting — sufficient for our workload (Parquet persistence
    from the main process, sequential VPK parsing in Pool workers).

    Thread-safe.  Use as a context manager::

        with throttle:
            df.to_parquet(path)

    Ponytail: global semaphore, per-priority queue if seek-heavy
    workloads appear.
    """

    def __init__(self, max_concurrent: int = 2) -> None:
        self._sem = threading.Semaphore(max_concurrent)
        self._max = max_concurrent

    @property
    def max_concurrent(self) -> int:
        return self._max

    def acquire(self) -> None:
        self._sem.acquire()

    def release(self) -> None:
        self._sem.release()

    def __enter__(self) -> IoThrottle:
        self.acquire()
        return self

    def __exit__(self, *args: object) -> None:
        self.release()


def build_resource_monitor(
    memory_limit_str: str = "",
    nolimit: bool = False,
) -> ResourceMonitor:
    """Build a :class:`ResourceMonitor` from a config memory-limit string."""
    from parallelines.sys_utils import parse_memory_limit

    limit_bytes = parse_memory_limit(memory_limit_str)
    return ResourceMonitor(memory_limit_bytes=limit_bytes, nolimit=nolimit)
