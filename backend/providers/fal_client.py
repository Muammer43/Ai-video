"""fal.ai kuyruk API'si (queue.fal.run). Durum/sonuç URL'leri gönderim yanıtından alınır."""
from __future__ import annotations

from . import http as H
from .base import CallContext, ProviderError


def run_queue(ctx: CallContext, model_id: str, payload: dict, *, timeout: float = 900, interval: float = 4.0) -> dict:
    key = ctx.creds.get("fal")
    headers = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
    with H.client(60) as c:
        r = H.request(c, "POST", f"https://queue.fal.run/{model_id}", "fal", headers=headers, json=payload)
        sub = r.json()
        rid = sub.get("request_id")
        if not rid:
            if "video" in sub or "images" in sub:  # senkron yanıt
                return sub
            raise ProviderError("fal: request_id alınamadı", "permanent")
        status_url = sub.get("status_url") or f"https://queue.fal.run/{model_id}/requests/{rid}/status"
        result_url = sub.get("response_url") or f"https://queue.fal.run/{model_id}/requests/{rid}"

        def check():
            s = H.request(c, "GET", status_url, "fal", headers=headers).json()
            st = (s.get("status") or "").upper()
            if st == "COMPLETED":
                if s.get("error"):
                    raise ProviderError(f"fal: üretim hatası: {str(s['error'])[:200]}", "permanent")
                return True, s
            if st in ("FAILED", "ERROR", "CANCELLED"):
                raise ProviderError(f"fal: iş başarısız ({st})", "permanent")
            return False, s

        H.poll(ctx, check, interval=interval, timeout=timeout, what="fal kuyruk", backoff=1.2, max_interval=15)
        res = H.request(c, "GET", result_url, "fal", headers=headers)
        return res.json()


def find_url(d: dict, *paths: str) -> str | None:
    for p in paths:
        cur = d
        ok = True
        for part in p.split("."):
            if isinstance(cur, list):
                try:
                    cur = cur[int(part)]
                except (ValueError, IndexError):
                    ok = False
                    break
            elif isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and isinstance(cur, str) and cur.startswith("http"):
            return cur
    return None
