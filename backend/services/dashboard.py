from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import MetricSnapshot, Project, ProviderStat, Publication, Status, utcnow
from . import costs


def latest_snapshots(db: Session, user_id: str) -> list[MetricSnapshot]:
    sub = select(MetricSnapshot.publication_id, func.max(MetricSnapshot.taken_at).label("t")).where(MetricSnapshot.user_id == user_id).group_by(MetricSnapshot.publication_id).subquery()
    return list(db.execute(select(MetricSnapshot).join(sub, (MetricSnapshot.publication_id == sub.c.publication_id) & (MetricSnapshot.taken_at == sub.c.t))).scalars())


def build(db: Session, user_id: str) -> dict:
    now = utcnow()
    d0 = now.replace(hour=0, minute=0, second=0, microsecond=0)

    def cnt(*conds) -> int:
        return db.execute(select(func.count()).select_from(Project).where(Project.user_id == user_id, *conds)).scalar() or 0

    snaps = latest_snapshots(db, user_id)
    views = sum(s.views or 0 for s in snaps)
    inter = sum((s.likes or 0) + (s.comments or 0) + (s.shares or 0) + (s.saves or 0) for s in snaps)
    published = db.execute(select(func.count()).select_from(Publication).where(Publication.user_id == user_id, Publication.status == "PUBLISHED")).scalar() or 0
    series = []
    for i in range(13, -1, -1):
        a = d0 - timedelta(days=i)
        b = a + timedelta(days=1)
        series.append({"date": a.strftime("%Y-%m-%d"),
                       "produced": cnt(Project.created_at >= a, Project.created_at < b),
                       "published": db.execute(select(func.count()).select_from(Publication).where(
                           Publication.user_id == user_id, Publication.status == "PUBLISHED", Publication.published_at >= a, Publication.published_at < b)).scalar() or 0})
    stats = db.execute(select(ProviderStat).where(ProviderStat.user_id == user_id)).scalars().all()
    from .. import providers  # noqa: F401
    from ..providers import router
    from .credentials import CredentialResolver
    cr = CredentialResolver(db, user_id)
    prov = []
    for p in router.all_providers():
        st = next((s for s in stats if s.provider == p.name and s.kind == p.kind), None)
        prov.append({"name": p.name, "kind": p.kind, "label": p.label or p.name, "configured": p.is_configured(type("C", (), {"creds": cr})()),
                     "is_ai": p.is_ai, "offline": p.offline, "calls": st.calls if st else 0,
                     "success_rate": round(st.successes / st.calls, 3) if st and st.calls else None,
                     "last_error": (st.last_error[:120] if st and st.last_error and st.failures and (not st.last_success_at or (st.last_failure_at and st.last_failure_at > st.last_success_at)) else "")})
    bud = costs.budget_status(db, user_id)
    return {
        "videos_total": cnt(), "videos_today": cnt(Project.created_at >= d0),
        "queue": cnt(Project.status == Status.QUEUED), "in_progress": cnt(Project.status.in_(list(Status.RUNNING))),
        "completed": cnt(Project.status.in_([Status.APPROVED, Status.PUBLISHING, Status.PUBLISHED])),
        "failed": cnt(Project.status == Status.FAILED), "needs_review": cnt(Project.status == Status.NEEDS_REVIEW),
        "ready_to_publish": cnt(Project.status == Status.APPROVED), "published_videos": published,
        "total_views": views if snaps else None, "engagement_rate": round(inter / views, 4) if views else None,
        "metrics_note": None if snaps else "Henüz platform metriği toplanmadı (yayınlanmış video ve bağlı hesap gerekir).",
        "cost_today_usd": bud["spent_today_usd"], "cost_month_usd": bud["spent_month_usd"],
        "avg_cost_per_video_usd": round(float(db.execute(select(func.avg(Project.cost_actual)).where(Project.user_id == user_id, Project.cost_actual > 0)).scalar() or 0), 4),
        "budget": bud, "providers": prov, "series": series,
    }
