"""Pipeline/servisler için ortak çalışma bağlamı: CallContext, bütçe koruması, iptal denetimi."""
from __future__ import annotations

from pathlib import Path

from ..core.errors import BudgetExceeded, Cancelled, DeadlineExceeded
from ..database.session import session_scope
from ..models import Project, utcnow
from ..providers.base import CallContext
from . import costs
from .credentials import CredentialResolver
from .events import heartbeat
from .notifications import notify
from .usersettings import get_user_settings


def budget_guard(user_id: str, project_id: str | None):
    def guard(est: float) -> None:
        with session_scope() as db:
            costs.check_budget(db, user_id, est, project_id, notify_fn=notify)
    return guard


def cancel_checker(project_id: str):
    def check() -> None:
        with session_scope() as db:
            p = db.get(Project, project_id)
            if p is None:
                return
            if p.cancel_requested or p.status == "CANCELLED":
                raise Cancelled()
            if p.started_at and (utcnow() - p.started_at).total_seconds() > _deadline_s():
                raise DeadlineExceeded()
    return check


def _deadline_s() -> int:
    from ..core.config import get_settings
    return get_settings().project_deadline_minutes * 60


def make_ctx(user_id: str | None, project_id: str | None, work: Path) -> CallContext:
    with session_scope() as db:
        creds = CredentialResolver(db, user_id)
        # önbelleği doldur: oturum kapandıktan sonra da çalışsın
        for name in ("openai", "anthropic", "fal", "runway", "replicate", "elevenlabs", "pexels", "pixabay", "youtube_data"):
            creds.get(name)
        settings = get_user_settings(db, user_id) if user_id else {}
    creds.db = None  # oturum kapandı; yalnızca önbellek kullanılır
    ctx = CallContext(user_id=user_id, project_id=project_id, creds=creds, work_dir=work, settings=settings)
    if project_id:
        ctx.cancel_check = cancel_checker(project_id)
        ctx.heartbeat = lambda: heartbeat(project_id)
    return ctx
