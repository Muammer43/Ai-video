"""Yayınlanmış videoların platform metriklerini periyodik toplar (yalnızca resmî API'ler)."""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select

from ..database.session import session_scope
from ..models import MetricSnapshot, Project, Publication, SocialAccount, utcnow
from ..providers.base import ProviderError
from ..providers.publishing.base import get_publisher
from ..services import oauth
from .learning import conclude_ready_experiments

log = logging.getLogger(__name__)


def _interval(age_h: float) -> timedelta:
    return timedelta(hours=3) if age_h < 48 else timedelta(hours=24) if age_h < 24 * 14 else timedelta(days=3)


def due(pub: Publication, last: MetricSnapshot | None, now) -> bool:  # noqa: ANN001
    age = (now - (pub.published_at or pub.created_at)).total_seconds() / 3600
    if age > 24 * 60:
        return False
    return last is None or now - last.taken_at >= _interval(age)


def collect_one(db, pub: Publication) -> dict:  # noqa: ANN001
    acc = db.get(SocialAccount, pub.account_id)
    proj = db.get(Project, pub.project_id)
    if acc is None or acc.status != "active" or not pub.external_id:
        return {}
    token = oauth.access_token(db, acc)
    m = get_publisher(pub.platform).metrics(token, pub.external_id, float((proj.duration_target if proj else 0) or 0), {"external_id": acc.external_id})
    if not m:
        return {}
    age = ((utcnow() - (pub.published_at or pub.created_at)).total_seconds()) / 3600
    db.add(MetricSnapshot(user_id=pub.user_id, publication_id=pub.id, age_hours=round(age, 2), views=m.get("views"), avg_watch_seconds=m.get("avg_watch_seconds"),
                          completion_rate=m.get("completion_rate"), likes=m.get("likes"), comments=m.get("comments"), shares=m.get("shares"),
                          saves=m.get("saves"), followers_gained=m.get("followers_gained"), raw=m))
    db.commit()
    return m


def collect_all() -> dict:
    now = utcnow()
    ok = failed = skipped = 0
    users = set()
    with session_scope() as db:
        pubs = db.execute(select(Publication).where(Publication.status == "PUBLISHED")).scalars().all()
        for pub in pubs:
            last = db.execute(select(MetricSnapshot).where(MetricSnapshot.publication_id == pub.id)
                              .order_by(MetricSnapshot.taken_at.desc()).limit(1)).scalar_one_or_none()
            if not due(pub, last, now):
                skipped += 1
                continue
            try:
                if collect_one(db, pub):
                    ok += 1
                    users.add(pub.user_id)
                else:
                    skipped += 1
            except ProviderError as e:
                failed += 1
                log.warning("metrik toplama hatası %s/%s: %s", pub.platform, pub.id, e)
            except Exception:  # noqa: BLE001
                failed += 1
                log.exception("metrik toplama beklenmeyen hata")
        for u in users:
            conclude_ready_experiments(db, u)
    return {"collected": ok, "failed": failed, "skipped": skipped}
