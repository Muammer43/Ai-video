"""fal.ai metinden/görselden video. Şema yalnızca Kling ailesi için doğrulandı (prompt, start_image_url, duration, generate_audio)."""
from __future__ import annotations

from ...core.config import get_settings
from .. import http as H
from ..base import CallContext, Provider, ProviderError, ProviderResult, VideoRequest
from ..fal_client import find_url, run_queue
from ..pricing import video_cost
from ..router import register
from .common import data_uri, describe


class FalVideo(Provider):
    name = "fal"
    kind = "video"
    cred_name = "fal"
    price_tier = 2
    label = "fal.ai (Kling vb.)"

    def _model(self, req: VideoRequest) -> str:
        s = get_settings()
        return s.fal_i2v_model if req.image_path else s.fal_t2v_model

    def _secs(self, req: VideoRequest) -> int:
        return int(min(max(round(req.duration), 3), 15))

    def estimate(self, req: VideoRequest) -> float:
        return video_cost("fal", self._model(req), self._secs(req))[0]

    def execute(self, ctx: CallContext, req: VideoRequest) -> ProviderResult:
        model, secs = self._model(req), self._secs(req)
        payload: dict = {"prompt": req.prompt[:2400], "duration": str(secs), "generate_audio": False}
        if req.image_path:
            payload["start_image_url"] = data_uri(req.image_path)
        else:
            payload["aspect_ratio"] = req.aspect_ratio
        res = run_queue(ctx, model, payload, timeout=1200, interval=5)
        url = find_url(res, "video.url", "videos.0.url", "output.url")
        if not url:
            raise ProviderError("fal video: çıktı URL'si yok", "permanent")
        out = ctx.sub(f"vid_{req.scene_idx}_fal.mp4")
        with H.client(300) as c:
            H.download(c, url, out, "fal")
        cost, meta = video_cost("fal", model, secs)
        meta.update(describe(out))
        meta.update(model=model, origin="ai_video")
        return ProviderResult(path=out, cost_usd=cost, units=secs, unit_name="sec", meta=meta, model=model)


register(FalVideo())
