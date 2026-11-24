from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.deps import audit, current_user
from ..core.errors import AppError, NotFound
from ..core.security import create_media_token, decode_media_token
from ..database.session import SessionLocal, get_db
from ..models import Asset, JobEvent, Project, Publication, Scene, User
from ..schemas.api import ApproveIn, ProjectCreate, RetryIn
from ..services import projects as svc
from ..services.estimator import estimate_project
from ..services.publishing import enqueue_publications
from ..storage import get_storage

router = APIRouter(tags=["projects"])


def project_out(p: Project, detail: bool = False, db: Session | None = None) -> dict:
    d = {"id": p.id, "topic": p.topic, "category": p.category, "language": p.language, "style": p.style, "aspect_ratio": p.aspect_ratio,
         "resolution": p.resolution, "duration_target": p.duration_target, "quality_tier": p.quality_tier, "media_mode": p.media_mode,
         "platforms": p.platforms, "publish_mode": p.publish_mode, "status": p.status, "stage": p.stage, "stage_message": p.stage_message,
         "progress": p.progress, "cost_estimate": p.cost_estimate, "cost_actual": p.cost_actual, "quality_score": p.quality_score,
         "qc_decision": p.qc_decision, "error": p.error, "error_code": p.error_code, "attempts": p.attempts, "channel_id": p.channel_id,
         "has_video": bool(p.final_asset_id), "has_thumbnail": bool(p.thumbnail_asset_id), "created_at": p.created_at.isoformat(),
         "updated_at": p.updated_at.isoformat(), "finished_at": p.finished_at.isoformat() if p.finished_at else None,
         "title": (p.script or {}).get("title"), "variant": p.variant, "experiment_id": p.experiment_id}
    if detail and db is not None:
        d["script"] = {k: v for k, v in (p.script or {}).items() if not k.startswith("_")}
        d["script_meta"] = (p.script or {}).get("_meta", {})
        d["media_report"] = p.media_report
        d["quality_report"] = p.quality_report
        d["options"] = p.options
        d["voice"] = p.voice
        d["scenes"] = [{"idx": s.idx, "narration": s.narration, "origin": s.origin, "duration": s.duration, "status": s.status,
                        "provider": s.meta.get("media_provider"), "tts_provider": s.meta.get("tts_provider"), "visual_prompt": s.visual_prompt[:400]}
                       for s in db.execute(select(Scene).where(Scene.project_id == p.id).order_by(Scene.idx)).scalars()]
        d["publications"] = [{"id": x.id, "platform": x.platform, "status": x.status, "external_url": x.external_url, "error": x.error,
                              "effective_privacy": x.effective_privacy, "scheduled_at": x.scheduled_at.isoformat() if x.scheduled_at else None,
                              "published_at": x.published_at.isoformat() if x.published_at else None, "attempts": x.attempts}
                             for x in db.execute(select(Publication).where(Publication.project_id == p.id)).scalars()]
    return d


@router.post("/projects/estimate")
def estimate(body: ProjectCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return estimate_project(db, user.id, duration=body.duration, media_mode=body.media_mode, quality_tier=body.quality_tier,
                            aspect_ratio=body.aspect_ratio, resolution=body.resolution)


@router.post("/projects", status_code=202)
def create(body: ProjectCreate, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user),
           idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=120)):
    p, est = svc.create_project(db, user.id, body.to_params(), idempotency_key=idempotency_key)
    audit(db, request, user.id, "project.create", "project", p.id)
    return {"project": project_out(p), "estimate": est, "replayed": bool(est.get("replayed"))}


