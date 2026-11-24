from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..automation.engine import run_channel_now
from ..core.deps import audit, current_user
from ..core.errors import AppError, Conflict, NotFound
from ..database.session import get_db
from ..editor import ffmpeg as ff
from ..models import Asset, Channel, Idea, Project, Publication, Status, SocialAccount, Task, TrendItem, User, utcnow
from ..schemas.api import ChannelIn, IdeaGenerateIn, RescheduleIn
from ..services import assets as assets_svc
from ..services import projects as psvc
from ..services.usersettings import get_user_settings, update_user_settings
from ..workers.dispatch import dispatch
from ..workers.tasks import tracked

router = APIRouter(tags=["content"])


def channel_out(c: Channel) -> dict:
    return {"id": c.id, "name": c.name, "category": c.category, "language": c.language, "style": c.style, "voice": c.voice, "platforms": c.platforms,
            "aspect_ratio": c.aspect_ratio, "resolution": c.resolution, "duration": c.duration, "quality_tier": c.quality_tier, "media_mode": c.media_mode,
            "automation_enabled": c.automation_enabled, "videos_per_day": c.videos_per_day, "posting_hours": c.posting_hours, "auto_publish": c.auto_publish,
            "brand": c.brand, "last_run_at": c.last_run_at.isoformat() if c.last_run_at else None, "created_at": c.created_at.isoformat()}


def _chan(db: Session, user_id: str, cid: str) -> Channel:
    c = db.get(Channel, cid)
    if c is None or c.user_id != user_id:
        raise NotFound("Kanal bulunamadı")
    return c


