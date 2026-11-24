"""Sağlayıcı soyutlaması. Her sağlayıcı bağımsızdır; yönlendirici (router) yedekleme ve maliyet politikasını uygular."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..services.credentials import CredentialResolver


class ProviderError(Exception):
    """kind: transient | rate_limit | auth | permanent | unconfigured | budget | cancelled"""

    def __init__(self, message: str, kind: str = "permanent", retry_after: float | None = None):
        super().__init__(message)
        self.kind = kind
        self.retry_after = retry_after


@dataclass
class CallContext:
    user_id: str | None
    project_id: str | None
    creds: CredentialResolver
    work_dir: Path
    cancel_check: Callable[[], None] = lambda: None  # iptal edildiyse Cancelled fırlatır
    heartbeat: Callable[[], None] = lambda: None
    settings: dict = field(default_factory=dict)  # kullanıcı ayarları (tercihler)

    def sub(self, name: str) -> Path:
        p = self.work_dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


@dataclass
class ProviderResult:
    path: Path | None = None
    data: Any = None
    cost_usd: float = 0.0
    cost_estimated: bool = True  # False: sağlayıcının bildirdiği gerçek maliyet
    units: float = 0.0
    unit_name: str = ""
    meta: dict = field(default_factory=dict)
    provider: str = ""
    model: str = ""


# ---- istek tipleri ----
@dataclass
class LLMRequest:
    system: str
    user: str
    json_mode: bool = True
    max_tokens: int = 3000
    temperature: float = 0.8
    task: str = "generic"  # ideas | script | moderation | generic  (şablon sağlayıcı için)
    params: dict = field(default_factory=dict)


@dataclass
class ImageRequest:
    prompt: str
    aspect_ratio: str = "9:16"
    quality: str = "standard"
    seed: int | None = None


@dataclass
class VideoRequest:
    prompt: str
    duration: float = 5.0
    aspect_ratio: str = "9:16"
    resolution: str = "720p"
    image_path: Path | None = None  # image-to-video
    quality: str = "standard"
    seed: int | None = None
    scene_idx: int = 0
    stock_query: str = ""
    category: str = ""


@dataclass
class TTSRequest:
    text: str
    language: str = "tr"
    voice: dict = field(default_factory=dict)  # {"gender","name","speed","emotion","style"}


@dataclass
class STTRequest:
    audio_path: Path
    language: str = "tr"
    text_hint: str = ""  # bilinen metin (hizalayıcı için)
    duration: float = 0.0


@dataclass
class StockRequest:
    query: str
    orientation: str = "portrait"
    min_duration: float = 3.0
    exclude_ids: list[str] = field(default_factory=list)


class Provider:
    name = ""
    kind = ""
    is_ai = True  # üretken yapay zekâ mı?
    offline = False  # yerel/çevrimdışı yedek mi?
    price_tier = 2  # 0 ücretsiz, 1 ucuz, 2 orta, 3 pahalı
    cred_name: str | None = None  # CredentialResolver anahtarı
    label = ""

    def is_configured(self, ctx: CallContext) -> bool:
        return bool(self.cred_name is None or ctx.creds.has(self.cred_name))

    def estimate(self, req: Any) -> float:
        return 0.0

    def execute(self, ctx: CallContext, req: Any) -> ProviderResult:  # pragma: no cover - arayüz
        raise NotImplementedError

    def info(self) -> dict:
        return {"name": self.name, "kind": self.kind, "label": self.label or self.name, "is_ai": self.is_ai,
                "offline": self.offline, "price_tier": self.price_tier}
