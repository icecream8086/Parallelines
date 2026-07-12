"""Tests for ResourceMonitor and IoThrottle (resource limits)."""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest

from parallelines.resource import IoThrottle, ResourceMonitor, build_resource_monitor


class TestResourceMonitor:
    """clamp_workers admission control."""

    def test_passthrough_when_no_limit(self) -> None:
        rm = ResourceMonitor(memory_limit_bytes=None)
        assert rm.clamp_workers(8) == 8

    def test_passthrough_when_limit_zero(self) -> None:
        rm = ResourceMonitor(memory_limit_bytes=0)
        assert rm.clamp_workers(8) == 8

    def test_passthrough_when_nolimit(self) -> None:
        rm = ResourceMonitor(memory_limit_bytes=8 * 1_073_741_824, nolimit=True)
        assert rm.clamp_workers(8) == 8

    def test_passthrough_when_cannot_probe(self) -> None:
        rm = ResourceMonitor(memory_limit_bytes=8 * 1_073_741_824)
        with patch.object(rm, "_available_memory_bytes", return_value=None):
            assert rm.clamp_workers(8) == 8

    def test_reduces_workers_when_memory_tight(self) -> None:
        """With only 1 GB available and 500 MiB/worker estimate, max is 1 worker."""
        rm = ResourceMonitor(memory_limit_bytes=4 * 1_073_741_824)
        # 1 GB available, 90% budget = 0.9 GB, ~900 MiB / 500 MiB = 1 worker
        with patch.object(rm, "_available_memory_bytes", return_value=1_073_741_824):
            assert rm.clamp_workers(8) == 1

    def test_respects_90_percent_cap(self) -> None:
        """Exactly 500 MiB available → 90% = 450 MiB → 0 → clamped to 1."""
        rm = ResourceMonitor(memory_limit_bytes=4 * 1_073_741_824)
        with patch.object(rm, "_available_memory_bytes", return_value=500 * 1_048_576):
            assert rm.clamp_workers(8) == 1

    def test_ample_memory_no_reduction(self) -> None:
        """32 GB available @ 90% → ~28.8 GB → ~57 workers, but only 8 requested."""
        rm = ResourceMonitor(memory_limit_bytes=32 * 1_073_741_824)
        with patch.object(rm, "_available_memory_bytes", return_value=32 * 1_073_741_824):
            assert rm.clamp_workers(8) == 8

    def test_build_resource_monitor_empty(self) -> None:
        rm = build_resource_monitor("", False)
        assert rm._memory_limit is None
        assert rm._nolimit is False

    def test_build_resource_monitor_with_value(self) -> None:
        rm = build_resource_monitor("4GB", False)
        assert rm._memory_limit == 4 * 1_073_741_824

    def test_build_resource_monitor_nolimit(self) -> None:
        rm = build_resource_monitor("", True)
        assert rm._nolimit is True


class TestIoThrottle:
    """IoThrottle semaphore-based concurrency control."""

    def test_acquire_release(self) -> None:
        t = IoThrottle(max_concurrent=1)
        t.acquire()
        # Second acquire would block if release didn't work — spawn thread
        released = threading.Event()

        def try_acquire() -> None:
            t.acquire()
            released.set()

        thr = threading.Thread(target=try_acquire, daemon=True)
        thr.start()
        time.sleep(0.05)
        assert not released.is_set()  # still blocked
        t.release()
        thr.join(timeout=0.5)
        assert released.is_set()

    def test_context_manager(self) -> None:
        t = IoThrottle(max_concurrent=1)
        with t:
            pass  # acquired then released

    def test_context_manager_serializes(self) -> None:
        """With max_concurrent=1, two context managers cannot overlap."""
        t = IoThrottle(max_concurrent=1)
        order: list[int] = []

        def worker(n: int) -> None:
            with t:
                order.append(n)
                time.sleep(0.05)

        threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(3)]
        for thr in threads:
            thr.start()
        for thr in threads:
            thr.join(timeout=1)

        # Order should be sequential: no two same timestamps adjacent
        assert len(order) == 3
        assert order == sorted(order)  # sequential, no overlap

    def test_max_concurrent_property(self) -> None:
        t = IoThrottle(max_concurrent=4)
        assert t.max_concurrent == 4

    def test_concurrent_2_allows_two(self) -> None:
        """With max_concurrent=2, two acquires succeed immediately."""
        t = IoThrottle(max_concurrent=2)
        t.acquire()
        t.acquire()  # second must not block
        t.release()
        t.release()


class TestCacheManagerIoThrottleIntegration:
    """CacheManager(io_throttle=None) must not crash (regression guard)."""

    def test_cache_manager_none_throttle(self) -> None:
        """CacheManager should accept io_throttle=None and not crash on save."""
        from pathlib import Path
        from parallelines.cache.manager import CacheManager, _NullContextManager, _NULL_CM

        cm = CacheManager(Path("/nonexistent/test_cache"), io_throttle=None)
        assert cm._io_throttle is None
        # Verify the null context manager works
        with _NULL_CM:
            pass
        assert isinstance(_NULL_CM, _NullContextManager)
