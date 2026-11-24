"""Tüm HTTP sağlayıcıları için ortak istemci ve hata eşleme. Testler transport'u buradan değiştirir."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import httpx

from ..core.logging import redact
from .base import ProviderError

_transport_factory: Callable[[], httpx.BaseTransport | None] | None = None


def set_transport_factory(factory: Callable[[], httpx.BaseTransport | None] | None) -> None:
    """Yalnızca testler için: gerçek ağ yerine sahte transport kullan."""
    global _transport_factory
    _transport_factory = factory


def client(timeout: float = 120.0, follow_redirects: bool = True) -> httpx.Client:
    transport = _transport_factory() if _transport_factory else None
    return httpx.Client(timeout=timeout, transport=transport, follow_redirects=follow_redirects,
                        headers={"User-Agent": "AIVideoFactoryPro/2.0"})


def raise_for_provider(resp: httpx.Response, provider: str) -> None:
    if resp.status_code < 400:
        return
    body = redact(resp.text[:300].replace("\n", " "))
    retry_after = None
    ra = resp.headers.get("retry-after")
    if ra:
        try:
            retry_after = float(ra)
        except ValueError:
            retry_after = None
    code = resp.status_code
    if code in (401, 403):
        raise ProviderError(f"{provider}: yetkilendirme hatası ({code})", "auth")
    if code == 429:
        raise ProviderError(f"{provider}: rate limit (429)", "rate_limit", retry_after)
    if code in (408, 409, 425) or code >= 500:
        raise ProviderError(f"{provider}: geçici hata ({code}) {body}", "transient", retry_after)
    if code == 402:
        raise ProviderError(f"{provider}: ödeme/kredi yetersiz (402)", "auth")
    raise ProviderError(f"{provider}: istek reddedildi ({code}) {body}", "permanent")


def request(c: httpx.Client, method: str, url: str, provider: str, **kw) -> httpx.Response:
    try:
        r = c.request(method, url, **kw)
    except httpx.TimeoutException as e:
        raise ProviderError(f"{provider}: zaman aşımı", "transient") from e
    except httpx.HTTPError as e:
        raise ProviderError(f"{provider}: ağ hatası ({type(e).__name__})", "transient") from e
    raise_for_provider(r, provider)
    return r


def download(c: httpx.Client, url: str, dest: Path, provider: str, headers: dict | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with c.stream("GET", url, headers=headers or {}) as r:
            raise_for_provider_stream(r, provider)
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes(1 << 16):
                    f.write(chunk)
    except httpx.HTTPError as e:
        raise ProviderError(f"{provider}: indirme hatası ({type(e).__name__})", "transient") from e
    if dest.stat().st_size == 0:
        raise ProviderError(f"{provider}: boş dosya indirildi", "transient")
    return dest


def raise_for_provider_stream(r: httpx.Response, provider: str) -> None:
    if r.status_code >= 400:
        r.read()
        raise_for_provider(r, provider)


def poll(ctx, fn: Callable[[], tuple[bool, object]], *, interval: float, timeout: float, what: str,
         backoff: float = 1.0, max_interval: float = 30.0):
    """fn() -> (bitti_mi, değer). İptal ve heartbeat kontrolü yapar."""
    start = time.monotonic()
    delay = interval
    while True:
        ctx.cancel_check()
        ctx.heartbeat()
        done, value = fn()
        if done:
            return value
        if time.monotonic() - start > timeout:
            raise ProviderError(f"{what}: zaman aşımı ({int(timeout)} sn)", "transient")
        time.sleep(delay)
        delay = min(delay * backoff, max_interval)
