"""Konuşma tanıma OLMADAN, bilinen metin + ses süresinden TAHMİNİ kelime zamanlaması. Gerçek ASR değildir; 'estimated' etiketli."""
from __future__ import annotations

import re
import subprocess

from ...editor import ffmpeg as ff
from ..base import CallContext, Provider, ProviderResult, STTRequest
from ..router import register
from .align import tokenize


def speech_bounds(path, total: float) -> tuple[float, float]:  # noqa: ANN001
    """silencedetect ile baş/son sessizliği bul."""
    s = ff.get_settings().ffmpeg_bin
    p = subprocess.run([s, "-hide_banner", "-nostdin", "-i", str(path), "-af", "silencedetect=noise=-38dB:d=0.12", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=60)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", p.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", p.stderr)]
    lead = ends[0] if starts and starts[0] < 0.05 and ends else 0.0
    tail_start = starts[-1] if starts and (len(starts) > len(ends) or (ends and ends[-1] >= total - 0.05)) and starts[-1] > lead else total
    return lead, max(tail_start, lead + 0.2)


class AlignerSTT(Provider):
    name = "aligner"
    kind = "stt"
    is_ai = False
    offline = True
    price_tier = 0
    label = "Tahmini hizalayıcı (ASR değil)"

    def execute(self, ctx: CallContext, req: STTRequest) -> ProviderResult:
        total = req.duration or ff.audio_duration(req.audio_path)
        words = tokenize(req.text_hint)
        lead, end = speech_bounds(req.audio_path, total)
        weights = [max(len(re.sub(r"\W", "", w)), 1) + (3 if w[-1:] in ".!?" else 1 if w[-1:] in ",;:" else 0) for w in words]
        tot = sum(weights) or 1
        t = lead
        out = []
        for w, wg in zip(words, weights):
            d = (end - lead) * wg / tot
            out.append({"word": w, "start": round(t, 3), "end": round(t + d, 3)})
            t += d
        return ProviderResult(data={"words": out, "estimated": True, "text": req.text_hint},
                              meta={"duration": total, "origin": "aligner", "price_verified": True})


register(AlignerSTT())
