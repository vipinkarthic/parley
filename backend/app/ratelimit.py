"""Tiny in-memory rate limiter (sliding window) for abuse-prone endpoints.

Single-process, best-effort abuse protection: caps password-guessing on login,
OTP-email spam on signup, and passcode-guessing on join. State is per-process
and resets on restart; for a multi-instance deployment this would move to
Redis, but it meaningfully slows brute-force / email-bombing here.

Two properties that were missing and matter:

* **Bounded memory.** Keys used to be created and never removed. The key
  embeds a caller-supplied email, so an attacker submitting logins for a
  stream of distinct addresses grew the dict until the process was killed.
  Empty windows are now dropped, and the table has a hard ceiling.
* **A deque, not a list.** Expiring the oldest hit was `list.pop(0)`, which
  is O(n) in the window size.
"""
import time
from collections import OrderedDict, deque

# Enough for every distinct caller a single free-tier instance sees in a
# window, and small enough that a flood of unique keys cannot exhaust memory.
MAX_TRACKED_KEYS = 20_000

_hits: "OrderedDict[str, deque[float]]" = OrderedDict()


def allow(key: str, limit: int, window_seconds: int) -> bool:
    """Record a hit for `key`; return False if it exceeds `limit` per window."""
    now = time.time()
    cutoff = now - window_seconds

    hits = _hits.get(key)
    if hits is None:
        hits = _hits[key] = deque()
    else:
        _hits.move_to_end(key)

    while hits and hits[0] < cutoff:
        hits.popleft()

    if len(hits) >= limit:
        return False

    hits.append(now)
    _evict_if_needed()
    return True


def _evict_if_needed() -> None:
    """Drop spent and then least-recently-used keys to stay under the ceiling.

    Expired-but-present keys are the cheap win: they hold no information, and
    an abusive scan produces them by the thousand.
    """
    if len(_hits) <= MAX_TRACKED_KEYS:
        return
    for key in [k for k, v in _hits.items() if not v]:
        del _hits[key]
    while len(_hits) > MAX_TRACKED_KEYS:
        _hits.popitem(last=False)


def reset() -> None:
    """Drop all state. For tests."""
    _hits.clear()


def client_ip(request) -> str:
    """Best-effort caller identity for rate limiting.

    Render terminates TLS and proxies, so `request.client.host` is the proxy.
    The left-most X-Forwarded-For entry is the original caller and is the only
    one worth keying on - but it is caller-supplied and trivially spoofed, so
    this is a speed bump against casual spraying, not an identity. Email-keyed
    limits stay in place alongside it.
    """
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded[:64]
    client = getattr(request, "client", None)
    return (getattr(client, "host", None) or "unknown")[:64]
