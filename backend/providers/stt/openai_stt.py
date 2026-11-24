from __future__ import annotations

from ...core.config import get_settings
from .. import http as H
from ..base import CallContext, Provider, ProviderError, ProviderResult, STTRequest
from ..pricing import stt_cost
from ..router import register


class OpenAISTT(Provider):
    name = "openai"
    kind = "stt"
    cred_name = "openai"
    price_tier = 1
    label = "OpenAI Whisper (kelime zamanlı)"

    def estimate(self, req: STTRequest) -> float:
        return stt_cost("openai", get_settings().openai_stt_model, req.duration or 30)[0]

    def execute(self, ctx: CallContext, req: STTRequest) -> ProviderResult:
        model = get_settings().openai_stt_model
        with open(req.audio_path, "rb") as f, H.client(180) as c:
            r = H.request(c, "POST", "https://api.openai.com/v1/audio/transcriptions", self.name,
                          headers={"Authorization": f"Bearer {ctx.creds.get('openai')}"},
                          data={"model": model, "response_format": "verbose_json", "timestamp_granularities[]": "word",
                                "language": req.language},
                          files={"file": (req.audio_path.name, f, "application/octet-stream")})
        d = r.json()
        words = d.get("words")
        if not isinstance(words, list):
            raise ProviderError("openai stt: kelime zamanları yok", "permanent")
        dur = float(d.get("duration") or req.duration or 0)
        cost, meta = stt_cost("openai", model, dur)
        meta.update(model=model, duration=dur)
        return ProviderResult(data={"words": [{"word": w["word"], "start": w["start"], "end": w["end"]} for w in words],
                                    "estimated": False, "text": d.get("text", "")},
                              cost_usd=cost, units=dur, unit_name="sec", meta=meta, model=model)


register(OpenAISTT())
