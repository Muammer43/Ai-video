"""Google Gemini metin modeli — OpenAI uyumlu uç üzerinden (tek anahtar). Ücretsiz katmanda içerik Google tarafından ürün geliştirmede kullanılabilir.
Model adı GEMINI_TEXT_MODEL ile ayarlanır; bulunamazsa models.list ile uygun bir 'flash' modeli otomatik seçilir."""
from __future__ import annotations

import re

from ...core.config import get_settings
from .. import http as H
from ..base import CallContext, LLMRequest, ProviderError, ProviderResult
from ..router import register
from .compat_llm import CompatLLM

BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
_discovered: dict[str, str] = {}


def discover_model(key: str) -> str | None:
    """models.list: generateContent destekleyen, TTS/görsel/canlı/embedding olmayan en yeni 'flash' modeli."""
    with H.client(30) as c:
        r = H.request(c, "GET", "https://generativelanguage.googleapis.com/v1beta/models", "gemini", headers={"x-goog-api-key": key},
                      params={"pageSize": 200}).json()
    cands = []
    for m in r.get("models", []):
        name = m.get("name", "").removeprefix("models/")
        if "generateContent" not in (m.get("supportedGenerationMethods") or []):
            continue
        if "flash" not in name or re.search(r"tts|image|live|embed|audio|lite|vision|thinking-exp|preview-\d", name):
            continue
        cands.append(name)
    return sorted(cands)[-1] if cands else None


class GeminiLLM(CompatLLM):
    name = "gemini"
    cred_name = "gemini"
    price_tier = 1
    label = "Google Gemini (ücretsiz katman olabilir)"

    def is_configured(self, ctx: CallContext) -> bool:
        return ctx.creds.has("gemini")

    def execute(self, ctx: CallContext, req: LLMRequest) -> ProviderResult:
        key = ctx.creds.get("gemini")
        model = _discovered.get(key) or get_settings().gemini_text_model
        shim = type("Creds", (), {})()
        for attempt in (0, 1):
            ex = {"base_url": BASE, "model": model, "in_per_m": 0, "out_per_m": 0}
            ctx2 = CallContext(user_id=ctx.user_id, project_id=ctx.project_id, work_dir=ctx.work_dir, settings=ctx.settings,
                               creds=_FixedCreds(key, ex))
            try:
                res = CompatLLM.execute(self, ctx2, req)
                res.meta["price_source"] = "Gemini ücretsiz katman olabilir (fiyat doğrulanmadı; 0 varsayıldı)"
                return res
            except ProviderError as e:
                if attempt == 0 and e.kind == "permanent" and ("404" in str(e) or "400" in str(e)):
                    found = discover_model(key)
                    if found and found != model:
                        _discovered[key] = model = found
                        continue
                raise
        raise ProviderError("gemini: model bulunamadı", "permanent")


class _FixedCreds:
    def __init__(self, key: str, extra: dict):
        self._key, self._extra = key, extra

    def get(self, provider: str) -> str:
        return self._key

    def has(self, provider: str) -> bool:
        return True

    def extra(self, provider: str) -> dict:
        return self._extra


register(GeminiLLM())