@router.get("/projects")
def list_projects(status: str | None = None, q: str | None = Query(default=None, max_length=100), limit: int = Query(default=30, ge=1, le=100),
                  offset: int = Query(default=0, ge=0), db: Session = Depends(get_db), user: User = Depends(current_user)):
    cond = [Project.user_id == user.id]
    if status:
        cond.append(Project.status.in_([s.strip().upper() for s in status.split(",")]))
    if q:
        cond.append(Project.topic.ilike(f"%{q}%"))
    total = db.execute(select(func.count()).select_from(Project).where(*cond)).scalar() or 0
    rows = db.execute(select(Project).where(*cond).order_by(desc(Project.created_at)).limit(limit).offset(offset)).scalars().all()
    return {"total": total, "items": [project_out(p) for p in rows]}


@router.get("/projects/{pid}")
def get_one(pid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return project_out(svc.get_project(db, user.id, pid), True, db)


@router.post("/projects/{pid}/cancel")
def cancel(pid: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = svc.cancel_project(db, user.id, pid)
    audit(db, request, user.id, "project.cancel", "project", pid)
    return project_out(p)


@router.post("/projects/{pid}/retry", status_code=202)
def retry(pid: str, body: RetryIn | None = None, request: Request = None, db: Session = Depends(get_db), user: User = Depends(current_user)):  # type: ignore[assignment]
    p = svc.retry_project(db, user.id, pid, reset=bool(body and body.reset))
    audit(db, request, user.id, "project.retry", "project", pid)
    return project_out(p)


@router.post("/projects/{pid}/approve")
def approve(pid: str, body: ApproveIn | None = None, request: Request = None, db: Session = Depends(get_db), user: User = Depends(current_user)):  # type: ignore[assignment]
    p, n = svc.approve_project(db, user.id, pid, override=bool(body and body.override))
    audit(db, request, user.id, "project.approve", "project", pid, override=bool(body and body.override), publications=n)
    msg = f"{n} platform için yayın kuyruğa alındı" if n else "Onaylandı; yayın için bağlı hesap yok (Entegrasyonlar'dan hesap bağlayın)"
    return {"project": project_out(p), "publications_queued": n, "message": msg}


@router.post("/projects/{pid}/reject")
def reject(pid: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = svc.get_project(db, user.id, pid)
    if p.status != "NEEDS_REVIEW":
        raise AppError("Yalnızca incelemedeki işler reddedilebilir", code="conflict", status_code=409)
    p.status = "CANCELLED"
    db.commit()
    audit(db, request, user.id, "project.reject", "project", pid)
    return project_out(p)


@router.delete("/projects/{pid}")
def delete(pid: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    svc.delete_project(db, user.id, pid)
    audit(db, request, user.id, "project.delete", "project", pid)
    return {"ok": True}


@router.get("/projects/{pid}/events")
def events(pid: str, after: int = 0, limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db), user: User = Depends(current_user)):
    svc.get_project(db, user.id, pid)
    rows = db.execute(select(JobEvent).where(JobEvent.project_id == pid, JobEvent.id > after).order_by(JobEvent.id).limit(limit)).scalars().all()
    return [_ev(e) for e in rows]


def _ev(e: JobEvent) -> dict:
    return {"id": e.id, "project_id": e.project_id, "level": e.level, "stage": e.stage, "status": e.status, "progress": e.progress,
            "message": e.message, "created_at": e.created_at.isoformat()}


def _fetch_events(user_id: str, project_id: str | None, after: int) -> tuple[list[dict], dict | None]:
    with SessionLocal() as db:
        q = select(JobEvent).where(JobEvent.user_id == user_id, JobEvent.id > after)
        if project_id:
            q = q.where(JobEvent.project_id == project_id)
        rows = db.execute(q.order_by(JobEvent.id).limit(200)).scalars().all()
        snap = None
        if project_id:
            p = db.get(Project, project_id)
            if p:
                snap = {"status": p.status, "progress": p.progress, "stage": p.stage}
        return [_ev(e) for e in rows], snap


async def _sse(request: Request, user_id: str, project_id: str | None, last: int):
    idle = 0
    while True:
        if await request.is_disconnected():
            return
        evs, snap = await asyncio.to_thread(_fetch_events, user_id, project_id, last)
        for e in evs:
            last = e["id"]
            yield f"id: {e['id']}\nevent: progress\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
        if evs:
            idle = 0
        else:
            idle += 1
            if idle % 10 == 0:
                yield ": ping\n\n"
        if project_id and snap and snap["status"] in ("PUBLISHED", "FAILED", "CANCELLED", "NEEDS_REVIEW", "APPROVED") and not evs:
            yield f"event: end\ndata: {json.dumps(snap)}\n\n"
            return
        await asyncio.sleep(1.0)


@router.get("/projects/{pid}/stream")
async def stream(pid: str, request: Request, last_event_id: int | None = Header(default=None, alias="Last-Event-ID"), after: int = 0,
                 user: User = Depends(current_user)):
    with SessionLocal() as db:
        svc.get_project(db, user.id, pid)
    return StreamingResponse(_sse(request, user.id, pid, last_event_id or after), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/events/stream")
async def stream_all(request: Request, after: int = 0, user: User = Depends(current_user)):
    return StreamingResponse(_sse(request, user.id, None, after), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- medya ----------
def _asset_for(db: Session, user_id: str, asset_id: str | None) -> Asset:
    a = db.get(Asset, asset_id) if asset_id else None
    if a is None or a.user_id != user_id:
        raise NotFound("Dosya bulunamadı")
    return a


@router.get("/projects/{pid}/media")
def media_links(pid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = svc.get_project(db, user.id, pid)
    out = {}
    for name, aid in (("video", p.final_asset_id), ("thumbnail", p.thumbnail_asset_id)):
        if aid:
            a = db.get(Asset, aid)
            out[name] = {"path": f"/api/v1/media/{create_media_token(user.id, a.storage_key)}", "mime": a.mime, "size": a.size, "duration": a.duration,
                         "expires_in": get_settings().signed_url_ttl_seconds}
    subs = db.execute(select(Asset).where(Asset.project_id == pid, Asset.kind == "subtitle")).scalars().all()
    out["subtitles"] = [{"name": s.storage_key.rsplit(".", 1)[-1], "path": f"/api/v1/media/{create_media_token(user.id, s.storage_key)}"} for s in subs]
    return out


@router.get("/media/{token}")
def media(token: str, db: Session = Depends(get_db)):
    """İmzalı, kısa ömürlü, kullanıcıya bağlı dosya erişimi (video oynatıcı / Instagram'ın indirmesi için)."""
    p = decode_media_token(token)
    a = db.execute(select(Asset).where(Asset.storage_key == p["key"], Asset.user_id == p["sub"])).scalar_one_or_none()
    if a is None:
        raise NotFound("Dosya bulunamadı")
    st = get_storage()
    url = st.presigned_url(a.storage_key, 600)
    if url:
        return RedirectResponse(url, status_code=307)
    lp = st.local_path(a.storage_key)
    if lp is None:
        raise NotFound("Dosya depoda yok")
    return FileResponse(lp, media_type=a.mime or "application/octet-stream")


@router.get("/assets/{asset_id}/download")
def download(asset_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    a = _asset_for(db, user.id, asset_id)
    st = get_storage()
    fname = f"ai_video_{a.project_id or a.id}.{a.storage_key.rsplit('.', 1)[-1]}"
    url = st.presigned_url(a.storage_key, 600, fname)
    if url:
        return RedirectResponse(url, status_code=307)
    return FileResponse(st.local_path(a.storage_key), media_type=a.mime, filename=fname)


@router.post("/projects/{pid}/publish", status_code=202)
def publish_now(pid: str, body: ApproveIn | None = None, request: Request = None, db: Session = Depends(get_db), user: User = Depends(current_user)):  # type: ignore[assignment]
    p, n = svc.approve_project(db, user.id, pid, override=bool(body and body.override))
    audit(db, request, user.id, "project.publish", "project", pid, publications=n)
    return {"publications_queued": n, "message": "Yayın kuyruğa alındı" if n else "Bağlı hesap yok: yayın yapılmadı"}
