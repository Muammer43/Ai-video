from __future__ import annotations

from ...core.config import get_settings
from .. import http as H
from ..base import CallContext, LLMRequest, Provider, ProviderError, ProviderResult
from ..pricing import llm_cost
from ..router import register


class OpenAILLM(Provider):
    name = "openai"
    kind = "llm"
    cred_name = "openai"
    price_tier = 1
    label = "OpenAI Chat Completions"

    def estimate(self, req: LLMRequest) -> float:
        m = get_settings().openai_text_model
        return llm_cost("openai", m, (len(req.system) + len(req.user)) // 3, req.max_tokens // 2)[0]

    def execute(self, ctx: CallContext, req: LLMRequest) -> ProviderResult:
        model = get_settings().openai_text_model
        body = {"model": model, "max_completion_tokens": req.max_tokens,
                "messages": [{"role": "system", "content": req.system}, {"role": "user", "content": req.user}]}
        if req.json_mode:
            body["response_format"] = {"type": "json_object"}
        with H.client(180) as c:
            r = H.request(c, "POST", "https://api.openai.com/v1/chat/completions", self.name,
                          headers={"Authorization": f"Bearer {ctx.creds.get('openai')}"}, json=body)
        d = r.json()
        try:
            text = d["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError("openai: beklenmeyen yanıt biçimi", "permanent") from e
        u = d.get("usage", {})
        cost, meta = llm_cost("openai", model, u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
        return ProviderResult(data=text, cost_usd=cost, units=u.get("total_tokens", 0), unit_name="tokens",
                              meta={"model": model, **meta}, model=model)


register(OpenAILLM())
