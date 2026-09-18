"""In-memory TTL cache and rate limiting for trend research sources."""

from __future__ import annotations

import asyncio
import time
from typing import Generic, TypeVar

from app.core.logging import get_logger

logger = get_logger("arya.trend_sources.cache")

T = TypeVar("T")


class TrendCache(Generic[T]):
    """In-memory cache with configurable TTL expiration."""

    def __init__(self, default_ttl_seconds: int = 3600) -> None:
        self._ttl = default_ttl_seconds
        # key -> (expires_at, data)
        self._store: dict[str, tuple[float, T]] = {}
        self._lock = asyncio.Lock()

    def _normalize_key(self, key: str) -> str:
        return key.strip().lower()

    async def get(self, key: str) -> T | None:
        norm_key = self._normalize_key(key)
        async with self._lock:
            entry = self._store.get(norm_key)
            if entry is None:
                return None
            expires_at, val = entry
            if time.monotonic() > expires_at:
                del self._store[norm_key]
                return None
            return val

    async def set(self, key: str, value: T, ttl_seconds: int | None = None) -> None:
        norm_key = self._normalize_key(key)
        ttl = ttl_seconds if ttl_seconds is not None else self._ttl
        expires_at = time.monotonic() + ttl
        async with self._lock:
            self._store[norm_key] = (expires_at, value)

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()

    @property
    def size(self) -> int:
        return len(self._store)


class SimpleRateLimiter:
    """Token bucket / minimum interval rate limiter to protect external APIs."""

    def __init__(self, min_interval_seconds: float = 0.2) -> None:
        self._min_interval = min_interval_seconds
        self._last_call: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_call = time.monotonic()
