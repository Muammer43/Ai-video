"""ÇEVRİMDIŞI ŞABLON — yapay zekâ DEĞİLDİR. API anahtarı olmadan hattı test etmek için deterministik içerik üretir.
Bu sağlayıcıyla üretilen senaryolar `is_ai=False` etiketlenir ve otomatik yayına alınmaz."""
from __future__ import annotations

import json

from ..base import CallContext, LLMRequest, Provider, ProviderResult
from ..router import register


class TemplateLLM(Provider):
    name = "template"
    kind = "llm"
    is_ai = False
    offline = True
    price_tier = 0
    label = "Yerel şablon (AI değil)"

    def execute(self, ctx: CallContext, req: LLMRequest) -> ProviderResult:
        p = req.params
        if req.task == "ideas":
            cat, n = p.get("category", "Genel"), int(p.get("count", 5))
            trends = p.get("trends") or []
            base = [t["title"] for t in trends[:n]] or [f"{cat} dünyasında az bilinen {i + 3} gerçek" for i in range(n)]
            ideas = [{"title": t, "angle": "Kısa, merak uyandıran, doğrulanabilir bilgilere dayalı anlatım",
                      "audience": f"{cat} meraklıları", "format": "talking-points", "score": 55 - i,
                      "reason": "şablon (AI değerlendirmesi değil)"} for i, t in enumerate(base[:n])]
            return ProviderResult(data=json.dumps({"ideas": ideas}, ensure_ascii=False), meta={"template": True})
        if req.task == "script":
            topic, style, dur = p.get("topic", "Konu"), p.get("style", "cinematic"), int(p.get("duration", 30))
            n = max(3, min(7, dur // 6))
            scenes = [{"narration": f"{topic} hakkında {i + 1}. nokta: kısa ve net bir açıklama.",
                       "visual_prompt": f"{topic}, scene {i + 1}, {style} style, detailed, no text",
                       "camera": "slow push-in", "lighting": "soft cinematic", "composition": "centered subject",
                       "transition": "fade", "on_screen_text": ""} for i in range(n)]
            scenes[0]["narration"] = f"{topic} konusunda çoğu kişinin bilmediği bir şey var."
            script = {"title": topic[:90], "hook": scenes[0]["narration"], "scenes": scenes, "cta": "Sen ne düşünüyorsun? Yorumlara yaz.",
                      "description": f"{topic} hakkında kısa video.", "hashtags": ["#shorts", "#keşfet"],
                      "facts_to_verify": [], "claims_risk": "low", "sources": []}
            return ProviderResult(data=json.dumps(script, ensure_ascii=False), meta={"template": True})
        return ProviderResult(data=json.dumps({"ok": True, "flagged": False}), meta={"template": True})


register(TemplateLLM())
