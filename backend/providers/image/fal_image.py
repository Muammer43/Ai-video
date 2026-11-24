from __future__ import annotations

from ...core.config import get_settings
from .. import http as H
from ..base import CallContext, ImageRequest, Provider, ProviderError, ProviderResult
from ..fal_client import find_url, run_queue
from ..pricing import image_cost
from ..router import register

IMG_SIZE = {"9:16": "portrait_16_9", "16:9": "landscape_16_9", "1:1": "square_hd"}
MP = {"9:16": 1.0, "16:9": 1.0, "1:1": 1.0}


class FalImage(Provider):
    name = "fal"
    kind = "image"
    cred_name = "fal"
    price_tier = 2
    label = "fal.ai (Flux)"

    def estimate(self, req: ImageRequest) -> float:
        return image_cost("fal", get_settings().fal_image_model, 1.0)[0]

    def execute(self, ctx: CallContext, req: ImageRequest) -> ProviderResult:
        model = get_settings().fal_image_model
        payload = {"prompt": req.prompt[:2000], "image_size": IMG_SIZE.get(req.aspect_ratio, "portrait_16_9"), "num_images": 1}
        if req.seed is not None:
            payload["seed"] = req.seed
        res = run_queue(ctx, model, payload, timeout=300, interval=2)
        url = find_url(res, "images.0.url", "image.url")
        if not url:
            raise ProviderError("fal image: çıktı URL'si yok", "permanent")
        out = ctx.sub(f"img_{abs(hash(req.prompt)) % 10**8}.png")
        with H.client(120) as c:
            H.download(c, url, out, "fal")
        cost, meta = image_cost("fal", model, MP.get(req.aspect_ratio, 1.0))
        return ProviderResult(path=out, cost_usd=cost, units=1, unit_name="image",
                              meta={"model": model, "origin": "ai_image", **meta}, model=model)


register(FalImage())
