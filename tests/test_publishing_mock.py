"""Yayın adaptörleri — MOCK HTTP ile (canlı YouTube/TikTok/Instagram API'siyle test EDİLMEDİ).
Doğrulanan davranış: PUBLISHED yalnızca platform doğrulamasından sonra; token yenileme; hata/yeniden deneme; kısıt bildirimi."""
import time
from datetime import timedelta

import httpx
import pytest

from backend.core.security import encrypt_secret
from backend.database.session import session_scope
from backend.models import Asset, Project, Publication, SocialAccount, utcnow
from backend.providers import http as H
from backend.services.assets import store_asset
from backend.services import publishing as P

from .conftest import make_project


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(P, "VERIFY_INTERVAL_S", 0)


def _setup(user, platform, env, tmp_video, caps=None, expires_in=3600, privacy="public"):
    from backend.core import config
    for k, v in dict(GOOGLE_CLIENT_ID="gid", GOOGLE_CLIENT_SECRET="gs", TIKTOK_CLIENT_KEY="tk", TIKTOK_CLIENT_SECRET="ts",
                     INSTAGRAM_APP_ID="ia", INSTAGRAM_APP_SECRET="is", PUBLIC_BASE_URL="https://factory.example.com").items():
        import os
        os.environ[k] = v
    config.reset_settings_cache()
    pid = make_project(user, platforms=[platform], status="APPROVED", options={"privacy": privacy})
    with session_scope() as db:
        a = store_asset(db, user, pid, "final", tmp_video, duration=15.0, meta={"width": 720, "height": 1280})
        p = db.get(Project, pid)
        p.final_asset_id = a.id
        p.script = {"title": "Test başlık", "description": "Açıklama", "hashtags": ["#a", "b"]}
        acc = SocialAccount(user_id=user, platform=platform, external_id="ext1", display_name="Hesap", status="active",
                            access_token_enc=encrypt_secret("AT"), refresh_token_enc=encrypt_secret("RT"),
                            token_expires_at=utcnow() + timedelta(seconds=expires_in), capabilities=caps or {})
        db.add(acc)
        db.flush()
        db.add(Publication(user_id=user, project_id=pid, account_id=acc.id, platform=platform, variant="", status="QUEUED", title="Test başlık",
                           description="Açıklama", hashtags=["#a", "b"], privacy=privacy))
    return pid


@pytest.fixture()
def video(tmp_path):
    import subprocess
    p = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=360x640:d=2", "-f", "lavfi", "-i", "sine=d=2", "-shortest", str(p)], check=True)
    return p


def _pub(pid):
    with session_scope() as db:
        return db.query(Publication).filter(Publication.project_id == pid).one()


def test_youtube_not_published_until_processed(user, env, video):
    pid = _setup(user, "youtube", env, video)
    states = iter(["uploaded", "processed"])
    log = []

    def h(req: httpx.Request):
        log.append((req.method, str(req.url.path)))
        if req.url.path == "/upload/youtube/v3/videos":
            return httpx.Response(200, headers={"location": "https://upload.example/session1"})
        if req.url.host == "upload.example":
            return httpx.Response(201, json={"id": "VID1"})
        if req.url.path == "/youtube/v3/videos":
            return httpx.Response(200, json={"items": [{"status": {"uploadStatus": next(states), "privacyStatus": "public"}}]})
        return httpx.Response(404)
    H.set_transport_factory(lambda: httpx.MockTransport(h))
    pub = _pub(pid)
    r = P.run_publication(pub.id)
    p = _pub(pid)
    assert r["status"] == "PUBLISHED" and p.status == "PUBLISHED" and p.external_id == "VID1" and p.verified_at
    assert p.external_url.endswith("/shorts/VID1")
    assert log.count(("GET", "/youtube/v3/videos")) == 2  # ilk yanıt 'uploaded' → hemen PUBLISHED yapılmadı
    with session_scope() as db:
        assert db.get(Project, pid).status == "PUBLISHED"


def test_youtube_privacy_downgrade_is_not_published(user, env, video):
    pid = _setup(user, "youtube", env, video)

    def h(req):
        if req.url.path == "/upload/youtube/v3/videos":
            return httpx.Response(200, headers={"location": "https://upload.example/s"})
        if req.url.host == "upload.example":
            return httpx.Response(200, json={"id": "V2"})
        return httpx.Response(200, json={"items": [{"status": {"uploadStatus": "processed", "privacyStatus": "private"}}]})
    H.set_transport_factory(lambda: httpx.MockTransport(h))
    P.run_publication(_pub(pid).id)
    p = _pub(pid)
    assert p.status == "NEEDS_ACTION" and p.effective_privacy == "private" and "denetim" in p.error
    with session_scope() as db:
        assert db.get(Project, pid).status == "NEEDS_REVIEW"


