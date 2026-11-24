from __future__ import annotations

from ...core.config import get_settings
from ...editor import ffmpeg as ff
from .. import http as H
from ..base import CallContext, Provider, ProviderResult, TTSRequest
from ..pricing import tts_cost
from ..router import register

DEFAULT_FEMALE = "21m00Tcm4TlvDq8ikWAM"
DEFAULT_MALE = "pNInz6obpgDQGcFmaJgB"
EMOTION = {"neutral": (0.5, 0.0), "excited": (0.3, 0.5), "calm": (0.7, 0.0), "serious": (0.6, 0.2),
           "warm": (0.5, 0.3), "dramatic": (0.35, 0.6)}  # (stability, style)


class ElevenLabsTTS(Provider):
    name = "elevenlabs"
    kind = "tts"
    cred_name = "elevenlabs"
    price_tier = 2
    label = "ElevenLabs"

    def estimate(self, req: TTSRequest) -> float:
        return tts_cost("elevenlabs", get_settings().elevenlabs_model, len(req.text))[0]

    def execute(self, ctx: CallContext, req: TTSRequest) -> ProviderResult:
        model = get_settings().elevenlabs_model
        vid = req.voice.get("voice_id") or (DEFAULT_FEMALE if req.voice.get("gender") == "female" else DEFAULT_MALE)
        stab, style = EMOTION.get(req.voice.get("emotion", "neutral"), (0.5, 0.0))
        body = {"text": req.text[:9000], "model_id": model,
                "voice_settings": {"stability": stab, "similarity_boost": 0.75, "style": style,
                                   "speed": min(max(float(req.voice.get("speed", 1.0)), 0.7), 1.2)}}
        with H.client(120) as c:
            r = H.request(c, "POST", f"https://api.elevenlabs.io/v1/text-to-speech/{vid}", self.name,
                          headers={"xi-api-key": ctx.creds.get("elevenlabs"), "Accept": "audio/mpeg"},
                          params={"output_format": "mp3_44100_128"}, json=body)
        out = ctx.sub(f"tts_{abs(hash(req.text)) % 10**8}.mp3")
        out.write_bytes(r.content)
        dur = ff.audio_duration(out)
        cost, meta = tts_cost("elevenlabs", model, len(req.text))
        meta.update(model=model, duration=round(dur, 2), voice=vid)
        return ProviderResult(path=out, cost_usd=cost, units=len(req.text), unit_name="chars", meta=meta, model=model)


register(ElevenLabsTTS())
