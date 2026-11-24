"""Otomasyon motoru: kanal zamanlayıcı (tick), fikir üretimi, trend yenileme, deney varyant ataması."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from ..core.errors import BudgetExceeded
from ..database.session import session_scope
from ..models import Channel, Experiment, Idea, Project, Status, utcnow
from ..providers import router
from ..services import costs
from ..services.content import generate_ideas
from ..services.notifications import notify
from ..services.projects import create_project
from ..services.runtime import make_ctx
from ..services.trends import recent_trends, refresh_trends
from ..services.usersettings import get_user_settings
from ..core.config import get_settings
from pathlib import Path

log = logging.getLogger(__name__)
MAX_ACTIVE_PER_CHANNEL = 2


def users_with_automation() -> list[str]:
    with session_scope() as db:
        return [u for (u,) in db.execute(select(Channel.user_id).where(Channel.automation_enabled.is_(True)).distinct())]


def _work(uid: str) -> Path:
    return Path(get_settings().work_dir) / f"auto_{uid}"


def do_refresh_trends(user_id: str, payload: dict) -> dict:
    with session_scope() as db:
        cats = payload.get("categories") or sorted({c.category for c in db.execute(select(Channel).where(Channel.user_id == user_id)).scalars()}) or ["Teknoloji"]
        ctx = make_ctx(user_id, None, _work(user_id))
        return refresh_trends(db, user_id, cats, ctx.creds)


def do_generate_ideas(user_id: str, payload: dict) -> dict:
    from ..analytics.learning import learning_priors
    category = payload.get("category", "Genel")
    with session_scope() as db:
        trends = [{"title": t.title, "source": t.source, "metrics": t.metrics} for t in recent_trends(db, user_id, category, limit=12)]
        priors = learning_priors(db, user_id)
        ctx = make_ctx(user_id, None, _work(user_id))
        ideas = generate_ideas(db, ctx, user_id, category=category, count=int(payload.get("count", 5)), channel_id=payload.get("channel_id"),
                               trends=trends, language=payload.get("language", "tr"), priors=priors)
        return {"idea_ids": [i.id for i in ideas], "used_real_trends": bool(trends), "provider": ideas[0].source.get("provider") if ideas else None}


def _next_slot(hours: list[int], now: datetime, taken: list[datetime]) -> datetime | None:
    """posting_hours (UTC saat) içinde sıradaki boş yayın zamanı."""
    if not hours:
        return None
    for d in range(0, 3):
        for h in sorted(hours):
            slot = (now + timedelta(days=d)).replace(hour=h, minute=0, second=0, microsecond=0)
            if slot > now + timedelta(minutes=5) and all(abs((slot - t).total_seconds()) > 1800 for t in taken):
                return slot
    return None


def _assign_variant(db, ch: Channel) -> tuple[str | None, str, dict]:
    ex = db.execute(select(Experiment).where(Experiment.user_id == ch.user_id, Experiment.status == "running",
                                             (Experiment.channel_id == ch.id) | (Experiment.channel_id.is_(None)))
                    .order_by(Experiment.created_at)).scalars().first()
    if not ex:
        return None, "", {}
    counts = {v: db.execute(select(func.count()).select_from(Project).where(Project.experiment_id == ex.id, Project.variant == v)).scalar() or 0
              for v in ex.variants}
    v = min(counts, key=lambda k: (counts[k], k))  # dengeli dağıtım
    return ex.id, v, dict(ex.variants[v].get("params", {}))


def tick() -> dict:
    """Her dakika: açık kanallar için günlük hedefe göre yeni proje başlat. Bütçe/duraklatma/aktif iş sınırına uyar."""
    now = utcnow()
    created, skipped = 0, []
    with session_scope() as db:
        chans = db.execute(select(Channel).where(Channel.automation_enabled.is_(True))).scalars().all()
        for ch in chans:
            try:
                st = get_user_settings(db, ch.user_id)
                if st["automation"]["paused"]:
                    skipped.append((ch.id, "otomasyon duraklatıldı"))
                    continue
                if st["budget"]["paused"]:
                    skipped.append((ch.id, "bütçe duraklatıldı"))
                    continue
                day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
                today = db.execute(select(func.count()).select_from(Project).where(Project.channel_id == ch.id, Project.created_at >= day0)).scalar() or 0
                active = db.execute(select(func.count()).select_from(Project).where(Project.channel_id == ch.id, Project.status.in_(list(Status.ACTIVE)))).scalar() or 0
                if today >= ch.videos_per_day or active >= MAX_ACTIVE_PER_CHANNEL:
                    continue
                idea = db.execute(select(Idea).where(Idea.user_id == ch.user_id, Idea.channel_id == ch.id, Idea.status == "new")
                                  .order_by(Idea.score.desc())).scalars().first()
                if idea is None:
                    from ..workers.tasks import tracked
                    from ..workers.dispatch import dispatch
                    tid = tracked("idea_generation", ch.user_id, {"category": ch.category, "channel_id": ch.id, "language": ch.language, "count": 6},
                                  300, idem=f"ideas:{ch.id}:{now:%Y%m%d%H}")
                    dispatch("generate_ideas_task", [tid])
                    skipped.append((ch.id, "fikir üretimi başlatıldı"))
                    continue
                exp_id, variant, vparams = _assign_variant(db, ch)
                opts = {**(ch.brand or {}).get("options", {}), **vparams}
                from ..models import Publication
                pending_slots = [t for (t,) in db.execute(select(Publication.scheduled_at).where(Publication.user_id == ch.user_id, Publication.scheduled_at.is_not(None), Publication.status == "QUEUED"))]
                pending_slots += [datetime.fromisoformat(po["publish_at"]) for (po,) in db.execute(select(Project.options).where(Project.channel_id == ch.id, Project.status.in_(list(Status.ACTIVE))))if po and po.get("publish_at")]
                slot = _next_slot(ch.posting_hours or [], now, pending_slots)
                if slot:
                    opts["publish_at"] = slot.isoformat()
                params = dict(topic=idea.title, category=idea.category or ch.category, language=ch.language, style=ch.style, aspect_ratio=ch.aspect_ratio,
                              resolution=ch.resolution, duration=int(vparams.get("duration", ch.duration)), quality_tier=ch.quality_tier,
                              media_mode=ch.media_mode, voice=ch.voice or {}, options=opts, platforms=ch.platforms or [],
                              publish_mode="auto" if ch.auto_publish else "manual", channel_id=ch.id, idea_id=idea.id, experiment_id=exp_id, variant=variant)
                create_project(db, ch.user_id, params, idempotency_key=f"auto:{ch.id}:{idea.id}")
                ch.last_run_at = now
                created += 1
            except BudgetExceeded as e:
                skipped.append((ch.id, f"bütçe: {e.message[:80]}"))
            except Exception as e:  # noqa: BLE001
                log.exception("otomasyon tick hatası kanal=%s", ch.id)
                skipped.append((ch.id, f"hata: {type(e).__name__}"))
                db.rollback()
        db.commit()
    return {"created": created, "skipped": skipped}


def run_channel_now(db, user_id: str, channel_id: str) -> dict:
    """Kanal için hemen bir proje başlat (günlük sınır görmezden gelinir; bütçe/duraklatma kuralları geçerli)."""
    ch = db.get(Channel, channel_id)
    if ch is None or ch.user_id != user_id:
        from ..core.errors import NotFound
        raise NotFound("Kanal bulunamadı")
    idea = db.execute(select(Idea).where(Idea.user_id == user_id, Idea.channel_id == ch.id, Idea.status == "new").order_by(Idea.score.desc())).scalars().first()
    if idea is None:
        from ..workers.tasks import tracked
        from ..workers.dispatch import dispatch
        tid = tracked("idea_generation", user_id, {"category": ch.category, "channel_id": ch.id, "language": ch.language, "count": 5}, 300)
        dispatch("generate_ideas_task", [tid])
        return {"started": False, "task_id": tid, "message": "Önce fikir üretiliyor; tamamlanınca tekrar deneyin veya otomasyon sürdürsün"}
    exp_id, variant, vparams = _assign_variant(db, ch)
    params = dict(topic=idea.title, category=idea.category or ch.category, language=ch.language, style=ch.style, aspect_ratio=ch.aspect_ratio,
                  resolution=ch.resolution, duration=int(vparams.get("duration", ch.duration)), quality_tier=ch.quality_tier, media_mode=ch.media_mode,
                  voice=ch.voice or {}, options={**(ch.brand or {}).get("options", {}), **vparams}, platforms=ch.platforms or [],
                  publish_mode="auto" if ch.auto_publish else "manual", channel_id=ch.id, idea_id=idea.id, experiment_id=exp_id, variant=variant)
    p, est = create_project(db, user_id, params)
    return {"started": True, "project_id": p.id, "estimate": est}
