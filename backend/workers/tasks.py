"""Celery görevleri. Her görev idempotent ve izlenebilirdir; proje görevleri Project, diğerleri Task tablosunda izlenir."""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select

from ..core.config import get_settings
from ..core.logging import redact
from ..database.session import create_all, session_scope
from ..models import Project, Status, Task, utcnow
from .celery_app import celery
from .dispatch import dispatch

log = logging.getLogger(__name__)
_init = False


def _ensure_db() -> None:
    global _init
    if not _init:
        if get_settings().database_url.startswith("sqlite"):
            create_all()
        _init = True


@celery.task(name="backend.workers.tasks.run_project_task", bind=True, max_retries=0)
def run_project_task(self, project_id: str) -> dict:  # noqa: ANN001
    _ensure_db()
    from .pipeline import run_project

    with session_scope() as db:
        p = db.get(Project, project_id)
        if p:
            p.celery_task_id = getattr(self.request, "id", "") or p.celery_task_id
    out = run_project(project_id)
    if out.get("status") == "retry":
        dispatch("run_project_task", [project_id], countdown=int(out.get("retry_in", 30)), queue="render")
    return out


# ---------- genel görev izleme ----------
def tracked(task_type: str, user_id: str, payload: dict | None = None, timeout_s: int = 600, idem: str | None = None) -> str:
    with session_scope() as db:
        if idem:
            ex = db.execute(select(Task).where(Task.user_id == user_id, Task.idempotency_key == idem)).scalar_one_or_none()
            if ex:
                return ex.id
        t = Task(user_id=user_id, type=task_type, payload=payload or {}, timeout_s=timeout_s, idempotency_key=idem)
        db.add(t)
        db.flush()
        return t.id


def _run_tracked(task_id: str, fn) -> dict:  # noqa: ANN001
    _ensure_db()
    with session_scope() as db:
        t = db.get(Task, task_id)
        if t is None or t.status in (Status.CANCELLED, Status.PUBLISHED, "DONE") or t.cancel_requested:
            return {"status": "skipped"}
        if t.status == Status.PROCESSING and t.started_at and (utcnow() - t.started_at).total_seconds() < t.timeout_s:
            return {"status": "skipped", "reason": "already_running"}
        t.status, t.started_at, t.attempts, t.progress = Status.PROCESSING, utcnow(), t.attempts + 1, 5
        user_id, payload = t.user_id, dict(t.payload)
    try:
        result = fn(user_id, payload) or {}
        with session_scope() as db:
            t = db.get(Task, task_id)
            t.status, t.progress, t.result, t.finished_at = "DONE", 100, result, utcnow()
        return {"status": "DONE", **result}
    except Exception as e:  # noqa: BLE001
        log.exception("görev hatası %s", task_id)
        with session_scope() as db:
            t = db.get(Task, task_id)
            t.status, t.error, t.finished_at = Status.FAILED, redact(f"{type(e).__name__}: {e}")[:1500], utcnow()
        return {"status": "FAILED", "error": redact(str(e))[:300]}


@celery.task(name="backend.workers.tasks.generate_ideas_task")
def generate_ideas_task(task_id: str) -> dict:
    from ..automation.engine import do_generate_ideas
    return _run_tracked(task_id, do_generate_ideas)


@celery.task(name="backend.workers.tasks.refresh_trends_for_user_task")
def refresh_trends_for_user_task(task_id: str) -> dict:
    from ..automation.engine import do_refresh_trends
    return _run_tracked(task_id, do_refresh_trends)


@celery.task(name="backend.workers.tasks.refresh_trends_task")
def refresh_trends_task() -> dict:
    """Beat: otomasyonu açık kanalı olan kullanıcılar için trend tazele."""
    _ensure_db()
    from ..automation.engine import users_with_automation
    n = 0
    for uid in users_with_automation():
        tid = tracked("trend_research", uid, {}, 300, idem=f"trends:{uid}:{utcnow():%Y%m%d%H}")
        dispatch("refresh_trends_for_user_task", [tid])
        n += 1
    return {"users": n}


@celery.task(name="backend.workers.tasks.scheduler_tick_task")
def scheduler_tick_task() -> dict:
    _ensure_db()
    from ..automation.engine import tick
    return tick()


@celery.task(name="backend.workers.tasks.reap_stuck_task")
def reap_stuck_task() -> dict:
    """Takılı işleri (işçi öldü, mesaj kayboldu) toparla: yeniden kuyruğa al veya başarısız işaretle."""
    _ensure_db()
    s = get_settings()
    now = utcnow()
    requeued = failed = redispatched = 0
    with session_scope() as db:
        stuck = db.execute(select(Project).where(Project.status.in_(list(Status.RUNNING)),
                                                 Project.heartbeat_at < now - timedelta(minutes=s.stuck_job_minutes))).scalars().all()
        for p in stuck:
            if p.attempts < p.max_attempts and not p.cancel_requested:
                p.status, p.stage_message = Status.QUEUED, "Takılı iş tespit edildi, yeniden kuyruğa alındı"
                requeued += 1
            else:
                p.status, p.error, p.error_code, p.finished_at = Status.FAILED, "İşçi yanıt vermedi (zaman aşımı)", "STUCK", now
                failed += 1
        queued = db.execute(select(Project.id).where(Project.status == Status.QUEUED,
                                                      Project.updated_at < now - timedelta(minutes=10))).scalars().all()
    for pid in queued:
        dispatch("run_project_task", [pid], queue="render")
        redispatched += 1
    for pid in [p.id for p in stuck if p.status == Status.QUEUED]:
        dispatch("run_project_task", [pid], queue="render")
    return {"requeued": requeued, "failed": failed, "redispatched": redispatched}


@celery.task(name="backend.workers.tasks.publish_task")
def publish_task(publication_id: str) -> dict:
    _ensure_db()
    from ..services.publishing import run_publication
    return run_publication(publication_id)


@celery.task(name="backend.workers.tasks.publish_due_task")
def publish_due_task() -> dict:
    _ensure_db()
    from ..services.publishing import dispatch_due
    return dispatch_due()


@celery.task(name="backend.workers.tasks.collect_metrics_task")
def collect_metrics_task() -> dict:
    _ensure_db()
    from ..analytics.collector import collect_all
    return collect_all()
