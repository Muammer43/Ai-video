"""Uygulama ayarları. Tüm gizli değerler ortam değişkenlerinden / .env dosyasından gelir."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEFAULT_SECRET = "dev-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "AI Video Factory Pro"
    app_version: str = "2.0.0"
    env: str = "dev"  # dev | test | prod

    # --- güvenlik ---
    secret_key: str = INSECURE_DEFAULT_SECRET
    encryption_key: str = ""  # Fernet anahtarı (urlsafe base64, 32 bayt). Boşsa dev'de secret_key'den türetilir.
    access_token_minutes: int = 30
    refresh_token_days: int = 30
    allow_registration: bool = True
    cors_origins: str = ""  # virgülle ayrılmış; boş = yalnızca aynı origin
    public_base_url: str = "http://localhost:8000"  # OAuth redirect ve imzalı URL'ler için
    rate_limit_per_minute: int = 240
    login_rate_limit_per_minute: int = 10

    # --- altyapı ---
    database_url: str = "sqlite:///./data/dev.db"
    redis_url: str = "redis://localhost:6379/0"
    celery_eager: bool = False  # True: görevler aynı süreçte koşar (yalnızca test/dev)
    work_dir: str = "./data/work"

    # --- depolama ---
    storage_backend: str = "local"  # local | s3
    local_storage_dir: str = "./data/storage"
    s3_endpoint_url: str = ""
    s3_bucket: str = "aivf"
    s3_region: str = "us-east-1"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    signed_url_ttl_seconds: int = 3600

    # --- FFmpeg ---
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    font_dir: str = "/usr/share/fonts/truetype/dejavu"
    font_name: str = "DejaVu Sans"

    # --- sunucu düzeyi sağlayıcı anahtarları (kullanıcı anahtarı yoksa yedek) ---
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    fal_key: str = ""
    runway_api_key: str = ""
    replicate_api_token: str = ""
    elevenlabs_api_key: str = ""
    pexels_api_key: str = ""
    pixabay_api_key: str = ""
    gemini_api_key: str = ""  # Google AI Studio anahtarı: ücretsiz katmanda Gemini metin + TTS
    gemini_text_model: str = "gemini-3.8-flash"
    gemini_tts_model: str = "gemini-3.8-flash-tts"
    gemini_tts_fallback_model: str = "gemini-3.8-flash-lite-tts"
    compat_llm_api_key: str = ""  # OpenAI uyumlu özel LLM (Gemini/Groq/OpenRouter…)
    compat_llm_base_url: str = ""
    compat_llm_model: str = ""

    # --- model adları (sağlayıcılar model kapattığı için yapılandırılabilir) ---
    openai_text_model: str = "gpt-4.1-mini"
    anthropic_text_model: str = "claude-sonnet-5-5"
    openai_image_model: str = "gpt-image-2"
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_stt_model: str = "whisper-1"
    elevenlabs_model: str = "eleven_multilingual_v2"
    fal_image_model: str = "fal-ai/flux/schnell"
    fal_i2v_model: str = "fal-ai/kling-video/v3/pro/image-to-video"
    fal_t2v_model: str = "fal-ai/kling-video/v3/pro/text-to-video"
    runway_model: str = "gen4_turbo"
    runway_api_version: str = "2024-11-06"
    replicate_video_model: str = ""  # örn. "owner/name" — kullanıcı belirler
    replicate_image_model: str = ""

    # --- OAuth uygulamaları (yayınlama) ---
    google_client_id: str = ""
    google_client_secret: str = ""
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    instagram_app_id: str = ""
    instagram_app_secret: str = ""
    graph_api_version: str = "v27.0"
    android_deep_link: str = "aivf://oauth-done"

    # --- push ---
    fcm_service_account_json: str = ""  # Firebase servis hesabı JSON içeriği veya dosya yolu
    fcm_project_id: str = ""

    # --- politika ---
    allow_offline_providers: bool = True  # çevrimdışı/etiketli yerel sağlayıcılar
    default_daily_budget_usd: float = 5.0
    default_monthly_budget_usd: float = 100.0
    default_per_video_budget_usd: float = 2.0
    server_cost_per_render_minute_usd: float = 0.002  # yapılandırılmış tahmin (ölçüm değil)
    storage_cost_per_gb_month_usd: float = 0.023
    pricing_overrides_json: str = ""
    project_deadline_minutes: int = 90
    stuck_job_minutes: int = 20

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def pricing_overrides(self) -> dict:
        if not self.pricing_overrides_json:
            return {}
        try:
            return json.loads(self.pricing_overrides_json)
        except json.JSONDecodeError:
            return {}

    def validate_for_runtime(self) -> None:
        if self.is_prod and self.secret_key == INSECURE_DEFAULT_SECRET:
            raise RuntimeError("SECRET_KEY üretimde değiştirilmelidir.")
        if self.is_prod and not self.encryption_key:
            raise RuntimeError("ENCRYPTION_KEY üretimde zorunludur (Fernet anahtarı).")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()


def ensure_dirs(s: Settings | None = None) -> None:
    s = s or get_settings()
    Path(s.work_dir).mkdir(parents=True, exist_ok=True)
    if s.storage_backend == "local":
        Path(s.local_storage_dir).mkdir(parents=True, exist_ok=True)
    if s.database_url.startswith("sqlite:///"):
        Path(s.database_url.replace("sqlite:///", "", 1)).parent.mkdir(parents=True, exist_ok=True)
