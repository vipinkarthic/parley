"""In memory sliding window rate limiter.

Single process and best effort; a multi instance deployment would need Redis.
Bounded, because the key embeds a caller supplied email.
"""
import time
from collections import OrderedDict, deque

# Enough for real callers, small enough that a flood cannot exhaust memory.
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
    """Spent windows go first, since an abusive scan produces thousands."""
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
    """Caller identity for rate limiting.

    Spoofable, so it is a speed bump and the email keyed limits stay too.
    """
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded[:64]
    client = getattr(request, "client", None)
    return (getattr(client, "host", None) or "unknown")[:64]
