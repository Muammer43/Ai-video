from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
Platform = Literal["youtube", "tiktok", "instagram"]


class RegisterIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(default="", max_length=120)

    @field_validator("email")
    @classmethod
    def _e(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Geçersiz e-posta")
        return v

    @field_validator("password")
    @classmethod
    def _p(cls, v: str) -> str:
        if not (re.search(r"[A-Za-z]", v) and re.search(r"\d", v)):
            raise ValueError("Parola en az bir harf ve bir rakam içermeli")
        return v


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str = Field(max_length=200)


class PasswordChangeIn(BaseModel):
    old_password: str = Field(max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class VoiceIn(BaseModel):
    gender: Literal["female", "male"] = "female"
    speed: float = Field(default=1.0, ge=0.7, le=1.3)
    emotion: Literal["neutral", "excited", "calm", "serious", "warm", "dramatic"] = "neutral"
    voice_id: str | None = Field(default=None, max_length=80)
    openai_voice: str | None = Field(default=None, max_length=30)
    variant: int = Field(default=0, ge=0, le=9)


class ProjectOptions(BaseModel):
    subtitles: bool = True
    music: bool = True
    music_mood: Literal["calm", "epic", "upbeat", "dark"] | None = None
    intro: bool = True
    outro: bool = True
    watermark: bool = True
    cover_style: Literal["title", "none"] = "title"
    privacy: Literal["public", "unlisted", "private"] = "public"
    publish_at: str | None = Field(default=None, max_length=40)
    hook_style: str | None = Field(default=None, max_length=120)
    title_style: str | None = Field(default=None, max_length=120)


class ProjectCreate(BaseModel):
    topic: str = Field(min_length=3, max_length=300)
    category: str = Field(default="Genel", max_length=60)
    language: Literal["tr", "en"] = "tr"
    style: Literal["cinematic", "documentary", "energetic", "minimal", "anime", "3d"] = "cinematic"
    aspect_ratio: Literal["9:16", "16:9", "1:1"] = "9:16"
    resolution: Literal["720p", "1080p"] = "720p"
    duration: int = Field(default=30, ge=10, le=90)
    quality_tier: Literal["draft", "standard", "premium"] = "standard"
    media_mode: Literal["ai_video", "hybrid", "slideshow"] = "hybrid"
    voice: VoiceIn = VoiceIn()
    options: ProjectOptions = ProjectOptions()
    platforms: list[Platform] = ["youtube", "tiktok", "instagram"]
    publish_mode: Literal["auto", "manual"] = "auto"
    channel_id: str | None = Field(default=None, max_length=32)
    idea_id: str | None = Field(default=None, max_length=32)

    def to_params(self) -> dict:
        d = self.model_dump()
        d["voice"] = self.voice.model_dump(exclude_none=True)
        d["options"] = self.options.model_dump(exclude_none=True)
        return d


class ApproveIn(BaseModel):
    override: bool = False


class RetryIn(BaseModel):
    reset: bool = False


class ChannelIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    category: str = Field(max_length=60)
    language: Literal["tr", "en"] = "tr"
    style: Literal["cinematic", "documentary", "energetic", "minimal", "anime", "3d"] = "cinematic"
    voice: VoiceIn = VoiceIn()
    platforms: list[Platform] = ["youtube"]
    aspect_ratio: Literal["9:16", "16:9", "1:1"] = "9:16"
    resolution: Literal["720p", "1080p"] = "720p"
    duration: int = Field(default=30, ge=10, le=90)
    quality_tier: Literal["draft", "standard", "premium"] = "standard"
    media_mode: Literal["ai_video", "hybrid", "slideshow"] = "hybrid"
    automation_enabled: bool = False
    videos_per_day: int = Field(default=1, ge=1, le=12)
    posting_hours: list[int] = Field(default_factory=list, max_length=12)
    auto_publish: bool = True
    brand: dict = Field(default_factory=dict)

    @field_validator("posting_hours")
    @classmethod
    def _h(cls, v: list[int]) -> list[int]:
        if any(h < 0 or h > 23 for h in v):
            raise ValueError("Saat 0-23 olmalı")
        return sorted(set(v))

    @field_validator("brand")
    @classmethod
    def _b(cls, v: dict) -> dict:
        allowed = {"intro_text", "outro_text", "logo_asset_id", "options"}
        if set(v) - allowed:
            raise ValueError(f"brand yalnızca {sorted(allowed)} içerebilir")
        for k in ("intro_text", "outro_text"):
            if k in v and len(str(v[k])) > 80:
                raise ValueError(f"{k} en fazla 80 karakter")
        return v


class IdeaGenerateIn(BaseModel):
    category: str = Field(max_length=60)
    count: int = Field(default=5, ge=1, le=10)
    channel_id: str | None = Field(default=None, max_length=32)
    language: Literal["tr", "en"] = "tr"


class CredentialIn(BaseModel):
    secret: str = Field(min_length=8, max_length=500)


class PreferencesIn(BaseModel):
    llm: list[str] | None = None
    image: list[str] | None = None
    video: list[str] | None = None
    tts: list[str] | None = None
    stt: list[str] | None = None


class BudgetIn(BaseModel):
    daily_usd: float | None = Field(default=None, gt=0, le=10000)
    monthly_usd: float | None = Field(default=None, gt=0, le=100000)
    per_video_usd: float | None = Field(default=None, gt=0, le=1000)
    alert_pct: int | None = Field(default=None, ge=10, le=100)
    block_expensive_fallback: bool | None = None


class QualityIn(BaseModel):
    auto_publish_min: int = Field(ge=50, le=100)
    low_risk_min: int = Field(ge=40, le=100)
    review_min: int = Field(ge=20, le=100)

    @field_validator("review_min")
    @classmethod
    def _o(cls, v: int, info) -> int:  # noqa: ANN001
        d = info.data
        if "low_risk_min" in d and "auto_publish_min" in d and not (v < d["low_risk_min"] <= d["auto_publish_min"]):
            raise ValueError("review_min < low_risk_min <= auto_publish_min olmalı")
        return v


class ExperimentIn(BaseModel):
    kind: Literal["hook", "title", "cover", "format"]
    channel_id: str | None = Field(default=None, max_length=32)
    min_views_per_variant: int = Field(default=500, ge=50, le=100000)


class DeviceIn(BaseModel):
    token: str = Field(min_length=10, max_length=400)
    platform: Literal["android"] = "android"


class RescheduleIn(BaseModel):
    scheduled_at: str = Field(max_length=40)
