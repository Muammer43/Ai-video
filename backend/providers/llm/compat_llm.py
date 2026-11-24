"""OpenAI uyumlu Chat Completions istemcisi (Gemini OpenAI-uyumlu uç, Groq, OpenRouter, yerel vb.).
Kullanıcı tanımlı base_url + model + anahtar. Fiyat bilinmez: varsayılan 0 USD olarak kaydedilir ve 'fiyat doğrulanmamış' etiketlenir
(isteğe bağlı in_per_m/out_per_m girilebilir)."""
from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from .. import http as H
from ..base import CallContext, LLMRequest, Provider, ProviderError, ProviderResult
from ..router import register


def validate_base_url(url: str) -> str:
    """SSRF önlemi: yalnızca https, genel (özel/loopback/link-local olmayan) ana makine adları."""
    u = urlparse(url.strip())
    if u.scheme != "https" or not u.hostname:
        raise ValueError("Adres https:// ile başlamalı")
    host = u.hostname.lower()
    if host in ("localhost",) or host.endswith((".local", ".internal", ".localhost")) or "." not in host:
        raise ValueError("Yerel/iç ağ adresleri kabul edilmez")
    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            raise ValueError("Özel/iç IP adresleri kabul edilmez")
    except ValueError as e:
        if "kabul edilmez" in str(e):
            raise
    return url.strip().rstrip("/")


class CompatLLM(Provider):
    name = "compat"
    kind = "llm"
    cred_name = "compat"
    price_tier = 1
    label = "OpenAI uyumlu (Gemini/Groq/OpenRouter…)"

    def is_configured(self, ctx: CallContext) -> bool:
        ex = ctx.creds.extra("compat")
        return ctx.creds.has("compat") and bool(ex.get("base_url")) and bool(ex.get("model"))

    def execute(self, ctx: CallContext, req: LLMRequest) -> ProviderResult:
        ex = ctx.creds.extra("compat")
        try:
            base = validate_base_url(ex["base_url"])
        except ValueError as e:
            raise ProviderError(f"compat: geçersiz adres ({e})", "permanent") from e
        model = ex["model"]
        body = {"model": model, "max_tokens": req.max_tokens, "messages": [{"role": "system", "content": req.system}, {"role": "user", "content": req.user}]}
        if req.json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {ctx.creds.get('compat')}"}
        with H.client(180) as c:
            try:
                r = H.request(c, "POST", base + "/chat/completions", self.name, headers=headers, json=body)
            except ProviderError as e:
                if e.kind == "permanent" and req.json_mode:  # bazı sağlayıcılar json_object kipini desteklemez: ek yönergeyle yeniden dene
                    body.pop("response_format", None)
                    body["messages"][0]["content"] += "\n\nYalnızca geçerli JSON döndür; başka metin ekleme."
                    r = H.request(c, "POST", base + "/chat/completions", self.name, headers=headers, json=body)
                else:
                    raise
        d = r.json()
        try:
            text = d["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError("compat: beklenmeyen yanıt biçimi", "permanent") from e
        u = d.get("usage") or {}
        cost = (u.get("prompt_tokens", 0) * float(ex.get("in_per_m", 0)) + u.get("completion_tokens", 0) * float(ex.get("out_per_m", 0))) / 1e6
        return ProviderResult(data=text, cost_usd=cost, units=u.get("total_tokens", 0), unit_name="tokens", model=model,
                              meta={"model": model, "price_verified": False, "price_source": "kullanıcı sağlayıcısı: fiyat bilinmiyor (girilmediyse 0 varsayılır)"})


register(CompatLLM())
