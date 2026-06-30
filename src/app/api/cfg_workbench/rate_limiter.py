"""
Simple in-memory rate limiter for CFG Workbench API endpoints.

Per-IP token bucket with configurable rate and burst. Suitable for a
single-process demo/research deployment. For production, replace with
Redis-backed rate limiting or an API gateway.

Usage:
    from app.api.cfg_workbench.rate_limiter import rate_limit

    @router.post("/execute-node")
    def execute_node(req: ExecuteNodeRequest, request: Request):
        rate_limit(request, max_requests=100, window_seconds=60)
        ...
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field

from fastapi import HTTPException, Request


@dataclass
class _Bucket:
    """Token bucket for a single client."""
    tokens: float = 100.0
    last_refill: float = field(default_factory=time.monotonic)
    max_tokens: float = 100.0


class _RateLimiter:
    """Thread-safe in-memory rate limiter."""

    def __init__(self) -> None:
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def _refill(self, bucket: _Bucket, now: float, refill_rate: float) -> None:
        """Refill tokens based on elapsed time."""
        elapsed = now - bucket.last_refill
        bucket.tokens = min(bucket.max_tokens, bucket.tokens + elapsed * refill_rate)
        bucket.last_refill = now

    def allow(self, key: str, max_requests: int = 100, window_seconds: int = 60) -> bool:
        """Check if a request is allowed. Returns True if within limit.

        Args:
            key: Client identifier (typically IP address).
            max_requests: Maximum requests allowed in the window.
            window_seconds: Time window in seconds.

        Returns:
            True if the request is allowed, False if rate limited.
        """
        now = time.monotonic()
        refill_rate = max_requests / window_seconds

        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(
                    tokens=max_requests - 1,
                    last_refill=now,
                    max_tokens=max_requests,
                )
                self._buckets[key] = bucket
                return True

            self._refill(bucket, now, refill_rate)

            if bucket.tokens >= 1:
                bucket.tokens -= 1
                return True

            return False

    def cleanup(self, max_age_seconds: float = 300) -> int:
        """Remove stale buckets. Returns count of removed entries."""
        now = time.monotonic()
        with self._lock:
            stale = [
                key for key, b in self._buckets.items()
                if now - b.last_refill > max_age_seconds
            ]
            for key in stale:
                del self._buckets[key]
            return len(stale)


# Global instance
_limiter = _RateLimiter()


def rate_limit(
    request: Request,
    max_requests: int = 100,
    window_seconds: int = 60,
) -> None:
    """Rate-limit a request by client IP.

    Raises HTTPException(429) if the client has exceeded the limit.

    Args:
        request: FastAPI Request object.
        max_requests: Max requests per window (default 100/min).
        window_seconds: Window size in seconds (default 60).

    Raises:
        HTTPException: 429 Too Many Requests.
    """
    client_ip = request.client.host if request.client else "unknown"
    key = f"ip:{client_ip}"

    if not _limiter.allow(key, max_requests=max_requests, window_seconds=window_seconds):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please slow down.",
            headers={"Retry-After": str(window_seconds)},
        )


def rate_limit_ws(websocket, max_requests: int = 100, window_seconds: int = 60) -> bool:
    """Rate-limit a WebSocket command by client host.

    Returns True if allowed, False if rate limited.
    """
    client_host = getattr(websocket.client, 'host', 'unknown') if hasattr(websocket, 'client') else 'unknown'
    key = f"ws:{client_host}"
    return _limiter.allow(key, max_requests=max_requests, window_seconds=window_seconds)
