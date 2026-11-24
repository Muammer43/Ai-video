from __future__ import annotations

from ...core.config import get_settings
from .. import http as H
from ..base import CallContext, LLMRequest, Provider, ProviderError, ProviderResult
from ..pricing import llm_cost
from ..router import register


class AnthropicLLM(Provider):
    name = "anthropic"
    kind = "llm"
    cred_name = "anthropic"
    price_tier = 2
    label = "Anthropic Messages"

    def estimate(self, req: LLMRequest) -> float:
        m = get_settings().anthropic_text_model
        return llm_cost("anthropic", m, (len(req.system) + len(req.user)) // 3, req.max_tokens // 2)[0]

    def execute(self, ctx: CallContext, req: LLMRequest) -> ProviderResult:
        model = get_settings().anthropic_text_model
        system = req.system + ("\n\nYalnızca geçerli JSON döndür; başka metin ekleme." if req.json_mode else "")
        # Not: yeni API sürümü temperature/top_p/top_k göndermeyi reddeder; bu yüzden gönderilmez.
        body = {"model": model, "max_tokens": req.max_tokens, "system": system,
                "messages": [{"role": "user", "content": req.user}]}
        with H.client(180) as c:
            r = H.request(c, "POST", "https://api.anthropic.com/v1/messages", self.name,
                          headers={"x-api-key": ctx.creds.get("anthropic"), "anthropic-version": "2023-06-01"}, json=body)
        d = r.json()
        try:
            text = "".join(b.get("text", "") for b in d["content"] if b.get("type") == "text")
        except (KeyError, TypeError) as e:
            raise ProviderError("anthropic: beklenmeyen yanıt biçimi", "permanent") from e
        if d.get("stop_reason") == "refusal":
            raise ProviderError("anthropic: model isteği reddetti", "permanent")
        u = d.get("usage", {})
        cost, meta = llm_cost("anthropic", model, u.get("input_tokens", 0), u.get("output_tokens", 0))
        return ProviderResult(data=text, cost_usd=cost, units=u.get("input_tokens", 0) + u.get("output_tokens", 0),
                              unit_name="tokens", meta={"model": model, **meta}, model=model)


register(AnthropicLLM())
