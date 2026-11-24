"""Yayın sağlayıcıları (resmî API'ler). Tarayıcı otomasyonu veya resmî olmayan yöntem YOKTUR."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ...core.config import get_settings
from ..base import ProviderError


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str = ""
    expires_in: int = 3600
    refresh_expires_in: int | None = None
    scopes: list[str] = field(default_factory=list)
    external_id: str = ""  # hesap kimliği
    display_name: str = ""
    account_type: str = ""
    capabilities: dict = field(default_factory=dict)


@dataclass
class PublishRequest:
    access_token: str
    video_path: Path
    title: str
    description: str
    hashtags: list[str]
    privacy: str  # public | unlisted | private
    duration: float
    vertical: bool
    synthetic: bool  # AI üretimi medya içeriyor mu (platform beyanı için)
    account: dict  # external_id, capabilities…
    public_video_url: str | None = None  # Instagram için herkese açık HTTPS
    cover_url: str | None = None
    state: dict = field(default_factory=dict)  # önceki denemeden kalan durum (resume)


@dataclass
class VerifyResult:
    status: str  # published | processing | failed | needs_action
    external_id: str = ""
    url: str = ""
    effective_privacy: str = ""
    detail: str = ""
    state: dict = field(default_factory=dict)


class PublishProvider:
    platform = ""
    label = ""
    scopes: list[str] = []
    needs_public_url = False
    requirements = ""  # kullanıcıya gösterilen hesap/izin gereksinimleri

    def configured(self) -> bool:
        return False

    def config_hint(self) -> str:
        return ""

    def authorize_url(self, redirect_uri: str, state: str, challenge: str) -> str:
        raise NotImplementedError

    def exchange_code(self, code: str, redirect_uri: str, verifier: str) -> TokenSet:
        raise NotImplementedError

    def refresh(self, refresh_token: str, access_token: str = "") -> TokenSet:
        raise NotImplementedError

    def publish(self, req: PublishRequest) -> dict:
        """Yüklemeyi başlat/tamamla ve platform durumunu döndür (state). PUBLISHED DEĞİLDİR — verify() gerekir."""
        raise NotImplementedError

    def verify(self, req: PublishRequest, state: dict) -> VerifyResult:
        raise NotImplementedError

    def metrics(self, access_token: str, external_id: str, duration: float, account: dict) -> dict:
        return {}


def redirect_uri(platform: str) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/api/v1/oauth/{platform}/callback"


def get_publisher(platform: str) -> PublishProvider:
    from .instagram import InstagramPublisher
    from .tiktok import TikTokPublisher
    from .youtube import YouTubePublisher

    m = {"youtube": YouTubePublisher, "tiktok": TikTokPublisher, "instagram": InstagramPublisher}
    if platform not in m:
        raise ProviderError(f"Desteklenmeyen platform: {platform}", "permanent")
    return m[platform]()


def hashtag_text(tags: list[str], limit: int = 15) -> str:
    return " ".join(t if t.startswith("#") else "#" + t for t in tags[:limit])
