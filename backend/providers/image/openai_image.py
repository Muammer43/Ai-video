from __future__ import annotations

import base64

from ...core.config import get_settings
from .. import http as H
from ..base import CallContext, ImageRequest, Provider, ProviderError, ProviderResult
from ..pricing import image_cost
from ..router import register

SIZES = {"9:16": "1024x1536", "16:9": "1536x1024", "1:1": "1024x1024"}
QUALITY = {"draft": "low", "standard": "medium", "premium": "high"}


class OpenAIImage(Provider):
    name = "openai"
    kind = "image"
    cred_name = "openai"
    price_tier = 1
    label = "OpenAI Images"

    def estimate(self, req: ImageRequest) -> float:
        return image_cost("openai", get_settings().openai_image_model, 1.5)[0]

    def execute(self, ctx: CallContext, req: ImageRequest) -> ProviderResult:
        model = get_settings().openai_image_model  # gpt-image-1 kapatıldı; varsayılan gpt-image-2
        body = {"model": model, "prompt": req.prompt[:4000], "n": 1, "size": SIZES.get(req.aspect_ratio, "1024x1536"),
                "quality": QUALITY.get(req.quality, "medium")}
        with H.client(180) as c:
            r = H.request(c, "POST", "https://api.openai.com/v1/images/generations", self.name,
                          headers={"Authorization": f"Bearer {ctx.creds.get('openai')}"}, json=body)
        d = r.json()
        try:
            b64 = d["data"][0]["b64_json"]
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError("openai image: beklenmeyen yanıt", "permanent") from e
        out = ctx.sub(f"img_{abs(hash(req.prompt)) % 10**8}.png")
        out.write_bytes(base64.b64decode(b64))
        cost, meta = image_cost("openai", model, 1.5)
        return ProviderResult(path=out, cost_usd=cost, units=1, unit_name="image",
                              meta={"model": model, "origin": "ai_image", "resolution": body["size"], **meta}, model=model)


register(OpenAIImage())
