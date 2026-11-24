"""Proje durum güncellemeleri ve olay akışı (SSE'nin kaynağı). Her çağrı kısa ömürlü kendi oturumunu kullanır."""
from __future__ import annotations

from typing import Any

from sqlalchemy import update

from ..database.session import session_scope
from ..models import JobEvent, Project, utcnow
from ..core.logging import redact


def emit(project_id: str, message: str, *, level: str = "info", stage: str | None = None,
         data: dict | None = None, **project_fields: Any) -> None:
    """Olay yaz + (varsa) proje alanlarını güncelle."""
    with session_scope() as db:
        p = db.get(Project, project_id)
        if p is None:
            return
        for k, v in project_fields.items():
            setattr(p, k, v)
        if stage:
            p.stage = stage
        p.stage_message = redact(message)[:300]
        p.heartbeat_at = utcnow()
        db.add(JobEvent(user_id=p.user_id, project_id=project_id, level=level, stage=stage or p.stage,
                        status=p.status, progress=p.progress, message=redact(message)[:2000], data=data or {}))


def set_fields(project_id: str, **fields: Any) -> None:
    with session_scope() as db:
        db.execute(update(Project).where(Project.id == project_id).values(**fields, updated_at=utcnow()))


def heartbeat(project_id: str) -> None:
    set_fields(project_id, heartbeat_at=utcnow())