@router.get("/channels")
def channels(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [channel_out(c) for c in db.execute(select(Channel).where(Channel.user_id == user.id).order_by(Channel.created_at)).scalars()]


@router.post("/channels", status_code=201)
def channel_create(body: ChannelIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    d = body.model_dump()
    d["voice"] = body.voice.model_dump(exclude_none=True)
    c = Channel(user_id=user.id, **d)
    db.add(c)
    db.commit()
    audit(db, request, user.id, "channel.create", "channel", c.id)
    return channel_out(c)


@router.put("/channels/{cid}")
def channel_update(cid: str, body: ChannelIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c = _chan(db, user.id, cid)
    d = body.model_dump()
    d["voice"] = body.voice.model_dump(exclude_none=True)
    lid = (c.brand or {}).get("logo_asset_id")
    for k, v in d.items():
        setattr(c, k, v)
    if lid and "logo_asset_id" not in c.brand:
        c.brand = {**c.brand, "logo_asset_id": lid}
    db.commit()
    audit(db, request, user.id, "channel.update", "channel", cid)
    return channel_out(c)


@router.delete("/channels/{cid}")
def channel_delete(cid: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c = _chan(db, user.id, cid)
    db.delete(c)
    db.commit()
    audit(db, request, user.id, "channel.delete", "channel", cid)
    return {"ok": True}


@router.post("/channels/{cid}/run-now", status_code=202)
def channel_run(cid: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = run_channel_now(db, user.id, cid)
    audit(db, request, user.id, "channel.run_now", "channel", cid)
    return r


@router.post("/channels/{cid}/logo")
async def channel_logo(cid: str, file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    c = _chan(db, user.id, cid)
    data = await file.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise AppError("Logo en fazla 2 MB olabilir", code="file_too_large", status_code=413)
    ext = ".png" if data[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg" if data[:3] == b"\xff\xd8\xff" else None  # içerik imzası (uzantıya güvenilmez)
    if ext is None:
        raise AppError("Yalnızca PNG veya JPEG logo kabul edilir", code="bad_file_type", status_code=415)
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / f"logo{ext}"
        p.write_bytes(data)
        try:
            info = ff.probe(p)
        except Exception as e:  # noqa: BLE001
            raise AppError("Görsel okunamadı", code="bad_file", status_code=415) from e
        if info.width > 4000 or info.height > 4000:
            raise AppError("Logo çok büyük (en fazla 4000 px)", code="bad_file", status_code=413)
        a = assets_svc.store_asset(db, user.id, None, "logo", p, meta={"width": info.width, "height": info.height})
    c.brand = {**(c.brand or {}), "logo_asset_id": a.id}
    db.commit()
    return channel_out(c)


# ---------- fikirler / trendler / görevler ----------
def idea_out(i: Idea) -> dict:
    return {"id": i.id, "title": i.title, "angle": i.angle, "audience": i.audience, "format": i.format, "score": i.score, "score_detail": i.score_detail,
            "category": i.category, "status": i.status, "project_id": i.project_id, "channel_id": i.channel_id, "source": i.source,
            "created_at": i.created_at.isoformat()}


@router.post("/ideas/generate", status_code=202)
def ideas_generate(body: IdeaGenerateIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    tid = tracked("idea_generation", user.id, body.model_dump(), 300)
    dispatch("generate_ideas_task", [tid])
    audit(db, request, user.id, "ideas.generate", "task", tid)
    return {"task_id": tid}


@router.get("/ideas")
def ideas(status: str | None = None, limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = select(Idea).where(Idea.user_id == user.id)
    if status:
        q = q.where(Idea.status == status)
    return [idea_out(i) for i in db.execute(q.order_by(desc(Idea.score), desc(Idea.created_at)).limit(limit)).scalars()]


@router.post("/ideas/{iid}/produce", status_code=202)
def idea_produce(iid: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    i = db.get(Idea, iid)
    if i is None or i.user_id != user.id:
        raise NotFound("Fikir bulunamadı")
    if i.status != "new":
        raise Conflict("Bu fikir zaten kullanıldı veya reddedildi")
    ch = db.get(Channel, i.channel_id) if i.channel_id else None
    params = dict(topic=i.title, category=i.category or "Genel", language=ch.language if ch else "tr", style=ch.style if ch else "cinematic",
                  aspect_ratio=ch.aspect_ratio if ch else "9:16", resolution=ch.resolution if ch else "720p", duration=ch.duration if ch else 30,
                  quality_tier=ch.quality_tier if ch else "standard", media_mode=ch.media_mode if ch else "hybrid", voice=ch.voice if ch else {},
                  options={}, platforms=ch.platforms if ch else [], publish_mode="auto" if (ch and ch.auto_publish) else "manual",
                  channel_id=ch.id if ch else None, idea_id=i.id)
    p, est = psvc.create_project(db, user.id, params, idempotency_key=f"idea:{i.id}")
    audit(db, request, user.id, "idea.produce", "idea", iid)
    return {"project_id": p.id, "estimate": est}


@router.delete("/ideas/{iid}")
def idea_reject(iid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    i = db.get(Idea, iid)
    if i is None or i.user_id != user.id:
        raise NotFound("Fikir bulunamadı")
    i.status = "rejected"
    db.commit()
    return {"ok": True}


@router.post("/trends/refresh", status_code=202)
def trends_refresh(categories: list[str] | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    tid = tracked("trend_research", user.id, {"categories": (categories or [])[:10]}, 300)
    dispatch("refresh_trends_for_user_task", [tid])
    return {"task_id": tid}


@router.get("/trends")
def trends(category: str | None = None, limit: int = Query(default=30, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = select(TrendItem).where(TrendItem.user_id == user.id)
    if category:
        q = q.where(TrendItem.category == category)
    rows = db.execute(q.order_by(desc(TrendItem.fetched_at)).limit(limit)).scalars()
    return [{"id": t.id, "source": t.source, "category": t.category, "title": t.title, "url": t.url, "metrics": t.metrics,
             "fetched_at": t.fetched_at.isoformat()} for t in rows]


def task_out(t: Task) -> dict:
    return {"id": t.id, "type": t.type, "status": t.status, "progress": t.progress, "result": t.result, "error": t.error, "attempts": t.attempts,
            "created_at": t.created_at.isoformat(), "finished_at": t.finished_at.isoformat() if t.finished_at else None}


@router.get("/tasks")
def tasks(limit: int = Query(default=30, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [task_out(t) for t in db.execute(select(Task).where(Task.user_id == user.id).order_by(desc(Task.created_at)).limit(limit)).scalars()]


@router.get("/tasks/{tid}")
def task_get(tid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = db.get(Task, tid)
    if t is None or t.user_id != user.id:
        raise NotFound("Görev bulunamadı")
    return task_out(t)


@router.post("/tasks/{tid}/cancel")
def task_cancel(tid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = db.get(Task, tid)
    if t is None or t.user_id != user.id:
        raise NotFound("Görev bulunamadı")
    if t.status in ("DONE", "FAILED", "CANCELLED"):
        raise Conflict(f"Görev zaten {t.status}")
    t.cancel_requested = True
    if t.status == "QUEUED":
        t.status = "CANCELLED"
    db.commit()
    return task_out(t)


# ---------- otomasyon ----------
@router.get("/automation/status")
def automation_status(db: Session = Depends(get_db), user: User = Depends(current_user)):
    st = get_user_settings(db, user.id)
    chans = db.execute(select(Channel).where(Channel.user_id == user.id)).scalars().all()
    active = db.execute(select(Project).where(Project.user_id == user.id, Project.status.in_(list(Status.ACTIVE)))).scalars().all()
    return {"paused": st["automation"]["paused"], "budget_paused": st["budget"]["paused"], "channels_total": len(chans),
            "channels_automated": sum(1 for c in chans if c.automation_enabled), "active_projects": len(active),
            "channels": [{"id": c.id, "name": c.name, "enabled": c.automation_enabled, "videos_per_day": c.videos_per_day,
                          "last_run_at": c.last_run_at.isoformat() if c.last_run_at else None} for c in chans]}


@router.post("/automation/pause")
def automation_pause(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    update_user_settings(db, user.id, {"automation": {"paused": True}})
    audit(db, request, user.id, "automation.pause")
    return {"paused": True}


@router.post("/automation/resume")
def automation_resume(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    update_user_settings(db, user.id, {"automation": {"paused": False}})
    audit(db, request, user.id, "automation.resume")
    return {"paused": False}


# ---------- yayın takvimi ----------
def pub_out(x: Publication, p: Project | None = None) -> dict:
    return {"id": x.id, "project_id": x.project_id, "platform": x.platform, "status": x.status, "title": x.title, "scheduled_at": x.scheduled_at.isoformat() if x.scheduled_at else None,
            "published_at": x.published_at.isoformat() if x.published_at else None, "external_url": x.external_url, "error": x.error, "attempts": x.attempts,
            "effective_privacy": x.effective_privacy, "verified": bool(x.verified_at), "topic": p.topic if p else None}


@router.get("/calendar")
def calendar(days_back: int = Query(default=7, ge=0, le=90), days_ahead: int = Query(default=14, ge=0, le=90), db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    now = utcnow()
    a, b = now - timedelta(days=days_back), now + timedelta(days=days_ahead)
    pubs = db.execute(select(Publication, Project).join(Project, Project.id == Publication.project_id).where(
        Publication.user_id == user.id, ((Publication.scheduled_at >= a) & (Publication.scheduled_at <= b)) | ((Publication.published_at >= a) & (Publication.published_at <= b)) |
        (Publication.status.in_(["QUEUED", "UPLOADING", "PROCESSING", "NEEDS_ACTION"])))).all()
    upcoming = db.execute(select(Project).where(Project.user_id == user.id, Project.status.in_(list(Status.ACTIVE) + ["APPROVED", "NEEDS_REVIEW"]))
                          .order_by(Project.created_at)).scalars().all()
    return {"publications": [pub_out(x, p) for x, p in pubs], "pipeline": [{"id": p.id, "topic": p.topic, "status": p.status, "progress": p.progress,
                                                                            "publish_at": (p.options or {}).get("publish_at")} for p in upcoming]}


def _pub(db: Session, user_id: str, pid: str) -> Publication:
    x = db.get(Publication, pid)
    if x is None or x.user_id != user_id:
        raise NotFound("Yayın bulunamadı")
    return x


@router.post("/publications/{pid}/reschedule")
def pub_reschedule(pid: str, body: RescheduleIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    x = _pub(db, user.id, pid)
    if x.status not in ("QUEUED", "NEEDS_ACTION", "FAILED"):
        raise Conflict(f"{x.status} durumundaki yayın zamanlanamaz")
    try:
        t = datetime.fromisoformat(body.scheduled_at)
    except ValueError as e:
        raise AppError("Geçersiz tarih (ISO 8601)", code="bad_date", status_code=422) from e
    x.scheduled_at, x.status, x.error, x.attempts, x.next_attempt_at = t, "QUEUED", "", 0, None
    db.commit()
    return pub_out(x)


@router.post("/publications/{pid}/retry", status_code=202)
def pub_retry(pid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    x = _pub(db, user.id, pid)
    if x.status not in ("FAILED", "NEEDS_ACTION"):
        raise Conflict(f"{x.status} durumundaki yayın yeniden denenemez")
    x.status, x.error, x.attempts, x.next_attempt_at = "QUEUED", "", 0, None
    p = db.get(Project, x.project_id)
    if p and p.status != Status.PUBLISHING:
        p.status = Status.PUBLISHING
    db.commit()
    dispatch("publish_task", [x.id])
    return pub_out(x)


@router.post("/publications/{pid}/cancel")
def pub_cancel(pid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    x = _pub(db, user.id, pid)
    if x.status not in ("QUEUED", "NEEDS_ACTION", "FAILED"):
        raise Conflict(f"{x.status} durumundaki yayın iptal edilemez")
    x.status = "CANCELLED"
    db.commit()
    return pub_out(x)
