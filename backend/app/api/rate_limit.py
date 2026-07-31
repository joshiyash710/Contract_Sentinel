"""
In-process sliding-window rate limiter (feature 032, W3).

Caps login/signup/password attempts per client IP to blunt brute-force and signup abuse. Thresholds
are read LIVE from app.config (constitution §3), so overriding the env/constant changes behavior with
no code edit (spec AC-17).

Scope note (spec EC-8/EC-9): state is per-process and in-memory — it resets on restart (a short
window, acceptable) and is per-worker if the app is ever run with >1 uvicorn worker. Phase-1 runs
single-process; horizontal scaling would need shared counter storage (out of scope). Per-account
lockout, which must survive a restart, is persisted in the DB (UserStore), NOT here.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Optional

import app.config as _cfg


class RateLimiter:
    """Thread-safe sliding-window counter keyed by an arbitrary string (e.g. client IP)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, deque] = defaultdict(deque)

    def check(
        self, key: str, *, max_hits: Optional[int] = None, window_seconds: Optional[int] = None
    ) -> bool:
        """Record an attempt for `key`; return True if allowed, False if it exceeds the limit.

        Thresholds default to AUTH_RATE_LIMIT_MAX / AUTH_RATE_LIMIT_WINDOW_SECONDS (read live).
        """
        limit = _cfg.AUTH_RATE_LIMIT_MAX if max_hits is None else max_hits
        window = _cfg.AUTH_RATE_LIMIT_WINDOW_SECONDS if window_seconds is None else window_seconds
        now = time.time()
        cutoff = now - window
        with self._lock:
            dq = self._hits[key]
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) >= limit:
                return False
            dq.append(now)
            return True

    def reset(self, key: Optional[str] = None) -> None:
        """Clear one key (or everything if key is None). Used by tests / an admin reset."""
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)
