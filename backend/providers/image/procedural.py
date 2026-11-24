"""ÇEVRİMDIŞI yer tutucu görsel (FFmpeg gradyanı). Yapay zekâ görseli DEĞİLDİR; QC bunu işaretler."""
from __future__ import annotations

import hashlib

from ...editor import ffmpeg as ff
from ..base import CallContext, ImageRequest, Provider, ProviderResult
from ..router import register

PALETTES = [("0x1b2a49", "0x7b2cbf"), ("0x0f2027", "0x2c5364"), ("0x41295a", "0x2f0743"), ("0x134e5e", "0x71b280"),
            ("0x3a1c71", "0xd76d77"), ("0x232526", "0x414345")]


class ProceduralImage(Provider):
    name = "procedural"
    kind = "image"
    is_ai = False
    offline = True
    price_tier = 0
    label = "Yerel gradyan (AI değil)"

    def execute(self, ctx: CallContext, req: ImageRequest) -> ProviderResult:
        w, h = {"9:16": (720, 1280), "16:9": (1280, 720), "1:1": (720, 720)}.get(req.aspect_ratio, (720, 1280))
        hv = int(hashlib.sha256(req.prompt.encode()).hexdigest(), 16)
        c0, c1 = PALETTES[hv % len(PALETTES)]
        out = ctx.sub(f"proc_{hv % 10**8}.png")
        ff.run(["-f", "lavfi", "-i", f"gradients=s={w}x{h}:c0={c0}:c1={c1}:x0=0:y0=0:x1={w}:y1={h}:d=1:speed=0.01",
                "-frames:v", "1", str(out)], timeout=60)
        return ProviderResult(path=out, cost_usd=0.0, units=1, unit_name="image", meta={"origin": "procedural", "price_verified": True})


register(ProceduralImage())
