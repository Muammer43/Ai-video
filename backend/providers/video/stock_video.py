"""Stok video: Pexels (/v1/videos/search) ve Pixabay (/api/videos/). Lisans bilgisi varlığa yazılır (QC telif listesi)."""
from __future__ import annotations

import re

from .. import http as H
from ..base import CallContext, Provider, ProviderError, ProviderResult, VideoRequest
from ..router import register
from .common import describe


def _query(prompt: str) -> str:
    words = re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü]{3,}", prompt)
    stop = {"the", "and", "with", "style", "cinematic", "shot", "scene", "detailed", "text", "no", "of", "in", "a", "an", "for"}
    return " ".join([w for w in words if w.lower() not in stop][:5]) or "abstract background"


class StockVideo(Provider):
    name = "stock"
    kind = "video"
    is_ai = False
    price_tier = 0
    label = "Stok video (Pexels/Pixabay)"

    def is_configured(self, ctx: CallContext) -> bool:
        return ctx.creds.has("pexels") or ctx.creds.has("pixabay")

    def execute(self, ctx: CallContext, req: VideoRequest) -> ProviderResult:
        q = req.stock_query or _query(req.prompt)
        errors = []
        with H.client(60) as c:
            if ctx.creds.has("pexels"):
                try:
                    return self._pexels(ctx, c, req, q)
                except ProviderError as e:
                    errors.append(str(e))
            if ctx.creds.has("pixabay"):
                try:
                    return self._pixabay(ctx, c, req, q)
                except ProviderError as e:
                    errors.append(str(e))
        raise ProviderError("stok: sonuç bulunamadı — " + "; ".join(errors), "permanent")

    def _pexels(self, ctx, c, req, q):  # noqa: ANN001
        orient = {"9:16": "portrait", "16:9": "landscape", "1:1": "square"}.get(req.aspect_ratio, "portrait")
        r = H.request(c, "GET", "https://api.pexels.com/v1/videos/search", "pexels",
                      headers={"Authorization": ctx.creds.get("pexels")},
                      params={"query": q, "orientation": orient, "size": "medium", "per_page": 15})
        vids = [v for v in r.json().get("videos", []) if v.get("duration", 0) >= min(req.duration, 3)]
        if not vids:
            raise ProviderError("pexels: sonuç yok", "permanent")
        used = set(ctx.settings.get("_used_stock_ids", []))
        v = next((x for x in vids if f"pexels:{x['id']}" not in used), vids[0])
        files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("link")]
        if not files:
            raise ProviderError("pexels: mp4 dosyası yok", "permanent")
        want_h = {"portrait": 1280, "landscape": 720, "square": 720}[orient]
        f = min(files, key=lambda x: abs((x.get("height") or 0) - want_h))
        out = ctx.sub(f"vid_{req.scene_idx}_pexels.mp4")
        H.download(c, f["link"], out, "pexels")
        user = v.get("user", {})
        meta = describe(out)
        meta.update(origin="stock", stock_id=f"pexels:{v['id']}", price_verified=True, price_source="ücretsiz",
                    rate_limit={"remaining": r.headers.get("x-ratelimit-remaining")},
                    license={"type": "Pexels License", "source": "pexels.com", "url": v.get("url", ""),
                             "attribution": f"Video: {user.get('name', '')} / Pexels", "commercial_use": True})
        return ProviderResult(path=out, cost_usd=0.0, cost_estimated=False, units=meta.get("duration", 0), unit_name="sec", meta=meta)

    def _pixabay(self, ctx, c, req, q):  # noqa: ANN001
        r = H.request(c, "GET", "https://pixabay.com/api/videos/", "pixabay",
                      params={"key": ctx.creds.get("pixabay"), "q": q[:100], "per_page": 15, "safesearch": "true"})
        hits = [h for h in r.json().get("hits", []) if h.get("duration", 0) >= min(req.duration, 3)]
        if not hits:
            raise ProviderError("pixabay: sonuç yok", "permanent")
        used = set(ctx.settings.get("_used_stock_ids", []))
        h = next((x for x in hits if f"pixabay:{x['id']}" not in used), hits[0])
        vv = h["videos"]
        pick = next((vv[k] for k in ("medium", "large", "small", "tiny") if vv.get(k, {}).get("url")), None)
        if not pick:
            raise ProviderError("pixabay: dosya yok", "permanent")
        out = ctx.sub(f"vid_{req.scene_idx}_pixabay.mp4")
        H.download(c, pick["url"], out, "pixabay")
        meta = describe(out)
        meta.update(origin="stock", stock_id=f"pixabay:{h['id']}", price_verified=True, price_source="ücretsiz",
                    license={"type": "Pixabay Content License", "source": "pixabay.com", "url": h.get("pageURL", ""),
                             "attribution": f"Video: {h.get('user', '')} / Pixabay", "commercial_use": True})
        return ProviderResult(path=out, cost_usd=0.0, cost_estimated=False, units=meta.get("duration", 0), unit_name="sec", meta=meta)


register(StockVideo())
