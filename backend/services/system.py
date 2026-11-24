from __future__ import annotations

import shutil
import subprocess
import time

from sqlalchemy import text

from ..core.config import get_settings
from ..database.session import SessionLocal

_cache: dict = {"t": 0, "v": None}


def status() -> dict:
    s = get_settings()
    if _cache["v"] and time.time() - _cache["t"] < 8:
        return _cache["v"]
    out: dict = {"version": s.app_version, "env": s.env, "queue_mode": "eager(thread)" if s.celery_eager else "celery+redis"}
    try:
        with SessionLocal() as db:
            db.execute(text("select 1"))
        out["database"] = {"ok": True, "kind": s.database_url.split(":")[0].split("+")[0]}
    except Exception as e:  # noqa: BLE001
        out["database"] = {"ok": False, "error": type(e).__name__}
    if s.celery_eager:
        out["redis"] = {"ok": None, "note": "eager modda Redis kullanılmıyor"}
        out["workers"] = {"ok": None, "online": 0, "note": "eager mod"}
    else:
        try:
            import redis
            r = redis.Redis.from_url(s.redis_url, socket_connect_timeout=1, socket_timeout=1)
            r.ping()
            out["redis"] = {"ok": True, "queues": {q: r.llen(q) for q in ("default", "render")}}
        except Exception as e:  # noqa: BLE001
            out["redis"] = {"ok": False, "error": type(e).__name__}
        try:
            from ..workers.celery_app import celery
            ping = celery.control.inspect(timeout=1.0).ping() or {}
            out["workers"] = {"ok": bool(ping), "online": len(ping), "names": sorted(ping)[:5]}
        except Exception as e:  # noqa: BLE001
            out["workers"] = {"ok": False, "online": 0, "error": type(e).__name__}
    try:
        v = subprocess.run([s.ffmpeg_bin, "-version"], capture_output=True, text=True, timeout=5).stdout.splitlines()[0]
        out["ffmpeg"] = {"ok": True, "version": v[:60]}
    except Exception as e:  # noqa: BLE001
        out["ffmpeg"] = {"ok": False, "error": type(e).__name__}
    try:
        du = shutil.disk_usage(s.work_dir if s.work_dir and shutil.os.path.exists(s.work_dir) else ".")
        out["disk"] = {"free_gb": round(du.free / 1e9, 1), "total_gb": round(du.total / 1e9, 1)}
    except Exception:  # noqa: BLE001
        pass
    out["storage"] = {"backend": s.storage_backend}
    out["ok"] = bool(out["database"]["ok"] and out["ffmpeg"]["ok"] and (out["redis"]["ok"] in (True, None)))
    _cache.update(t=time.time(), v=out)
    return out
