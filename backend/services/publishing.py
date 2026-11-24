"""Yayın kuyruğu. PUBLISHED yalnızca platform doğrulaması (verify) 'published' döndürürse yazılır."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import and_, or_, select, update

from ..core.config import get_settings
from ..core.logging import redact
from ..core.security import create_media_token
from ..database.session import session_scope
from ..models import Asset, Project, PubStatus, Publication, SocialAccount, Status, utcnow
from ..providers.base import ProviderError
from ..providers.publishing.base import PublishRequest, get_publisher
from ..storage import get_storage
from ..workers.dispatch import dispatch
from . import oauth
from .events import emit
from .notifications import notify

log = logging.getLogger(__name__)
VERIFY_WAIT_S = 240
VERIFY_INTERVAL_S = 8


def _is_synthetic(p: Project) -> bool:
    return True  # üretim hattındaki görsel/video/ses her zaman AI veya sentetik öğe içerir: platform beyanı için doğru taraf


def enqueue_publications(project_id: str, force: bool = False) -> int:
    """Projenin platformları için bağlı hesaplara yayın kayıtları oluşturur. Bağlı hesap yoksa 0 döner (yayınlandı DENMEZ)."""
    created = 0
    with session_scope() as db:
        p = db.get(Project, project_id)
        accounts = db.execute(select(SocialAccount).where(SocialAccount.user_id == p.user_id, SocialAccount.status == "active",
                                                          SocialAccount.platform.in_(p.platforms or []))).scalars().all()
        script = p.script or {}
        sched = None
        if (p.options or {}).get("publish_at"):
            try:
                sched = datetime.fromisoformat(p.options["publish_at"])
            except ValueError:
                sched = None
        privacy = (p.options or {}).get("privacy", "public")
        for acc in accounts:
            if acc.channel_id and p.channel_id and acc.channel_id != p.channel_id:
                continue
            exists = db.execute(select(Publication).where(Publication.project_id == p.id, Publication.account_id == acc.id,
                                                          Publication.variant == (p.variant or ""))).scalar_one_or_none()
            if exists:
                continue
            title = script.get("title") or p.topic
            db.add(Publication(user_id=p.user_id, project_id=p.id, account_id=acc.id, platform=acc.platform, variant=p.variant or "", status=PubStatus.QUEUED,
                               title=title[:100], description=script.get("description", ""), hashtags=script.get("hashtags", []), privacy=privacy,
                               scheduled_at=sched))
            created += 1
        if created:
            p.status, p.progress = Status.PUBLISHING, 97
            db.flush()
            pub_ids = [x for (x,) in db.execute(select(Publication.id).where(Publication.project_id == p.id, Publication.status == PubStatus.QUEUED,
                                                                              or_(Publication.scheduled_at.is_(None), Publication.scheduled_at <= utcnow())))]
    if created:
        emit(project_id, f"{created} platform için yayın kuyruğa alındı", stage="PUBLISH", status=Status.PUBLISHING, progress=97)
        for pid in pub_ids:
            dispatch("publish_task", [pid])
    return created


def dispatch_due() -> dict:
    """Beat: zamanı gelen ve yeniden deneme zamanı gelen yayınları gönder; takılı UPLOADING kayıtlarını toparla."""
    now = utcnow()
    n = 0
    with session_scope() as db:
        db.execute(update(Publication).where(Publication.status.in_([PubStatus.UPLOADING, PubStatus.PROCESSING]),
                                             Publication.next_attempt_at < now - timedelta(minutes=30)).values(status=PubStatus.QUEUED))
        ids = [x for (x,) in db.execute(select(Publication.id).where(
            Publication.status == PubStatus.QUEUED, or_(Publication.scheduled_at.is_(None), Publication.scheduled_at <= now),
            or_(Publication.next_attempt_at.is_(None), Publication.next_attempt_at <= now)))]
    for i in ids:
        dispatch("publish_task", [i])
        n += 1
    return {"dispatched": n}


def _claim(pub_id: str) -> bool:
    with session_scope() as db:
        r = db.execute(update(Publication).where(Publication.id == pub_id, Publication.status.in_([PubStatus.QUEUED, PubStatus.PROCESSING]))
                       .values(status=PubStatus.UPLOADING, attempts=Publication.attempts + 1, next_attempt_at=utcnow()))
        return r.rowcount == 1


def _set(pub_id: str, **f) -> None:
    with session_scope() as db:
        db.execute(update(Publication).where(Publication.id == pub_id).values(**f))


def run_publication(pub_id: str) -> dict:
    if not _claim(pub_id):
        return {"status": "skipped"}
    with session_scope() as db:
        pub = db.get(Publication, pub_id)
        acc = db.get(SocialAccount, pub.account_id)
        proj = db.get(Project, pub.project_id)
        if acc is None or acc.status != "active":
            _set(pub_id, status=PubStatus.NEEDS_ACTION, error="Hesap aktif değil — yeniden bağlayın")
            _refresh_project(proj.id)
            return {"status": PubStatus.NEEDS_ACTION}
        pdata = dict(id=pub.id, state=dict(pub.state or {}), attempts=pub.attempts, max=pub.max_attempts, title=pub.title, desc=pub.description,
                     tags=list(pub.hashtags or []), privacy=pub.privacy, user_id=pub.user_id, project_id=proj.id)
        adata = dict(external_id=acc.external_id, capabilities=dict(acc.capabilities or {}), platform=acc.platform)
        fa = db.get(Asset, proj.final_asset_id)
        ta = db.get(Asset, proj.thumbnail_asset_id) if proj.thumbnail_asset_id else None
        key, tkey = fa.storage_key, (ta.storage_key if ta else None)
        dur = fa.duration or 0.0
        vertical = (fa.meta or {}).get("height", 1) > (fa.meta or {}).get("width", 0)
        try:
            token = oauth.access_token(db, acc)
        except ProviderError as e:
            return _handle_error(pdata, e)
    pub_impl = get_publisher(adata["platform"])
    st = get_storage()
    tmp = Path(get_settings().work_dir) / f"pub_{pub_id}"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        local = st.local_path(key) or st.get_file(key, tmp / "video.mp4")
        public_url = None
        if pub_impl.needs_public_url:
            public_url = st.presigned_url(key, 3 * 3600) or (
                f"{get_settings().public_base_url.rstrip('/')}/api/v1/media/{create_media_token(pdata['user_id'], key, 3 * 3600)}")
        cover_url = None
        if tkey and pub_impl.needs_public_url:
            cover_url = st.presigned_url(tkey, 3 * 3600) or f"{get_settings().public_base_url.rstrip('/')}/api/v1/media/{create_media_token(pdata['user_id'], tkey, 3 * 3600)}"
        req = PublishRequest(access_token=token, video_path=Path(local), title=pdata["title"], description=pdata["desc"], hashtags=pdata["tags"],
                             privacy=pdata["privacy"], duration=dur, vertical=vertical, synthetic=True, account=adata, public_video_url=public_url,
                             cover_url=cover_url, state=pdata["state"])
        state = pub_impl.publish(req)
        _set(pub_id, state=state, status=PubStatus.PROCESSING)
        deadline = time.monotonic() + VERIFY_WAIT_S
        while True:
            res = pub_impl.verify(req, state)
            state = {**state, **(res.state or {})}
            _set(pub_id, state=state)
            if res.status == "published":
                _set(pub_id, status=PubStatus.PUBLISHED, external_id=res.external_id, external_url=res.url, effective_privacy=res.effective_privacy,
                     verified_at=utcnow(), published_at=utcnow(), error="")
                _on_success(pdata, adata, res)
                return {"status": PubStatus.PUBLISHED, "external_id": res.external_id}
            if res.status == "needs_action":
                _set(pub_id, status=PubStatus.NEEDS_ACTION, external_id=res.external_id, external_url=res.url, effective_privacy=res.effective_privacy,
                     error=res.detail)
                _notify(pdata, "Yayın için işlem gerekli", res.detail, "warning")
                _refresh_project(pdata["project_id"])
                return {"status": PubStatus.NEEDS_ACTION}
            if res.status == "failed":
                raise ProviderError(res.detail or "platform yayını reddetti", "permanent")
            if time.monotonic() > deadline:  # platform hâlâ işliyor: sonra yeniden doğrula (PUBLISHED DEĞİL)
                _set(pub_id, status=PubStatus.PROCESSING, next_attempt_at=utcnow() + timedelta(minutes=3), error=res.detail)
                return {"status": PubStatus.PROCESSING, "detail": res.detail}
            time.sleep(VERIFY_INTERVAL_S)
    except ProviderError as e:
        return _handle_error(pdata, e)
    except Exception as e:  # noqa: BLE001
        log.exception("yayın hatası")
        return _handle_error(pdata, ProviderError(f"{type(e).__name__}: {e}", "transient"))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _handle_error(pdata: dict, e: ProviderError) -> dict:
    msg = redact(str(e))[:500]
    pid = pdata["id"]
    if e.kind == "needs_action":
        _set(pid, status=PubStatus.NEEDS_ACTION, error=msg)
        _notify(pdata, "Yayın için işlem gerekli", msg, "warning")
    elif e.kind in ("transient", "rate_limit") and pdata["attempts"] < pdata["max"]:
        delay = min(60 * (2 ** (pdata["attempts"] - 1)), 1800)
        _set(pid, status=PubStatus.QUEUED, error=msg, next_attempt_at=utcnow() + timedelta(seconds=delay))
        return {"status": "retry", "in": delay}
    else:
        _set(pid, status=PubStatus.FAILED, error=msg)
        _notify(pdata, "Yayın başarısız", msg, "error")
    _refresh_project(pdata["project_id"])
    return {"status": "failed", "error": msg}


def _notify(pdata: dict, title: str, body: str, level: str) -> None:
    with session_scope() as db:
        notify(db, pdata["user_id"], "publish", title, body[:300], level=level, data={"project_id": pdata["project_id"], "publication_id": pdata["id"]})


def _on_success(pdata: dict, adata: dict, res) -> None:  # noqa: ANN001
    _refresh_project(pdata["project_id"])
    _notify(pdata, f"Yayınlandı ({adata['platform']})", res.url or pdata["title"], "info")


def _refresh_project(project_id: str) -> None:
    """Tüm yayınlar bitince proje durumunu kaydet."""
    with session_scope() as db:
        pubs = db.execute(select(Publication).where(Publication.project_id == project_id)).scalars().all()
        if not pubs or any(x.status in (PubStatus.QUEUED, PubStatus.UPLOADING, PubStatus.PROCESSING) for x in pubs):
            return
        p = db.get(Project, project_id)
        ok = [x for x in pubs if x.status == PubStatus.PUBLISHED]
        if ok:
            p.status, p.progress = Status.PUBLISHED, 100
            p.stage_message = f"{len(ok)}/{len(pubs)} platformda yayınlandı (platform doğrulamalı)"
        elif any(x.status == PubStatus.NEEDS_ACTION for x in pubs):
            p.status, p.stage_message = Status.NEEDS_REVIEW, "Yayın için kullanıcı işlemi gerekli"
        else:
            p.status, p.error, p.error_code, p.stage_message = Status.FAILED, "; ".join(x.error for x in pubs if x.error)[:1000], "PUBLISH_FAILED", "Yayın başarısız"
        db.commit()
