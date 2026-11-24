"""Replicate genel video adaptörü. Model `REPLICATE_VIDEO_MODEL=owner/name` ile seçilir ve girdi alanları
prompt / image / duration / aspect_ratio adlarını kabul etmelidir (model başına değişir — kullanıcı doğrular)."""
from __future__ import annotations

from ...core.config import get_settings
from .. import http as H
from ..base import CallContext, Provider, ProviderError, ProviderResult, VideoRequest
from ..pricing import video_cost
from ..router import register
from .common import data_uri, describe

BASE = "https://api.replicate.com/v1"


class ReplicateVideo(Provider):
    name = "replicate"
    kind = "video"
    cred_name = "replicate"
    price_tier = 2
    label = "Replicate"

    def is_configured(self, ctx: CallContext) -> bool:
        return bool(get_settings().replicate_video_model) and ctx.creds.has("replicate")

    def estimate(self, req: VideoRequest) -> float:
        return video_cost("replicate", get_settings().replicate_video_model, req.duration)[0]

    def execute(self, ctx: CallContext, req: VideoRequest) -> ProviderResult:
        model = get_settings().replicate_video_model
        headers = {"Authorization": f"Bearer {ctx.creds.get('replicate')}", "Prefer": "wait=30"}
        inp: dict = {"prompt": req.prompt[:2000], "duration": int(round(req.duration)), "aspect_ratio": req.aspect_ratio}
        if req.image_path:
            inp["image"] = data_uri(req.image_path)
        with H.client(90) as c:
            pred = H.request(c, "POST", f"{BASE}/models/{model}/predictions", self.name, headers=headers,
                             json={"input": inp}).json()
            get_url = (pred.get("urls") or {}).get("get") or f"{BASE}/predictions/{pred.get('id')}"
            h2 = {"Authorization": headers["Authorization"]}

            def check():
                cur = H.request(c, "GET", get_url, self.name, headers=h2).json()
                st = cur.get("status")
                if st == "succeeded":
                    return True, cur
                if st in ("failed", "canceled"):
                    raise ProviderError(f"replicate: tahmin {st}: {str(cur.get('error'))[:200]}", "permanent")
                return False, cur

            done = H.poll(ctx, check, interval=4, timeout=1200, what="replicate tahmini", backoff=1.2, max_interval=15)
            outv = done.get("output")
            url = outv if isinstance(outv, str) else (outv[0] if isinstance(outv, list) and outv else None)
            if not url:
                raise ProviderError("replicate: çıktı yok", "permanent")
            out = ctx.sub(f"vid_{req.scene_idx}_replicate.mp4")
            H.download(c, url, out, self.name, headers=h2)
        cost, meta = video_cost("replicate", model, req.duration)
        meta.update(describe(out))
        meta.update(model=model, origin="ai_video", predict_time=(done.get("metrics") or {}).get("predict_time"))
        return ProviderResult(path=out, cost_usd=cost, units=req.duration, unit_name="sec", meta=meta, model=model)


register(ReplicateVideo())
