"""Small in-memory sliding-window rate limiter (single process). Use a shared store (Redis) when running several instances."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_LOCK = threading.Lock()
_HITS: dict[str, deque] = defaultdict(deque)


def hit(key: str, limit: int, window_s: int = 60) -> None:
    now = time.monotonic()
    with _LOCK:
        q = _HITS[key]
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= limit:
            retry = max(1, int(window_s - (now - q[0])) + 1)
            raise HTTPException(429, "Too many requests. Wait a little and try again.", headers={"Retry-After": str(retry)})
        q.append(now)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


def reset() -> None:
    with _LOCK:
        _HITS.clear()
