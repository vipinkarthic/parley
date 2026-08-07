"""Tiny in-memory rate limiter (fixed-window) for auth endpoints.

Single-process, best-effort abuse protection: caps password-guessing on login and
OTP-email spam on signup. State is per-process and resets on restart; for a
multi-instance deployment this would move to Redis, but it meaningfully slows
brute-force / email-bombing here.
"""
import time

_hits: dict[str, list[float]] = {}


def allow(key: str, limit: int, window_seconds: int) -> bool:
    """Record a hit for `key`; return False if it exceeds `limit` per window."""
    now = time.time()
    cutoff = now - window_seconds
    q = _hits.setdefault(key, [])
    while q and q[0] < cutoff:
        q.pop(0)
    if len(q) >= limit:
        return False
    q.append(now)
    return True
