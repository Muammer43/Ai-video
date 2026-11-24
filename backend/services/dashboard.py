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
    by_status = {st: n for st, n in db.execute(select(Project.status, func.count()).where(Project.user_id == user_id).group_by(Project.status)).all()}

    def st(*names: str) -> int:
        return sum(by_status.get(n, 0) for n in names)

    today = db.execute(select(func.count()).select_from(Project).where(Project.user_id == user_id, Project.created_at >= d0)).scalar() or 0
    snaps = latest_snapshots(db, user_id)
    views = sum(s.views or 0 for s in snaps)
    inter = sum((s.likes or 0) + (s.comments or 0) + (s.shares or 0) + (s.saves or 0) for s in snaps)
    published = db.execute(select(func.count()).select_from(Publication).where(Publication.user_id == user_id, Publication.status == "PUBLISHED")).scalar() or 0
    start = d0 - timedelta(days=13)
    prod = {str(d)[:10]: n for d, n in db.execute(select(func.date(Project.created_at), func.count()).where(
        Project.user_id == user_id, Project.created_at >= start).group_by(func.date(Project.created_at))).all()}
    pubd = {str(d)[:10]: n for d, n in db.execute(select(func.date(Publication.published_at), func.count()).where(
        Publication.user_id == user_id, Publication.status == "PUBLISHED", Publication.published_at >= start).group_by(func.date(Publication.published_at))).all()}
    series = []
    for i in range(13, -1, -1):
        key = (d0 - timedelta(days=i)).strftime("%Y-%m-%d")
        series.append({"date": key, "produced": prod.get(key, 0), "published": pubd.get(key, 0)})
    stats = db.execute(select(ProviderStat).where(ProviderStat.user_id == user_id)).scalars().all()
    from ..providers import router
    from .credentials import CredentialResolver
    cr = CredentialResolver(db, user_id)
    ctx = type("C", (), {"creds": cr})()
    prov = []
    for p in router.all_providers():
        s_ = next((s for s in stats if s.provider == p.name and s.kind == p.kind), None)
        prov.append({"name": p.name, "kind": p.kind, "label": p.label or p.name, "configured": p.is_configured(ctx),
                     "is_ai": p.is_ai, "offline": p.offline, "calls": s_.calls if s_ else 0,
                     "success_rate": round(s_.successes / s_.calls, 3) if s_ and s_.calls else None,
                     "last_error": (s_.last_error[:120] if s_ and s_.last_error and s_.failures and (not s_.last_success_at or (s_.last_failure_at and s_.last_failure_at > s_.last_success_at)) else "")})
    bud = costs.budget_status(db, user_id)
    avg_cost = float(db.execute(select(func.avg(Project.cost_actual)).where(Project.user_id == user_id, Project.cost_actual > 0)).scalar() or 0)
    return {
        "videos_total": sum(by_status.values()), "videos_today": today,
        "queue": st(Status.QUEUED), "in_progress": st(*Status.RUNNING),
        "completed": st(Status.APPROVED, Status.PUBLISHING, Status.PUBLISHED),
        "failed": st(Status.FAILED), "needs_review": st(Status.NEEDS_REVIEW),
        "ready_to_publish": st(Status.APPROVED), "published_videos": published,
        "total_views": views if snaps else None, "engagement_rate": round(inter / views, 4) if views else None,
        "metrics_note": None if snaps else "Henüz platform metriği toplanmadı (yayınlanmış video ve bağlı hesap gerekir).",
        "cost_today_usd": bud["spent_today_usd"], "cost_month_usd": bud["spent_month_usd"],
        "avg_cost_per_video_usd": round(avg_cost, 4),
        "budget": bud, "providers": prov, "series": series,
    }
