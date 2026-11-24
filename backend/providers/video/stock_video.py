"""Stok video: Pexels (/v1/videos/search) ve Pixabay (/api/videos/). Lisans bilgisi varlığa yazılır (QC telif listesi)."""
from __future__ import annotations

import re

from .. import http as H
from ..base import CallContext, Provider, ProviderError, ProviderResult, VideoRequest
from ..router import register
from .common import describe


_STOP = {"the", "and", "with", "style", "cinematic", "shot", "scene", "detailed", "text", "no", "of", "in", "a", "an", "for", "camera", "slow", "push",
         "pull", "pan", "track", "tracking", "lighting", "soft", "light", "composition", "centered", "vertical", "frame", "wide", "close", "closeup",
         "dramatic", "high", "detail", "real", "people", "likeness", "watermark", "logos", "motion", "dolly"}

# Kategori -> İngilizce stok arama ifadeleri (LLM yoksa/başarısızsa sahneye göre döndürülür; Türkçe konu sözcükleri stokta sonuç vermez)
CATEGORY_QUERIES = {
    "Bilim": ["science laboratory", "space galaxy stars", "planet earth from space", "microscope cells", "telescope night sky", "chemistry experiment", "dna science"],
    "Teknoloji": ["technology futuristic", "circuit board electronics", "smartphone technology", "data center servers", "coding programming screen", "robot technology", "city lights night"],
    "Yapay Zekâ": ["artificial intelligence", "robot technology", "neural network abstract", "futuristic digital", "data visualization", "computer code screen", "hologram technology"],
    "Oyun": ["video game controller", "gaming setup neon", "esports arena", "arcade retro game", "neon city night", "virtual reality gaming", "game console"],
    "GTA 6": ["city skyline night", "sports car driving city", "neon city night", "beach sunset palm trees", "helicopter city aerial", "street traffic night", "video game controller"],
    "Otomobil": ["sports car driving", "car engine", "highway driving", "luxury car", "car racing", "road trip car", "city traffic night"],
    "Tarih": ["ancient ruins", "old map history", "castle medieval", "ancient architecture", "museum artifacts", "historic city old", "stone ruins sunset"],
    "Bilgi": ["library books", "world map globe", "light bulb idea", "city time lapse", "nature landscape", "abstract background", "notebook study"],
    "Eğlence": ["party celebration", "concert lights", "friends laughing", "confetti celebration", "city night lights", "dance crowd", "cinema popcorn"],
    "Finans": ["stock market chart", "business city skyline", "money coins", "office business meeting", "financial graph", "city skyscrapers", "calculator desk"],
    "Seyahat": ["travel landscape drone", "beach tropical", "mountain landscape", "city aerial travel", "airplane window clouds", "old town street", "sunset ocean"],
    "Eğitim": ["classroom students", "studying books", "university campus", "writing notebook", "library books", "teacher blackboard", "light bulb idea"],
    "Hikâye": ["foggy forest", "dark mysterious night", "moody cinematic landscape", "old house mystery", "stormy clouds", "candle light dark", "lonely road sunset"],
    "Belgesel": ["nature wildlife", "mountain river", "forest aerial", "ocean waves", "desert landscape", "clouds time lapse", "waterfall nature"],
}
GENERIC_QUERIES = ["abstract background", "city time lapse", "clouds time lapse", "nature landscape", "light particles abstract"]


def _query(prompt: str) -> str:
    """İstemden yalnızca İngilizce, anlamlı sözcükleri al (Türkçe sözcükler stok aramada sonuç vermez)."""
    words = re.findall(r"[A-Za-z]{3,}", prompt)
    return " ".join([w for w in words if w.lower() not in _STOP][:4])


def candidate_queries(req: VideoRequest) -> list[str]:
    qs: list[str] = []
    if req.stock_query.strip():
        qs.append(req.stock_query.strip()[:80])
    q = _query(req.prompt)
    if q:
        qs.append(q)
    cat = CATEGORY_QUERIES.get(req.category, [])
    if cat:
        qs.append(cat[req.scene_idx % len(cat)])
        qs.append(cat[(req.scene_idx + 3) % len(cat)])
    qs.append(GENERIC_QUERIES[req.scene_idx % len(GENERIC_QUERIES)])
    seen, out = set(), []
    for x in qs:
        if x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    return out[:4]


class StockVideo(Provider):
    name = "stock"
    kind = "video"
    is_ai = False
    price_tier = 0
    label = "Stok video (Pexels/Pixabay)"

    def is_configured(self, ctx: CallContext) -> bool:
        return ctx.creds.has("pexels") or ctx.creds.has("pixabay")

    def execute(self, ctx: CallContext, req: VideoRequest) -> ProviderResult:
        errors = []
        with H.client(60) as c:
            for q in candidate_queries(req):  # ilk sonuç veren arama kullanılır
                for name, fn in (("pexels", self._pexels), ("pixabay", self._pixabay)):
                    if not ctx.creds.has(name):
                        continue
                    try:
                        res = fn(ctx, c, req, q)
                        res.meta["stock_query_used"] = q
                        return res
                    except ProviderError as e:
                        if e.kind in ("auth", "rate_limit"):
                            errors.append(str(e))
                            continue
                        errors.append(f"'{q}': {str(e)[:60]}")
        raise ProviderError("stok: sonuç bulunamadı — " + "; ".join(errors[-4:]), "permanent")

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