def test_youtube_token_refresh_and_transient_retry(user, env, video):
    pid = _setup(user, "youtube", env, video, expires_in=10)  # süresi dolmak üzere
    calls = {"token": 0}

    def h(req):
        if req.url.host == "oauth2.googleapis.com":
            calls["token"] += 1
            return httpx.Response(200, json={"access_token": "NEW", "expires_in": 3600})
        if req.url.path == "/upload/youtube/v3/videos":
            return httpx.Response(503, json={})
        return httpx.Response(404)
    H.set_transport_factory(lambda: httpx.MockTransport(h))
    r = P.run_publication(_pub(pid).id)
    assert calls["token"] == 1 and r["status"] == "retry"
    p = _pub(pid)
    assert p.status == "QUEUED" and p.attempts == 1 and p.next_attempt_at > utcnow()
    with session_scope() as db:
        from backend.core.security import decrypt_secret
        assert decrypt_secret(db.query(SocialAccount).one().access_token_enc) == "NEW"


def test_tiktok_unaudited_and_privacy_gate(user, env, video):
    pid = _setup(user, "tiktok", env, video)  # herkese açık istendi

    def h(req):
        if "creator_info" in req.url.path:
            return httpx.Response(200, json={"data": {"privacy_level_options": ["SELF_ONLY"], "max_video_post_duration_sec": 600}, "error": {"code": "ok"}})
        return httpx.Response(404)
    H.set_transport_factory(lambda: httpx.MockTransport(h))
    P.run_publication(_pub(pid).id)
    p = _pub(pid)
    assert p.status == "NEEDS_ACTION" and "SELF_ONLY" in p.error  # sessizce özel paylaşılmadı


def test_tiktok_publish_complete_flow(user, env, video):
    pid = _setup(user, "tiktok", env, video)
    seq = iter(["PROCESSING_UPLOAD", "PUBLISH_COMPLETE"])
    seen = {}

    def h(req):
        if "creator_info" in req.url.path:
            return httpx.Response(200, json={"data": {"privacy_level_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"]}, "error": {"code": "ok"}})
        if req.url.path.endswith("/video/init/"):
            import json
            seen["init"] = json.loads(req.content)
            return httpx.Response(200, json={"data": {"publish_id": "PUB1", "upload_url": "https://upload.tiktok.example/u"}, "error": {"code": "ok"}})
        if req.url.host == "upload.tiktok.example":
            seen["range"] = req.headers["content-range"]
            return httpx.Response(201)
        if req.url.path.endswith("/status/fetch/"):
            s = next(seq)
            d = {"status": s}
            if s == "PUBLISH_COMPLETE":
                d["publicaly_available_post_id"] = [7001]
            return httpx.Response(200, json={"data": d, "error": {"code": "ok"}})
        return httpx.Response(404)
    H.set_transport_factory(lambda: httpx.MockTransport(h))
    P.run_publication(_pub(pid).id)
    p = _pub(pid)
    assert p.status == "PUBLISHED" and p.external_id == "7001"
    assert seen["init"]["post_info"]["privacy_level"] == "PUBLIC_TO_EVERYONE" and seen["init"]["post_info"]["is_aigc"] is True
    assert seen["init"]["source_info"]["total_chunk_count"] == 1 and seen["range"].startswith("bytes 0-")


def test_instagram_container_flow_and_https_requirement(user, env, video):
    pid = _setup(user, "instagram", env, video)
    seq = iter(["IN_PROGRESS", "FINISHED"])
    log = []

    def h(req):
        log.append((req.method, req.url.path))
        if req.url.path.endswith("/17841/media") and req.method == "POST":
            body = dict(x.split("=", 1) for x in req.content.decode().split("&"))
            log.append(("body", body["media_type"], body["is_ai_generated"]))
            assert body["video_url"].startswith("https%3A%2F%2Ffactory.example.com")
            return httpx.Response(200, json={"id": "CONT1"})
        if req.url.path.endswith("/CONT1"):
            return httpx.Response(200, json={"status_code": next(seq)})
        if req.url.path.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "MEDIA1"})
        if req.url.path.endswith("/MEDIA1"):
            return httpx.Response(200, json={"id": "MEDIA1", "permalink": "https://www.instagram.com/reel/abc/"})
        return httpx.Response(404, json={})
    with session_scope() as db:
        db.query(SocialAccount).one().external_id = "17841"
    H.set_transport_factory(lambda: httpx.MockTransport(h))
    P.run_publication(_pub(pid).id)
    p = _pub(pid)
    assert p.status == "PUBLISHED" and p.external_url.endswith("/reel/abc/")
    assert ("body", "REELS", "true") in log
    # media_publish yalnızca konteyner FINISHED olduktan sonra çağrıldı
    assert [x for x in log if len(x) == 2 and x[0] in ("POST",)][-1][1].endswith("/media_publish")


def test_instagram_requires_public_https(user, env, video):
    pid = _setup(user, "instagram", env, video)
    import os
    from backend.core import config
    os.environ["PUBLIC_BASE_URL"] = "http://localhost:8000"
    config.reset_settings_cache()
    H.set_transport_factory(lambda: httpx.MockTransport(lambda r: httpx.Response(404)))
    P.run_publication(_pub(pid).id)
    assert _pub(pid).status == "NEEDS_ACTION" and "HTTPS" in _pub(pid).error


def test_no_connected_account_means_not_published(user, env, video):
    pid = make_project(user, platforms=["youtube"], status="APPROVED")
    assert P.enqueue_publications(pid) == 0
    with session_scope() as db:
        assert db.get(Project, pid).status == "APPROVED"  # 'yayınlandı' DEĞİL
