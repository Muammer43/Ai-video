"""Sağlayıcı yönlendirici: tercih sırası, yedekleme (fallback), maliyet koruması, istatistik ve maliyet defteri."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..core.config import get_settings
from ..core.errors import BudgetExceeded, Cancelled
from ..core.logging import redact
from ..services import costs
from .base import CallContext, Provider, ProviderError, ProviderResult
from .pricing import TIERS

log = logging.getLogger(__name__)
_REGISTRY: dict[str, dict[str, Provider]] = {}


def register(p: Provider) -> Provider:
    _REGISTRY.setdefault(p.kind, {})[p.name] = p
    return p


def get(kind: str, name: str) -> Provider | None:
    load_all()
    return _REGISTRY.get(kind, {}).get(name)


def all_providers() -> list[Provider]:
    load_all()
    return [p for d in _REGISTRY.values() for p in d.values()]


_loaded = False


def load_all() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    from . import llm, image, video, tts, stt  # noqa: F401  (kayıt yan etkisi)


class ProviderExhausted(Exception):
    def __init__(self, kind: str, attempts: list[dict]):
        self.kind = kind
        self.attempts = attempts
        super().__init__(f"{kind}: kullanılabilir sağlayıcı yok — " + "; ".join(
            f"{a['provider']}: {a['outcome']}" for a in attempts) if attempts else f"{kind}: sağlayıcı yapılandırılmamış")


@dataclass
class RouteOutcome:
    result: ProviderResult
    provider: str
    attempts: list[dict] = field(default_factory=list)


def run(kind: str, ctx: CallContext, request: Any, *, preferred: list[str] | None = None,
        db_factory: Callable | None = None, guard: Callable[[float], None] | None = None,
        max_cost: float | None = None, only_ai: bool = False, retries: int = 2) -> RouteOutcome:
    """Sıradaki ilk çalışan sağlayıcının sonucunu döndürür.

    - Yapılandırılmamış sağlayıcılar atlanır (çalışıyormuş gibi gösterilmez).
    - 'offline' sağlayıcılar ALLOW_OFFLINE_PROVIDERS kapalıysa atlanır.
    - Tahmini maliyet max_cost'u aşarsa veya 'pahalıya geçişi engelle' açıkken daha yüksek kademeye düşülecekse atlanır.
    - Bütçe ihlali (guard) fallback ile aşılmaz; BudgetExceeded fırlatılır.
    """
    load_all()
    s = get_settings()
    names = preferred or list(_REGISTRY.get(kind, {}).keys())
    block_exp = bool(ctx.settings.get("budget", {}).get("block_expensive_fallback", True))
    attempts: list[dict] = []
    first_tier: int | None = None
    for name in names:
        p = _REGISTRY.get(kind, {}).get(name)
        if p is None:
            continue
        if p.offline and not s.allow_offline_providers:
            attempts.append({"provider": name, "outcome": "çevrimdışı sağlayıcılar kapalı"})
            continue
        if only_ai and not p.is_ai:
            attempts.append({"provider": name, "outcome": "yalnızca AI sağlayıcı istendi"})
            continue
        if not p.is_configured(ctx):
            attempts.append({"provider": name, "outcome": "yapılandırılmamış (anahtar yok)"})
            continue
        tier = TIERS.get(name, p.price_tier)
        if first_tier is None:
            first_tier = tier
        elif block_exp and tier > first_tier:
            attempts.append({"provider": name, "outcome": "daha pahalı yedeğe otomatik geçiş engellendi"})
            continue
        est = p.estimate(request)
        if max_cost is not None and est > max_cost:
            attempts.append({"provider": name, "outcome": f"tahmini maliyet ${est:.3f} sınırı aşıyor (${max_cost:.3f})"})
            continue
        if guard:
            guard(est)  # BudgetExceeded fırlatabilir -> fallback yok
        last_err: ProviderError | None = None
        for attempt in range(retries + 1):
            ctx.cancel_check()
            t0 = time.monotonic()
            try:
                res = p.execute(ctx, request)
                res.provider = name
                dt = time.monotonic() - t0
                _record(db_factory, ctx, p, res, dt, ok=True)
                attempts.append({"provider": name, "outcome": "başarılı", "seconds": round(dt, 2)})
                return RouteOutcome(res, name, attempts)
            except (Cancelled, BudgetExceeded):
                raise
            except ProviderError as e:
                last_err = e
                _record(db_factory, ctx, p, None, time.monotonic() - t0, ok=False, error=str(e), kind=e.kind)
                if e.kind in ("transient", "rate_limit") and attempt < retries:
                    time.sleep(min(e.retry_after or (2 ** attempt), 20))
                    continue
                break
            except Exception as e:  # noqa: BLE001
                last_err = ProviderError(f"{type(e).__name__}: {redact(str(e))[:200]}", "permanent")
                _record(db_factory, ctx, p, None, time.monotonic() - t0, ok=False, error=str(last_err))
                break
        attempts.append({"provider": name, "outcome": f"başarısız ({last_err.kind}): {redact(str(last_err))[:200]}"})
        log.warning("sağlayıcı %s/%s başarısız: %s", kind, name, last_err)
    raise ProviderExhausted(kind, attempts)


def _record(db_factory, ctx: CallContext, p: Provider, res: ProviderResult | None, seconds: float, *, ok: bool,
            error: str = "", kind: str = "") -> None:
    if db_factory is None or not ctx.user_id:
        return
    try:
        with db_factory() as db:
            costs.record_call(db, ctx.user_id, ctx.project_id, p, res, seconds, ok, error, kind)
    except Exception:  # noqa: BLE001
        log.exception("sağlayıcı istatistiği yazılamadı")
