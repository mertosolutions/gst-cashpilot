"""Small in-process result cache for the dashboard calls.

On AlloyDB every query is a network trip, and a dashboard call runs dozens of them. The results only change when data is written,
so they are kept per business and month and cleared on any successful write request (see the middleware in main.py)."""
import threading
import time
from collections.abc import Callable
from typing import Any

_lock = threading.Lock()
_store: dict[tuple, tuple[float, Any]] = {}
TTL_SECONDS = 600


def cached(key: tuple, compute: Callable[[], Any], ttl: int = TTL_SECONDS) -> Any:
    now = time.monotonic()
    with _lock:
        hit = _store.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = compute()
    with _lock:
        _store[key] = (time.monotonic(), value)
    return value


def clear() -> None:
    with _lock:
        _store.clear()
