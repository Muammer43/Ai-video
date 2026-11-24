"""Yerel espeak-ng sentezi (çevrimdışı, robotik; üretken AI değildir). Tüketici kalitesinde yayın için uygun DEĞİL."""
from __future__ import annotations

import hashlib
import shutil
import subprocess

from ...editor import ffmpeg as ff
from ..base import CallContext, Provider, ProviderError, ProviderResult, TTSRequest
from ..router import register

LANG = {"tr": "tr", "en": "en-us", "de": "de", "fr": "fr", "es": "es"}


class EspeakTTS(Provider):
    name = "espeak"
    kind = "tts"
    is_ai = False
    offline = True
    price_tier = 0
    label = "espeak-ng yerel (robotik, AI değil)"

    def is_configured(self, ctx: CallContext) -> bool:
        return shutil.which("espeak-ng") is not None

    def execute(self, ctx: CallContext, req: TTSRequest) -> ProviderResult:
        lang = LANG.get(req.language, "en-us")
        variant = "f3" if req.voice.get("gender") == "female" else "m3"
        speed = float(req.voice.get("speed", 1.0))
        wpm = int(min(max(165 * speed, 90), 300))
        pitch = {"excited": 65, "calm": 40, "serious": 35, "dramatic": 38}.get(req.voice.get("emotion", "neutral"), 50)
        h = hashlib.sha1(req.text.encode()).hexdigest()[:10]
        raw = ctx.sub(f"es_{h}.wav")
        p = subprocess.run(["espeak-ng", "-v", f"{lang}+{variant}", "-s", str(wpm), "-p", str(pitch), "-w", str(raw), "--stdin"],
                           input=req.text, capture_output=True, text=True, timeout=120)
        if p.returncode != 0 or not raw.exists():
            raise ProviderError(f"espeak-ng başarısız: {p.stderr[-200:]}", "permanent")
        out = ctx.sub(f"tts_{h}.wav")
        ff.run(["-i", str(raw), "-ar", "44100", "-ac", "1", "-af", "highpass=f=80,volume=1.6", str(out)], timeout=60)
        dur = ff.audio_duration(out)
        return ProviderResult(path=out, cost_usd=0.0, units=len(req.text), unit_name="chars",
                              meta={"duration": round(dur, 2), "voice": f"{lang}+{variant}", "origin": "espeak", "price_verified": True})


register(EspeakTTS())
