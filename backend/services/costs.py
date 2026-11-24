"""Maliyet defteri, sağlayıcı istatistikleri ve bütçe koruması."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.errors import BudgetExceeded
from ..models import CostEntry, Notification, Project, ProviderStat, utcnow
from .usersettings import get_user_settings, update_user_settings


def record(db: Session, user_id: str, project_id: str | None, provider: str, kind: str, units: float, unit_name: str,
           cost: float, estimated: bool = True, note: str = "") -> CostEntry:
    e = CostEntry(user_id=user_id, project_id=project_id, provider=provider, kind=kind, units=units,
                  unit_name=unit_name, cost_usd=round(cost, 6), estimated=estimated, note=note[:300])
    db.add(e)
    if project_id:
        p = db.get(Project, project_id)
        if p is not None:
            p.cost_actual = round((p.cost_actual or 0.0) + cost, 6)
    db.commit()
    return e


def record_call(db: Session, user_id: str, project_id: str | None, provider: Any, res: Any, seconds: float, ok: bool,
                error: str = "", err_kind: str = "") -> None:
    stat = db.execute(select(ProviderStat).where(ProviderStat.user_id == user_id, ProviderStat.provider == provider.name,
                                                 ProviderStat.kind == provider.kind)).scalar_one_or_none()
    if stat is None:
        stat = ProviderStat(user_id=user_id, provider=provider.name, kind=provider.kind, calls=0, successes=0, failures=0,
                            total_latency_s=0.0, total_cost_usd=0.0, total_output_seconds=0.0, rate_limited=0, last_meta={})
        db.add(stat)
    stat.calls += 1
    stat.total_latency_s += seconds
    if ok and res is not None:
        stat.successes += 1
        stat.last_success_at = utcnow()
        stat.total_cost_usd += res.cost_usd
        if res.meta.get("duration"):
            stat.total_output_seconds += float(res.meta["duration"])
        stat.last_meta = {k: v for k, v in res.meta.items() if k in ("resolution", "duration", "model", "origin", "rate_limit",
                                                                    "price_verified", "price_source")}
        if res.cost_usd or res.units:
            db.add(CostEntry(user_id=user_id, project_id=project_id, provider=provider.name, kind=provider.kind,
                             units=res.units, unit_name=res.unit_name, cost_usd=round(res.cost_usd, 6),
                             estimated=res.cost_estimated, note=("fiyat doğrulanmış" if res.meta.get("price_verified") else "fiyat tahmini")))
            if project_id:
                p = db.get(Project, project_id)
                if p is not None:
                    p.cost_actual = round((p.cost_actual or 0.0) + res.cost_usd, 6)
    else:
        stat.failures += 1
        stat.last_failure_at = utcnow()
        stat.last_error = error[:500]
        if err_kind == "rate_limit":
            stat.rate_limited += 1
    db.commit()


def spend_since(db: Session, user_id: str, since: datetime) -> float:
    v = db.execute(select(func.coalesce(func.sum(CostEntry.cost_usd), 0.0)).where(
        CostEntry.user_id == user_id, CostEntry.created_at >= since)).scalar()
    return float(v or 0.0)


def day_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def budget_status(db: Session, user_id: str) -> dict:
    cfg = get_user_settings(db, user_id)["budget"]
    d = spend_since(db, user_id, day_start())
    m = spend_since(db, user_id, month_start())
    return {
        **cfg,
        "spent_today_usd": round(d, 4), "spent_month_usd": round(m, 4),
        "daily_remaining_usd": round(max(cfg["daily_usd"] - d, 0), 4),
        "monthly_remaining_usd": round(max(cfg["monthly_usd"] - m, 0), 4),
        "daily_pct": round(100 * d / cfg["daily_usd"], 1) if cfg["daily_usd"] else 0,
        "monthly_pct": round(100 * m / cfg["monthly_usd"], 1) if cfg["monthly_usd"] else 0,
    }


def check_budget(db: Session, user_id: str, projected: float = 0.0, project_id: str | None = None,
                 notify_fn=None) -> None:
    """Yeni harcama sınırları aşacaksa BudgetExceeded fırlatır ve üretimi duraklatır (kullanıcıya bildirim)."""
    st = budget_status(db, user_id)
    reasons = []
    if st["paused"]:
        reasons.append(st.get("paused_reason") or "Bütçe nedeniyle üretim duraklatıldı")
    if st["spent_today_usd"] + projected > st["daily_usd"]:
        reasons.append(f"günlük bütçe aşılır (${st['spent_today_usd']:.2f}+${projected:.2f} > ${st['daily_usd']:.2f})")
    if st["spent_month_usd"] + projected > st["monthly_usd"]:
        reasons.append(f"aylık bütçe aşılır (${st['spent_month_usd']:.2f}+${projected:.2f} > ${st['monthly_usd']:.2f})")
    if project_id:
        p = db.get(Project, project_id)
        if p and (p.cost_actual or 0) + projected > st["per_video_usd"]:
            reasons.append(f"video başına sınır aşılır (${(p.cost_actual or 0) + projected:.2f} > ${st['per_video_usd']:.2f})")
    _maybe_alert(db, user_id, st, notify_fn)
    if reasons:
        if not st["paused"] and any("günlük" in r or "aylık" in r for r in reasons):
            update_user_settings(db, user_id, {"budget": {"paused": True, "paused_reason": reasons[0]}})
            if notify_fn:
                notify_fn(db, user_id, "budget", "Bütçe aşıldı — üretim durduruldu", "; ".join(reasons), level="error")
        raise BudgetExceeded("; ".join(reasons), data={"reasons": reasons})


def _maybe_alert(db: Session, user_id: str, st: dict, notify_fn) -> None:
    if not notify_fn:
        return
    pct = max(st["daily_pct"], st["monthly_pct"])
    if pct < st["alert_pct"]:
        return
    since = day_start()
    exists = db.execute(select(Notification.id).where(Notification.user_id == user_id, Notification.kind == "budget_alert",
                                                       Notification.created_at >= since)).first()
    if not exists:
        notify_fn(db, user_id, "budget_alert", f"Bütçe uyarısı: %{pct:.0f} kullanıldı",
                  f"Bugün ${st['spent_today_usd']:.2f} / ${st['daily_usd']:.2f}, bu ay ${st['spent_month_usd']:.2f} / ${st['monthly_usd']:.2f}",
                  level="warning")


def summary(db: Session, user_id: str, days: int = 30) -> dict:
    since = utcnow() - timedelta(days=days)
    rows = db.execute(select(CostEntry.kind, CostEntry.provider, func.sum(CostEntry.cost_usd), func.count()).where(
        CostEntry.user_id == user_id, CostEntry.created_at >= since).group_by(CostEntry.kind, CostEntry.provider)).all()
    by_kind: dict[str, float] = {}
    by_provider: dict[str, float] = {}
    for kind, prov, total, _n in rows:
        by_kind[kind] = round(by_kind.get(kind, 0) + float(total or 0), 4)
        by_provider[prov] = round(by_provider.get(prov, 0) + float(total or 0), 4)
    daily = db.execute(select(func.date(CostEntry.created_at), func.sum(CostEntry.cost_usd)).where(
        CostEntry.user_id == user_id, CostEntry.created_at >= since).group_by(func.date(CostEntry.created_at))
        .order_by(func.date(CostEntry.created_at))).all()
    est = db.execute(select(func.coalesce(func.sum(CostEntry.cost_usd), 0.0)).where(
        CostEntry.user_id == user_id, CostEntry.created_at >= since, CostEntry.estimated.is_(True))).scalar() or 0.0
    return {"days": days, "total_usd": round(sum(by_kind.values()), 4), "by_kind": by_kind, "by_provider": by_provider,
            "daily": [{"date": str(d), "usd": round(float(v or 0), 4)} for d, v in daily],
            "estimated_share_usd": round(float(est), 4),
            "note": "Sağlayıcı maliyeti bildirmediğinde değerler fiyat tablosundan tahmin edilir (estimated=true)."}


def server_cost_entries(db: Session, user_id: str, project_id: str, render_seconds: float, stored_bytes: int) -> None:
    s = get_settings()
    c1 = s.server_cost_per_render_minute_usd * render_seconds / 60
    record(db, user_id, project_id, "server", "server", round(render_seconds / 60, 3), "render_min", c1, True,
           "yapılandırılmış tahmin (ölçüm değil)")
    c2 = s.storage_cost_per_gb_month_usd * stored_bytes / 1e9
    record(db, user_id, project_id, "storage", "storage", round(stored_bytes / 1e9, 4), "GB-ay", c2, True,
           "ilk ay depolama tahmini")
