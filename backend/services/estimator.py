"""Üretim öncesi maliyet tahmini: yönlendiricinin seçeceği sağlayıcılar için kalem kalem hesap."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..providers import router
from ..providers.base import CallContext, ImageRequest, LLMRequest, STTRequest, TTSRequest, VideoRequest
from ..providers.pricing import TIERS
from .content import scene_count
from .credentials import CredentialResolver
from .usersettings import get_user_settings

PADDING = 1.15


def plan_for_scene(media_mode: str, tier: str, idx: int) -> list[str]:
    if media_mode == "slideshow" or (tier == "draft" and media_mode != "ai_video"):
        return ["image_motion"]
    if media_mode == "ai_video":
        return ["ai_video", "image_motion"]
    return ["ai_video", "stock", "image_motion"] if idx % 3 == 0 else ["stock", "image_motion"]


def _first(kind: str, ctx: CallContext, prefs: list[str], req, only_ai: bool = False):
    s = get_settings()
    first_tier = None
    for name in prefs:
        p = router.get(kind, name)
        if p is None or not p.is_configured(ctx) or (p.offline and not s.allow_offline_providers) or (only_ai and not p.is_ai):
            continue
        t = TIERS.get(name, p.price_tier)
        if first_tier is None:
            first_tier = t
        return p, p.estimate(req)
    return None, 0.0


def estimate_project(db: Session, user_id: str, *, duration: int, media_mode: str, quality_tier: str, aspect_ratio: str,
                     resolution: str, work: Path | None = None) -> dict:
    ctx = CallContext(user_id=user_id, project_id=None, creds=CredentialResolver(db, user_id), work_dir=work or Path("."),
                      settings=get_user_settings(db, user_id))
    prefs = ctx.settings["providers"]
    n = scene_count(duration)
    per = duration / n
    items = []
    warnings = []

    def add(kind: str, provider: str | None, label: str, cost: float, units: str):
        items.append({"kind": kind, "provider": provider or "—", "label": label, "usd": round(cost, 4), "units": units})

    p, c = _first("llm", ctx, prefs["llm"], LLMRequest(system="x" * 1500, user="y" * 1500, max_tokens=4000))
    add("llm", p.name if p else None, "Senaryo (LLM)", c, "1 çağrı")
    if p is None:
        warnings.append("LLM sağlayıcısı yok")
    elif not p.is_ai:
        warnings.append("LLM yerine yerel şablon kullanılacak (AI değil) — otomatik yayına alınmaz")
    chars = int(duration * 15)
    p, c = _first("tts", ctx, prefs["tts"], TTSRequest(text="x" * chars))
    add("tts", p.name if p else None, "Seslendirme", c, f"~{chars} karakter")
    if p is not None and not p.is_ai:
        warnings.append("Seslendirme yerel robotik sentez — otomatik yayına alınmaz")
    p, c = _first("stt", ctx, prefs["stt"], STTRequest(audio_path=Path("x"), duration=duration))
    add("stt", p.name if p else None, "Altyazı zamanlaması", c, f"{duration} sn")
    img_p, img_c = _first("image", ctx, prefs["image"], ImageRequest(prompt="x", aspect_ratio=aspect_ratio))
    vid_p, vid_c = _first("video", ctx, [x for x in prefs["video"] if x not in ("stock", "ken_burns")],
                          VideoRequest(prompt="x", duration=per, aspect_ratio=aspect_ratio, resolution=resolution), only_ai=True)
    img_total = vid_total = 0.0
    ai_scenes = 0
    for i in range(n):
        plan = plan_for_scene(media_mode, quality_tier, i)
        if "ai_video" in plan and vid_p is not None:
            ai_scenes += 1
            vid_total += vid_c
            img_total += img_c if (img_p and img_p.is_ai) else 0
        elif "stock" in plan and ctx.creds.has("pexels") or "stock" in plan and ctx.creds.has("pixabay"):
            pass
        else:
            img_total += img_c
    add("image", img_p.name if img_p else None, "Sahne görselleri", img_total, f"{n} sahne")
    add("video", vid_p.name if vid_p else None, "AI video klipleri", vid_total, f"{ai_scenes} sahne × ~{per:.0f} sn")
    if media_mode in ("ai_video", "hybrid") and vid_p is None:
        warnings.append("Yapılandırılmış AI video sağlayıcısı yok: sahneler görsel+hareket (AI video değil) olarak üretilecek")
    s = get_settings()
    add("server", "server", "Render (sunucu, yapılandırılmış tahmin)", s.server_cost_per_render_minute_usd * duration / 60 * 3, "~3x gerçek süre")
    add("storage", "storage", "Depolama (ilk ay, tahmin)", s.storage_cost_per_gb_month_usd * 0.03, "~30 MB")
    total = sum(i["usd"] for i in items) * PADDING
    st = ctx.settings["budget"]
    if total > st["per_video_usd"]:
        warnings.append(f"Tahmin (${total:.2f}) video başına sınırı (${st['per_video_usd']:.2f}) aşıyor")
    return {"items": items, "total_usd": round(total, 4), "padding": PADDING, "scenes": n, "warnings": warnings,
            "note": "Tahmin; sağlayıcı fiyat tablosu ve istek boyutlarına dayanır. Fiyatı doğrulanmamış kalemler 'price_verified=false'tir."}
