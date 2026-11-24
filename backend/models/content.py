from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, JSONType, UTCDateTime, new_id, utcnow


def _uid():  # kullanıcı kimliği sütunu
    return mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)


class Channel(Base):
    """İçerik kanalı = niş + otomasyon kuralları."""
    __tablename__ = "channels"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = _uid()
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(60))
    language: Mapped[str] = mapped_column(String(10), default="tr")
    style: Mapped[str] = mapped_column(String(40), default="cinematic")
    voice: Mapped[dict] = mapped_column(JSONType, default=dict)
    platforms: Mapped[list] = mapped_column(JSONType, default=list)
    aspect_ratio: Mapped[str] = mapped_column(String(8), default="9:16")
    resolution: Mapped[str] = mapped_column(String(8), default="720p")
    duration: Mapped[int] = mapped_column(Integer, default=30)
    quality_tier: Mapped[str] = mapped_column(String(12), default="standard")
    media_mode: Mapped[str] = mapped_column(String(12), default="hybrid")  # ai_video | hybrid | slideshow
    # otomasyon
    automation_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    videos_per_day: Mapped[int] = mapped_column(Integer, default=1)
    posting_hours: Mapped[list] = mapped_column(JSONType, default=list)  # örn. [12, 18, 21] (UTC saat)
    auto_publish: Mapped[bool] = mapped_column(Boolean, default=True)
    brand: Mapped[dict] = mapped_column(JSONType, default=dict)  # logo_asset_id, intro_text, outro_text, watermark
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class SocialAccount(Base):
    __tablename__ = "social_accounts"
    __table_args__ = (UniqueConstraint("user_id", "platform", "external_id", name="uq_social"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = _uid()
    platform: Mapped[str] = mapped_column(String(20))  # youtube | tiktok | instagram
    external_id: Mapped[str] = mapped_column(String(120))
    display_name: Mapped[str] = mapped_column(String(160), default="")
    account_type: Mapped[str] = mapped_column(String(40), default="")
    access_token_enc: Mapped[str] = mapped_column(Text, default="")
    refresh_token_enc: Mapped[str] = mapped_column(Text, default="")
    token_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    refresh_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    scopes: Mapped[list] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | needs_reauth | disconnected
    capabilities: Mapped[dict] = mapped_column(JSONType, default=dict)  # örn. {"private_only": true}
    channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class TrendItem(Base):
    __tablename__ = "trend_items"
    __table_args__ = (UniqueConstraint("user_id", "source", "external_id", name="uq_trend"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = _uid()
    source: Mapped[str] = mapped_column(String(40))
    external_id: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(60), default="")
    title: Mapped[str] = mapped_column(String(400))
    url: Mapped[str] = mapped_column(String(600), default="")
    metrics: Mapped[dict] = mapped_column(JSONType, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class Idea(Base):
    __tablename__ = "ideas"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = _uid()
    channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(60), default="")
    title: Mapped[str] = mapped_column(String(300))
    angle: Mapped[str] = mapped_column(Text, default="")
    audience: Mapped[str] = mapped_column(String(300), default="")
    format: Mapped[str] = mapped_column(String(60), default="")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    score_detail: Mapped[dict] = mapped_column(JSONType, default=dict)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[dict] = mapped_column(JSONType, default=dict)  # trend referansları, LLM sağlayıcısı
    status: Mapped[str] = mapped_column(String(16), default="new")  # new | used | rejected
    project_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_proj_user_status", "user_id", "status"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_proj_idem"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = _uid()
    channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    idea_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    topic: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(60), default="Genel")
    language: Mapped[str] = mapped_column(String(10), default="tr")
    style: Mapped[str] = mapped_column(String(40), default="cinematic")
    aspect_ratio: Mapped[str] = mapped_column(String(8), default="9:16")
    resolution: Mapped[str] = mapped_column(String(8), default="720p")
    duration_target: Mapped[int] = mapped_column(Integer, default=30)
    quality_tier: Mapped[str] = mapped_column(String(12), default="standard")  # draft | standard | premium
    media_mode: Mapped[str] = mapped_column(String(12), default="hybrid")
    voice: Mapped[dict] = mapped_column(JSONType, default=dict)
    options: Mapped[dict] = mapped_column(JSONType, default=dict)  # müzik, altyazı stili, logo, intro/outro
    platforms: Mapped[list] = mapped_column(JSONType, default=list)
    publish_mode: Mapped[str] = mapped_column(String(12), default="auto")  # auto | manual
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)
    stage: Mapped[str] = mapped_column(String(20), default="TOPIC")
    stage_message: Mapped[str] = mapped_column(String(300), default="")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    script: Mapped[dict] = mapped_column(JSONType, default=dict)
    storyboard: Mapped[dict] = mapped_column(JSONType, default=dict)
    media_report: Mapped[dict] = mapped_column(JSONType, default=dict)
    cost_estimate: Mapped[float] = mapped_column(Float, default=0.0)
    cost_actual: Mapped[float] = mapped_column(Float, default=0.0)
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    qc_decision: Mapped[str] = mapped_column(String(20), default="")  # auto_publish | review | rejected
    quality_report: Mapped[dict] = mapped_column(JSONType, default=dict)
    final_asset_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    thumbnail_asset_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    celery_task_id: Mapped[str] = mapped_column(String(80), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    error_code: Mapped[str] = mapped_column(String(40), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    experiment_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    variant: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Scene(Base):
    __tablename__ = "scenes"
    __table_args__ = (UniqueConstraint("project_id", "idx", name="uq_scene_idx"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = _uid()
    idx: Mapped[int] = mapped_column(Integer)
    narration: Mapped[str] = mapped_column(Text, default="")
    visual_prompt: Mapped[str] = mapped_column(Text, default="")
    shot: Mapped[dict] = mapped_column(JSONType, default=dict)  # kamera, ışık, kompozisyon, geçiş, hareket
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    image_asset_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    video_asset_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    audio_asset_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    origin: Mapped[str] = mapped_column(String(24), default="")  # ai_video | ai_image_motion | stock | slideshow | procedural
    status: Mapped[str] = mapped_column(String(16), default="pending")
    meta: Mapped[dict] = mapped_column(JSONType, default=dict)


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = _uid()
    project_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)  # image video audio subtitle music final thumbnail logo
    storage_key: Mapped[str] = mapped_column(String(400), unique=True)
    mime: Mapped[str] = mapped_column(String(80), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    license: Mapped[dict] = mapped_column(JSONType, default=dict)  # {"type","source","attribution","url"}
    meta: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class MusicTrack(Base):
    """Kullanıcı yüklediği, lisansını beyan ettiği müzik."""
    __tablename__ = "music_tracks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = _uid()
    asset_id: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    mood: Mapped[str] = mapped_column(String(40), default="")
    license_type: Mapped[str] = mapped_column(String(60))
    license_source: Mapped[str] = mapped_column(String(300))
    attribution: Mapped[str] = mapped_column(String(300), default="")
    commercial_use: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class JobEvent(Base):
    __tablename__ = "job_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = _uid()
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    level: Mapped[str] = mapped_column(String(10), default="info")
    stage: Mapped[str] = mapped_column(String(20), default="")
    status: Mapped[str] = mapped_column(String(20), default="")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Task(Base):
    """Genel otomasyon görevi (trend, fikir, yayın, analiz…) — proje pipeline'ından bağımsız izleme."""
    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key", name="uq_task_idem"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = _uid()
    type: Mapped[str] = mapped_column(String(40), index=True)
    project_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    result: Mapped[dict] = mapped_column(JSONType, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    timeout_s: Mapped[int] = mapped_column(Integer, default=600)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    celery_task_id: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Publication(Base):
    __tablename__ = "publications"
    __table_args__ = (UniqueConstraint("project_id", "account_id", "variant", name="uq_pub_once"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = _uid()
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[str] = mapped_column(String(32))
    platform: Mapped[str] = mapped_column(String(20), index=True)
    variant: Mapped[str] = mapped_column(String(20), default="")
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[list] = mapped_column(JSONType, default=list)
    privacy: Mapped[str] = mapped_column(String(30), default="")  # istenen
    effective_privacy: Mapped[str] = mapped_column(String(30), default="")  # platformun doğruladığı
    scheduled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    external_id: Mapped[str] = mapped_column(String(160), default="")
    external_url: Mapped[str] = mapped_column(String(500), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[dict] = mapped_column(JSONType, default=dict)  # platform-özel (publish_id, container_id…)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = _uid()
    publication_id: Mapped[str] = mapped_column(ForeignKey("publications.id", ondelete="CASCADE"), index=True)
    taken_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    age_hours: Mapped[float] = mapped_column(Float, default=0.0)
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_watch_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    completion_rate: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0..1
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    saves: Mapped[int | None] = mapped_column(Integer, nullable=True)
    followers_gained: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw: Mapped[dict] = mapped_column(JSONType, default=dict)


class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = _uid()
    channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))  # title | hook | cover | format
    metric: Mapped[str] = mapped_column(String(30), default="view_through")  # birincil metrik
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | concluded | inconclusive
    topic: Mapped[str] = mapped_column(String(300), default="")
    variants: Mapped[dict] = mapped_column(JSONType, default=dict)  # {"A": {...}, "B": {...}}
    min_views_per_variant: Mapped[int] = mapped_column(Integer, default=500)
    result: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    concluded_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class CostEntry(Base):
    __tablename__ = "cost_ledger"
    __table_args__ = (Index("ix_cost_user_created", "user_id", "created_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = _uid()
    project_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(20))  # llm image video tts stt stock server storage publish
    units: Mapped[float] = mapped_column(Float, default=0.0)
    unit_name: Mapped[str] = mapped_column(String(24), default="")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    estimated: Mapped[bool] = mapped_column(Boolean, default=True)  # True: tablo/yapılandırma tahmini; False: sağlayıcının bildirdiği
    note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ProviderStat(Base):
    __tablename__ = "provider_stats"
    __table_args__ = (UniqueConstraint("user_id", "provider", "kind", name="uq_pstat"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = _uid()
    provider: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(20))
    calls: Mapped[int] = mapped_column(Integer, default=0)
    successes: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    total_latency_s: Mapped[float] = mapped_column(Float, default=0.0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_output_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    rate_limited: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_meta: Mapped[dict] = mapped_column(JSONType, default=dict)  # çözünürlük, süre, rate-limit başlıkları
