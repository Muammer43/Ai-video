"""Runway API: POST /v1/image_to_video | /v1/text_to_video, GET /v1/tasks/{id} (X-Runway-Version zorunlu)."""
from __future__ import annotations

from ...core.config import get_settings
from .. import http as H
from ..base import CallContext, Provider, ProviderError, ProviderResult, VideoRequest
from ..pricing import video_cost
from ..router import register
from .common import data_uri, describe

BASE = "https://api.dev.runwayml.com"
RATIOS = {"9:16": "720:1280", "16:9": "1280:720"}
T2V_MODEL = "gen4.5"


class RunwayVideo(Provider):
    name = "runway"
    kind = "video"
    cred_name = "runway"
    price_tier = 3
    label = "Runway"

    def _model(self, req: VideoRequest) -> str:
        return get_settings().runway_model if req.image_path else T2V_MODEL

    def _secs(self, req: VideoRequest) -> int:
        return int(min(max(round(req.duration), 2), 10))

    def estimate(self, req: VideoRequest) -> float:
        return video_cost("runway", self._model(req), self._secs(req))[0]

    def execute(self, ctx: CallContext, req: VideoRequest) -> ProviderResult:
        if req.aspect_ratio not in RATIOS:
            raise ProviderError("runway: 1:1 biçimi bu adaptörde desteklenmiyor", "permanent")
        s = get_settings()
        model, secs = self._model(req), self._secs(req)
        headers = {"Authorization": f"Bearer {ctx.creds.get('runway')}", "X-Runway-Version": s.runway_api_version}
        body: dict = {"model": model, "promptText": req.prompt[:1000], "ratio": RATIOS[req.aspect_ratio], "duration": secs}
        if req.seed is not None:
            body["seed"] = req.seed % 4294967295
        path = "/v1/text_to_video"
        if req.image_path:
            path = "/v1/image_to_video"
            body["promptImage"] = data_uri(req.image_path)
        with H.client(60) as c:
            created = H.request(c, "POST", BASE + path, self.name, headers=headers, json=body).json()
            tid = created.get("id")
            if not tid:
                raise ProviderError("runway: görev kimliği alınamadı", "permanent")
            est_credits = (created.get("estimatedCost") or {}).get("credits")

            def check():
                t = H.request(c, "GET", f"{BASE}/v1/tasks/{tid}", self.name, headers=headers).json()
                st = t.get("status")
                if st == "SUCCEEDED":
                    return True, t
                if st in ("FAILED", "CANCELLED"):
                    raise ProviderError(f"runway: görev {st}: {t.get('failure', '')[:200]}", "permanent")
                return False, t  # PENDING | THROTTLED | RUNNING

            task = H.poll(ctx, check, interval=6, timeout=1200, what="runway görevi", backoff=1.1, max_interval=15)
            outs = task.get("output") or []
            if not outs:
                raise ProviderError("runway: çıktı yok", "permanent")
            out = ctx.sub(f"vid_{req.scene_idx}_runway.mp4")
            H.download(c, outs[0], out, self.name)  # çıktı URL'leri 24–48 saatte geçerliliğini yitirir; hemen indirilir
        cost, meta = video_cost("runway", model, secs)
        actual = (task.get("cost") or {}).get("credits")
        credits = actual if actual is not None else est_credits
        reported = credits is not None
        if reported:
            cost = float(credits) * 0.01  # 1 kredi = 0.01 USD (Runway fiyat sayfası, 2026-11-24)
        meta.update(describe(out))
        meta.update(model=model, origin="ai_video", credits=credits)
        return ProviderResult(path=out, cost_usd=cost, cost_estimated=not (actual is not None), units=secs, unit_name="sec",
                              meta=meta, model=model)


register(RunwayVideo())
