"""Kayan pencere rate limiter. Redis varsa paylaşımlı, yoksa süreç içi bellek."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from .config import get_settings

_lock = threading.Lock()
_mem: dict[str, deque] = defaultdict(deque)
_redis = None
_redis_checked = False


def _get_redis():
    global _redis, _redis_checked
    if _redis_checked:
        return _redis
    _redis_checked = True
    s = get_settings()
    if s.env == "test" or s.celery_eager:
        return None
    try:
        import redis

        r = redis.Redis.from_url(s.redis_url, socket_connect_timeout=0.3, socket_timeout=0.3)
        r.ping()
        _redis = r
    except Exception:  # noqa: BLE001
        _redis = None
    return _redis


def reset() -> None:
    global _redis_checked, _redis
    _redis_checked = False
    _redis = None
    with _lock:
        _mem.clear()


def hit(key: str, limit: int, window: int = 60) -> tuple[bool, int]:
    """(izinli_mi, kalan_saniye)"""
    r = _get_redis()
    now = time.time()
    if r is not None:
        try:
            k = f"rl:{key}"
            pipe = r.pipeline()
            pipe.zremrangebyscore(k, 0, now - window)
            pipe.zadd(k, {f"{now}:{id(pipe)}": now})
            pipe.zcard(k)
            pipe.expire(k, window + 1)
            _, _, count, _ = pipe.execute()
            return (count <= limit), window
        except Exception:  # noqa: BLE001
            pass
    with _lock:
        dq = _mem[key]
        while dq and dq[0] <= now - window:
            dq.popleft()
        if len(dq) >= limit:
            return False, int(window - (now - dq[0])) + 1
        dq.append(now)
        return True, 0
