from __future__ import annotations

from ...core.config import get_settings
from ...editor import ffmpeg as ff
from .. import http as H
from ..base import CallContext, Provider, ProviderResult, TTSRequest
from ..pricing import tts_cost
from ..router import register

FEMALE = ["coral", "nova", "shimmer", "sage"]
MALE = ["onyx", "echo", "ash", "cedar"]
EMOTION = {"neutral": "", "excited": "Speak with excitement and energy.", "calm": "Speak calmly and softly.",
           "serious": "Speak in a serious, authoritative tone.", "warm": "Speak in a warm, friendly tone.",
           "dramatic": "Speak dramatically, like a documentary narrator."}


def pick_voice(voice: dict) -> str:
    if voice.get("openai_voice"):
        return voice["openai_voice"]
    pool = FEMALE if voice.get("gender") == "female" else MALE
    return pool[int(voice.get("variant", 0)) % len(pool)]


class OpenAITTS(Provider):
    name = "openai"
    kind = "tts"
    cred_name = "openai"
    price_tier = 1
    label = "OpenAI TTS"

    def estimate(self, req: TTSRequest) -> float:
        return tts_cost("openai", get_settings().openai_tts_model, len(req.text))[0]

    def execute(self, ctx: CallContext, req: TTSRequest) -> ProviderResult:
        model = get_settings().openai_tts_model  # tts-1/gpt-4o-mini-tts 2027-01-06'da kapanacak: model adı yapılandırılabilir
        body = {"model": model, "voice": pick_voice(req.voice), "input": req.text[:4000], "response_format": "mp3",
                "speed": min(max(float(req.voice.get("speed", 1.0)), 0.5), 2.0)}
        lang = "Turkish" if req.language == "tr" else "English" if req.language == "en" else req.language
        instr = (EMOTION.get(req.voice.get("emotion", "neutral"), "") + f" Language: {lang}.").strip()
        if model.startswith("gpt-4o"):
            body["instructions"] = instr
        with H.client(120) as c:
            r = H.request(c, "POST", "https://api.openai.com/v1/audio/speech", self.name,
                          headers={"Authorization": f"Bearer {ctx.creds.get('openai')}"}, json=body)
        out = ctx.sub(f"tts_{abs(hash(req.text)) % 10**8}.mp3")
        out.write_bytes(r.content)
        dur = ff.audio_duration(out)
        cost, meta = tts_cost("openai", model, len(req.text))
        meta.update(model=model, duration=round(dur, 2), voice=body["voice"])
        return ProviderResult(path=out, cost_usd=cost, units=len(req.text), unit_name="chars", meta=meta, model=model)


register(OpenAITTS())
