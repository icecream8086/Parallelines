"""Cache validation strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod


class CacheStrategy(ABC):
    """Base class for cache validation strategies."""

    @abstractmethod
    def is_valid(self, cache_meta: dict, current_state: dict) -> bool:
        """Return True if the cached metadata matches the current state.

        Args:
            cache_meta: Metadata dict loaded from the cache (keyed by VPK
                        identifier, each value is a dict of attributes).
            current_state: Current metadata dict reflecting the filesystem
                           state (same structure as *cache_meta*).

        Returns:
            True if the cache is still valid, False otherwise.
        """
        ...


class MtimeStrategy(CacheStrategy):
    """Validate cache entries by comparing mtime and size."""

    def is_valid(self, cache_meta: dict, current_state: dict) -> bool:
        if set(cache_meta.keys()) != set(current_state.keys()):
            return False
        for key, cached in cache_meta.items():
            current = current_state.get(key)
            if current is None:
                return False
            if cached.get("mtime") != current.get("mtime"):
                return False
            if cached.get("size") != current.get("size"):
                return False
        return True


class HashStrategy(CacheStrategy):
    """Validate cache entries by comparing SHA-256 hashes."""

    def is_valid(self, cache_meta: dict, current_state: dict) -> bool:
        if set(cache_meta.keys()) != set(current_state.keys()):
            return False
        for key, cached in cache_meta.items():
            current = current_state.get(key)
            if current is None:
                return False
            if cached.get("sha256") != current.get("sha256"):
                return False
        return True
