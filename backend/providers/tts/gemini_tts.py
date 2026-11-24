"""Gemini TTS (Interactions API — dokümandaki biçim, 2026-11-24). Ücretsiz katmanda 'free of charge' yazıyor; limitler ve ticari kullanım dokümanda belirtilmemiş,
ücretsiz katmanda içerik Google tarafından ürün geliştirmede kullanılabilir. Türkçe destekli (dil otomatik algılanır). Canlı çağrı bu ortamda DOĞRULANMADI (mock testli)."""
from __future__ import annotations

import base64
import hashlib

from ...core.config import get_settings
from ...editor import ffmpeg as ff
from .. import http as H
from ..base import CallContext, Provider, ProviderError, ProviderResult, TTSRequest
from ..router import register

URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
# Dokümanda ses cinsiyeti belirtilmemiş; yaygın kullanıma göre varsayılan eşleme (kullanıcı voice.gemini_voice ile değiştirebilir)
FEMALE = ["Kore", "Aoede", "Leda"]
MALE = ["Puck", "Charon", "Orus"]
STYLE = {"neutral": "", "excited": "excited and energetic", "calm": "calm and soft", "serious": "serious and authoritative",
         "warm": "warm and friendly", "dramatic": "dramatic, like a documentary narrator"}


def _find_audio(node):  # noqa: ANN001
    """Yanıtta (steps[].content[]) base64 ses verisini bul."""
    if isinstance(node, dict):
        if isinstance(node.get("data"), str) and len(node["data"]) > 200 and (node.get("type") in (None, "audio") or "audio" in str(node.get("mime_type", node.get("mimeType", "")))):
            return node["data"], str(node.get("mime_type") or node.get("mimeType") or "")
        for v in node.values():
            r = _find_audio(v)
            if r:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _find_audio(v)
            if r:
                return r
    return None


class GeminiTTS(Provider):
    name = "gemini"
    kind = "tts"
    cred_name = "gemini"
    price_tier = 1
    label = "Gemini TTS (ücretsiz katman olabilir)"

    def _key(self, ctx: CallContext) -> str:
        k = ctx.creds.get("gemini")
        if k:
            return k
        ex = ctx.creds.extra("compat")  # Özel LLM olarak Gemini uç noktası girildiyse aynı anahtar kullanılır
        return ctx.creds.get("compat") if "generativelanguage.googleapis.com" in str(ex.get("base_url", "")) else ""

    def is_configured(self, ctx: CallContext) -> bool:
        return bool(self._key(ctx))

    def _call(self, c, key: str, model: str, req: TTSRequest, voice: str):  # noqa: ANN001
        text_part: dict = {"type": "text", "text": req.text[:4000]}
        style = STYLE.get(req.voice.get("emotion", "neutral"), "")
        if style:
            text_part["annotations"] = [{"type": "speech_metadata", "style": style}]
        body = {"model": model, "input": [{"type": "user_input", "content": [text_part]}], "response_format": {"type": "audio"},
                "generation_config": {"speech_config": [{"voice": voice}]}}
        return H.request(c, "POST", URL, self.name, headers={"x-goog-api-key": key}, json=body).json()

    def execute(self, ctx: CallContext, req: TTSRequest) -> ProviderResult:
        s = get_settings()
        key = self._key(ctx)
        pool = FEMALE if req.voice.get("gender") == "female" else MALE
        voice = req.voice.get("gemini_voice") or pool[int(req.voice.get("variant", 0)) % len(pool)]
        data = None
        used = s.gemini_tts_model
        with H.client(120) as c:
            last: ProviderError | None = None
            for model in (s.gemini_tts_model, s.gemini_tts_fallback_model):
                try:
                    data = self._call(c, key, model, req, voice)
                    used = model
                    break
                except ProviderError as e:
                    last = e
                    if e.kind in ("auth", "rate_limit", "transient"):
                        raise
            if data is None:
                raise last or ProviderError("gemini tts: yanıt yok", "permanent")
        found = _find_audio(data)
        if not found:
            raise ProviderError("gemini tts: yanıtta ses verisi yok (biçim değişmiş olabilir)", "permanent")
        raw = base64.b64decode(found[0])
        h = hashlib.sha1(req.text.encode()).hexdigest()[:10]
        if raw[:4] == b"RIFF":
            src = ctx.sub(f"gem_{h}.wav")
            src.write_bytes(raw)
            args = ["-i", str(src)]
        else:  # başsız ham PCM (audio/l16): 24 kHz, mono, 16-bit LE
            src = ctx.sub(f"gem_{h}.pcm")
            src.write_bytes(raw)
            args = ["-f", "s16le", "-ar", "24000", "-ac", "1", "-i", str(src)]
        out = ctx.sub(f"tts_{h}.wav")
        speed = float(req.voice.get("speed", 1.0))
        af = ["highpass=f=60"] + ([f"atempo={min(max(speed, 0.5), 2.0):.3f}"] if abs(speed - 1.0) > 0.03 else [])
        ff.run([*args, "-ar", "44100", "-ac", "1", "-af", ",".join(af), str(out)], timeout=60)
        dur = ff.audio_duration(out)
        return ProviderResult(path=out, cost_usd=0.0, cost_estimated=True, units=len(req.text), unit_name="chars", model=used,
                              meta={"model": used, "voice": voice, "duration": round(dur, 2), "price_verified": False,
                                    "price_source": "Gemini ücretsiz katmanda 'free of charge' (doküman); ücretli katmanda fiyat doğrulanmadı — 0 varsayıldı"})


register(GeminiTTS())
