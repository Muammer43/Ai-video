"""Proje yaşam döngüsü: oluşturma (tahmin + bütçe + idempotency), iptal, yeniden deneme, onay, silme."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.errors import AppError, Conflict, NotFound
from ..models import Asset, Channel, Idea, IdempotencyRecord, JobEvent, Project, Status, utcnow
from ..workers.dispatch import dispatch
from . import costs
from .assets import delete_asset
from .estimator import estimate_project
from .events import emit
from .notifications import notify
from .usersettings import get_user_settings

CATEGORIES = ["Oyun", "GTA 6", "Teknoloji", "Yapay Zekâ", "Otomobil", "Bilim", "Tarih", "Bilgi", "Eğlence", "Finans", "Seyahat",
              "Eğitim", "Hikâye", "Belgesel"]


def get_project(db: Session, user_id: str, project_id: str) -> Project:
    p = db.get(Project, project_id)
    if p is None or p.user_id != user_id:  # başka kullanıcının kaydı = yok (izolasyon)
        raise NotFound("Proje bulunamadı")
    return p


def _hash(d: Any) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


def create_project(db: Session, user_id: str, params: dict, *, idempotency_key: str | None = None, notify_fn=notify) -> tuple[Project, dict]:
    """Dönüş: (proje, tahmin). Aynı Idempotency-Key ile tekrar çağrı aynı projeyi döndürür."""
    rh = _hash(params)
    if idempotency_key:
        existing = db.execute(select(Project).where(Project.user_id == user_id, Project.idempotency_key == idempotency_key)).scalar_one_or_none()
        if existing:
            rec = db.execute(select(IdempotencyRecord).where(IdempotencyRecord.user_id == user_id, IdempotencyRecord.scope == "project",
                                                              IdempotencyRecord.key == idempotency_key)).scalar_one_or_none()
            if rec and rec.request_hash != rh:
                raise Conflict("Bu Idempotency-Key farklı bir istek için kullanılmış", code="idempotency_mismatch")
            return existing, {"replayed": True}
    settings = get_user_settings(db, user_id)
    ch = db.get(Channel, params["channel_id"]) if params.get("channel_id") else None
    if ch is not None and ch.user_id != user_id:
        raise NotFound("Kanal bulunamadı")
    est = estimate_project(db, user_id, duration=params["duration"], media_mode=params["media_mode"], quality_tier=params["quality_tier"],
                           aspect_ratio=params["aspect_ratio"], resolution=params["resolution"])
    costs.check_budget(db, user_id, est["total_usd"], None, notify_fn=notify_fn)  # günlük/aylık
    if est["total_usd"] > settings["budget"]["per_video_usd"]:
        raise AppError(f"Tahmini maliyet ${est['total_usd']:.2f} video başına sınırı (${settings['budget']['per_video_usd']:.2f}) aşıyor. "
                       "Kaliteyi/modu düşürün veya sınırı artırın.", code="per_video_budget", status_code=402, data={"estimate": est})
    p = Project(user_id=user_id, channel_id=params.get("channel_id"), idea_id=params.get("idea_id"), topic=params["topic"], category=params["category"],
                language=params["language"], style=params["style"], aspect_ratio=params["aspect_ratio"], resolution=params["resolution"],
                duration_target=params["duration"], quality_tier=params["quality_tier"], media_mode=params["media_mode"], voice=params.get("voice") or {},
                options=params.get("options") or {}, platforms=params.get("platforms") or [], publish_mode=params.get("publish_mode", "auto"),
                status=Status.QUEUED, stage="TOPIC", cost_estimate=est["total_usd"], idempotency_key=idempotency_key,
                experiment_id=params.get("experiment_id"), variant=params.get("variant", ""))
    db.add(p)
    try:
        db.flush()
        if idempotency_key:
            db.add(IdempotencyRecord(user_id=user_id, scope="project", key=idempotency_key, request_hash=rh, response={"project_id": p.id}))
        if p.idea_id:
            idea = db.get(Idea, p.idea_id)
            if idea and idea.user_id == user_id:
                idea.status, idea.project_id = "used", p.id
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.execute(select(Project).where(Project.user_id == user_id, Project.idempotency_key == idempotency_key)).scalar_one_or_none()
        if existing:
            return existing, {"replayed": True}
        raise
    emit(p.id, "İş kuyruğa alındı", stage="TOPIC", progress=0)
    tid = dispatch("run_project_task", [p.id], queue="render")
    p.celery_task_id = tid
    db.commit()
    return p, est


def cancel_project(db: Session, user_id: str, project_id: str) -> Project:
    p = get_project(db, user_id, project_id)
    if p.status in Status.TERMINAL:
        raise Conflict(f"İş zaten {p.status}")
    if p.status == Status.QUEUED:
        p.status, p.finished_at = Status.CANCELLED, utcnow()
        p.cancel_requested = True
        db.commit()
        emit(p.id, "İş iptal edildi (kuyruktan)", level="warning", stage="CANCELLED", status=Status.CANCELLED)
    else:
        p.cancel_requested = True  # çalışan iş aşama sınırında/polling'de durur
        db.commit()
        emit(p.id, "İptal istendi — iş en yakın güvenli noktada duracak", level="warning")
    return p


def retry_project(db: Session, user_id: str, project_id: str, *, reset: bool = False) -> Project:
    p = get_project(db, user_id, project_id)
    if p.status not in Status.RETRYABLE:
        raise Conflict(f"{p.status} durumundaki iş yeniden denenemez")
    settings = get_user_settings(db, user_id)
    if settings["budget"]["paused"]:
        raise AppError("Bütçe nedeniyle üretim duraklatıldı; önce bütçeyi güncelleyip devam ettirin.", code="budget_paused", status_code=402)
    vals: dict = dict(status=Status.QUEUED, cancel_requested=False, error="", error_code="", attempts=0, progress=0, finished_at=None,
                      updated_at=utcnow(), qc_decision="", stage_message="Yeniden kuyruğa alındı")
    if reset:  # sıfırdan: senaryo/sahne çıktıları silinir
        vals.update(script={}, storyboard={}, media_report={}, quality_report={}, quality_score=None, final_asset_id=None, thumbnail_asset_id=None)
        from ..models import Scene
        db.execute(Scene.__table__.delete().where(Scene.project_id == p.id))
        for a in db.execute(select(Asset).where(Asset.project_id == p.id)).scalars().all():
            delete_asset(db, a)
    db.execute(update(Project).where(Project.id == p.id).values(**vals))
    db.commit()
    db.refresh(p)
    emit(p.id, "Yeniden deneme isteği alındı", stage="TOPIC", progress=0)
    p.celery_task_id = dispatch("run_project_task", [p.id], queue="render")
    db.commit()
    return p


def delete_project(db: Session, user_id: str, project_id: str) -> None:
    p = get_project(db, user_id, project_id)
    if p.status in Status.RUNNING | {Status.PUBLISHING}:
        raise Conflict("Çalışan/yayınlanan iş silinemez; önce iptal edin")
    for a in db.execute(select(Asset).where(Asset.project_id == p.id)).scalars().all():
        delete_asset(db, a)
    db.execute(JobEvent.__table__.delete().where(JobEvent.project_id == p.id))
    db.delete(p)
    db.commit()


def approve_project(db: Session, user_id: str, project_id: str, *, override: bool = False) -> tuple[Project, int]:
    from .publishing import enqueue_publications
    p = get_project(db, user_id, project_id)
    if p.status != Status.NEEDS_REVIEW and not (p.status == Status.APPROVED):
        raise Conflict(f"{p.status} durumundaki iş onaylanamaz")
    crit = (p.quality_report or {}).get("critical", [])
    if crit and not override:
        raise AppError("Kritik güvenlik/telif bulguları var: " + ", ".join(crit) + ". Yine de yayınlamak için override=true gönderin.",
                       code="critical_findings", status_code=409, data={"critical": crit})
    p.status = Status.APPROVED
    db.commit()
    emit(p.id, "Kullanıcı onayladı" + (" (kritik bulgulara rağmen)" if crit else ""), stage="PUBLISH", status=Status.APPROVED)
    n = enqueue_publications(p.id, force=True)
    return p, n
