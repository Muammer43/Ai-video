"""V1 MVP uyumluluk katmanı: /api/jobs uçları aynı istek gövdesiyle çalışır (V2'de kimlik doğrulama zorunludur; kimlikler artık UUID)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.deps import current_user
from ..core.security import create_media_token
from ..database.session import get_db
from ..models import Asset, Project, User
from ..services import projects as svc
from .projects import project_out

router = APIRouter(prefix="/api", tags=["v1-compat"])

V1_STATUS = {"QUEUED": "queued", "PROCESSING": "processing", "WAITING_PROVIDER": "processing", "RENDERING": "processing", "QUALITY_CHECK": "processing",
             "APPROVED": "completed", "PUBLISHING": "completed", "PUBLISHED": "completed", "NEEDS_REVIEW": "needs_review", "FAILED": "failed", "CANCELLED": "failed"}
STYLE_MAP = {"cinematic": "cinematic", "documentary": "documentary", "energetic": "energetic", "minimal": "minimal"}


class V1CreateJob(BaseModel):
    topic: str = Field(min_length=3, max_length=240)
    category: str = Field(default="general", max_length=60)
    style: str = Field(default="cinematic", max_length=60)
    duration: int = Field(default=30, ge=15, le=90)
    platforms: list[str] = ["youtube", "tiktok", "instagram"]


def _v1(p: Project, db: Session) -> dict:
    o = project_out(p)
    return {"id": p.id, "topic": p.topic, "category": p.category, "style": p.style, "duration": p.duration_target, "platforms": p.platforms,
            "status": V1_STATUS.get(p.status, p.status.lower()), "stage": p.stage_message or p.stage, "progress": p.progress,
            "script": {k: v for k, v in (p.script or {}).items() if not k.startswith("_")}, "output_path": "available" if p.final_asset_id else "",
            "quality_score": p.quality_score or 0, "quality_notes": "; ".join((p.quality_report or {}).get("reasons", [])), "publish_status":
            "published" if p.status == "PUBLISHED" else "awaiting_integration" if p.status in ("APPROVED", "PUBLISHING") else "not_started",
            "error": p.error, "created_at": o["created_at"], "updated_at": o["updated_at"], "v2": o}


@router.get("/health")
def health():
    from ..services.system import status
    s = get_settings()
    st = status()
    return {"ok": st["ok"], "app": s.app_name, "version": s.app_version, "demo_mode": s.allow_offline_providers,
            "ai_configured": bool(s.openai_api_key or s.anthropic_api_key or s.fal_key)}


@router.get("/config")
def config(db: Session = Depends(get_db), user: User = Depends(current_user)):
    from ..services.usersettings import get_user_settings
    st = get_user_settings(db, user.id)
    return {"auto_publish": True, "quality_threshold": st["quality"]["low_risk_min"], "demo_mode": get_settings().allow_offline_providers}


@router.post("/jobs", status_code=200)
def create_job(body: V1CreateJob, db: Session = Depends(get_db), user: User = Depends(current_user)):
    params = dict(topic=body.topic, category=body.category if body.category != "general" else "Genel", language="tr", style=STYLE_MAP.get(body.style, "cinematic"),
                  aspect_ratio="9:16", resolution="720p", duration=body.duration, quality_tier="standard", media_mode="hybrid", voice={"gender": "female"},
                  options={}, platforms=[p for p in body.platforms if p in ("youtube", "tiktok", "instagram")], publish_mode="auto")
    p, _ = svc.create_project(db, user.id, params)
    return {"id": p.id, "status": "queued"}


@router.get("/jobs")
def list_jobs(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [_v1(p, db) for p in db.execute(select(Project).where(Project.user_id == user.id).order_by(desc(Project.created_at)).limit(100)).scalars()]


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _v1(svc.get_project(db, user.id, job_id), db)


@router.get("/jobs/{job_id}/video")
def get_video(job_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = svc.get_project(db, user.id, job_id)
    a = db.get(Asset, p.final_asset_id) if p.final_asset_id else None
    if a is None:
        raise HTTPException(404, "Video henüz hazır değil")
    return RedirectResponse(f"/api/v1/media/{create_media_token(user.id, a.storage_key)}", status_code=307)


@router.post("/jobs/{job_id}/publish")
def publish(job_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, n = svc.approve_project(db, user.id, job_id)
    if n == 0:
        return {"status": "awaiting_integration", "platforms": p.platforms,
                "message": "Video hazır. Canlı yayın için ilgili platformun OAuth bağlantısı kurulmadı (Entegrasyonlar)."}
    return {"status": "publishing", "platforms": p.platforms, "message": f"{n} platform için yayın kuyruğa alındı (platform doğrulaması sonrası 'published' olur)."}
