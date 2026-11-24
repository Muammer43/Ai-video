"""Duran görselden hareketli klip (zoom/pan). BU BİR AI VİDEO DEĞİLDİR — 'ai_image_motion' veya 'slideshow' etiketiyle raporlanır."""
from __future__ import annotations

import hashlib

from ...editor import ffmpeg as ff
from ..base import CallContext, Provider, ProviderError, ProviderResult, VideoRequest
from ..router import register

MOTIONS = ["zoom_in", "pan_right", "zoom_out", "pan_left", "pan_up"]


def zoompan_expr(motion: str, frames: int) -> tuple[str, str, str]:
    n = max(frames, 2)
    c_x, c_y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if motion == "zoom_out":
        return f"1.22-0.22*on/{n}", c_x, c_y
    if motion == "pan_right":
        return "1.18", f"(iw-iw/zoom)*on/{n}", c_y
    if motion == "pan_left":
        return "1.18", f"(iw-iw/zoom)*(1-on/{n})", c_y
    if motion == "pan_up":
        return "1.18", c_x, f"(ih-ih/zoom)*(1-on/{n})"
    return f"1+0.22*on/{n}", c_x, c_y  # zoom_in


def render_motion(image, out, duration: float, w: int, h: int, motion: str, cancel_check=None) -> None:  # noqa: ANN001
    frames = max(int(round(duration * ff.FPS)), 2)
    z, x, y = zoompan_expr(motion, frames)
    vf = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
          f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={ff.FPS},format=yuv420p")
    ff.run(["-i", str(image), "-vf", vf, "-frames:v", str(frames), "-an", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "20", "-pix_fmt", "yuv420p", str(out)], timeout=300, cancel_check=cancel_check)


class KenBurns(Provider):
    name = "ken_burns"
    kind = "video"
    is_ai = False
    offline = True
    price_tier = 0
    label = "Görselden hareket (AI video değil)"

    def execute(self, ctx: CallContext, req: VideoRequest) -> ProviderResult:
        if not req.image_path:
            raise ProviderError("ken_burns: kaynak görsel gerekli", "permanent")
        w, h = ff.dims(req.aspect_ratio, req.resolution)
        motion = MOTIONS[int(hashlib.md5(req.prompt.encode()).hexdigest(), 16) % len(MOTIONS)]
        out = ctx.sub(f"vid_{req.scene_idx}_kb.mp4")
        render_motion(req.image_path, out, req.duration, w, h, motion, ctx.cancel_check)
        return ProviderResult(path=out, cost_usd=0.0, units=req.duration, unit_name="sec",
                              meta={"origin": "ai_image_motion", "motion": motion, "duration": req.duration,
                                    "resolution": f"{w}x{h}", "price_verified": True})


register(KenBurns())
