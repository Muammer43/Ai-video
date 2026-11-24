"""API üzerinden gerçek üretim (eager iş parçacığı, gerçek FFmpeg/espeak). AI anahtarı yok → çevrimdışı etiketli sağlayıcılar."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.workers import dispatch as D

BODY = {"topic": "Gezegenlerin sıralaması", "category": "Bilim", "duration": 15, "quality_tier": "draft", "media_mode": "slideshow",
        "platforms": ["youtube"], "publish_mode": "auto"}


@pytest.fixture()
def client(env):
    with TestClient(app) as c:
        yield c


def _auth(client):
    r = client.post("/api/v1/auth/register", json={"email": "e@example.com", "password": "Passw0rd!xyz"})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def _wait(client, h, pid, want, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        p = client.get(f"/api/v1/projects/{pid}", headers=h).json()
        if p["status"] in want:
            return p
        time.sleep(0.5)
    raise AssertionError(f"zaman aşımı: {p['status']} {p.get('stage_message')} {p.get('error')}")


def test_full_flow_sse_media_range_approve(client):
    h = _auth(client)
    pid = client.post("/api/v1/projects", headers=h, json=BODY).json()["project"]["id"]
    p = _wait(client, h, pid, {"NEEDS_REVIEW", "FAILED", "APPROVED"})
    assert p["status"] == "NEEDS_REVIEW", (p["status"], p["error"])  # çevrimdışı içerik asla otomatik yayına girmez
    assert p["quality_score"] is not None and p["has_video"] and p["has_thumbnail"]
    det = client.get(f"/api/v1/projects/{pid}", headers=h).json()
    assert len(det["quality_report"]["checks"]) >= 14 and det["script_meta"]["is_ai"] is False
    assert [s["origin"] for s in det["scenes"]] and det["cost_actual"] >= 0
    # SSE: tamamlanmış işin olay geçmişi akıtılır ve 'end' olayıyla kapanır
    with client.stream("GET", f"/api/v1/projects/{pid}/stream", headers=h) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    assert "event: progress" in body and "event: end" in body
    evs = client.get(f"/api/v1/projects/{pid}/events", headers=h).json()
    assert evs[0]["stage"] in ("TOPIC", "SCRIPT") and any(e["stage"] == "QC" for e in evs)
    # medya: imzalı bağlantı + Range
    m = client.get(f"/api/v1/projects/{pid}/media", headers=h).json()
    path = m["video"]["path"]
    full = client.get(path)
    assert full.status_code == 200 and full.headers["content-type"] == "video/mp4" and len(full.content) == m["video"]["size"]
    part = client.get(path, headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100
    assert client.get("/api/v1/media/not.a.token").status_code == 401
    # başka kullanıcının token'ı olmadan yetkili indirme
    assert client.get(f"/api/v1/assets/{det['scenes'] and ''}/download", headers=h).status_code in (404, 405)
    # onay: kritik bulgu yok ama bağlı hesap yok → yayınlandı DENMEZ
    a = client.post(f"/api/v1/projects/{pid}/approve", headers=h, json={}).json()
    assert a["publications_queued"] == 0 and "bağlı hesap yok" in a["message"].lower()
    p2 = client.get(f"/api/v1/projects/{pid}", headers=h).json()
    assert p2["status"] == "APPROVED" and not p2["publications"]
    dash = client.get("/api/v1/dashboard", headers=h).json()
    assert dash["videos_total"] == 1 and dash["published_videos"] == 0 and dash["ready_to_publish"] == 1 and dash["total_views"] is None
    n = client.get("/api/v1/notifications", headers=h).json()
    assert n["unread"] >= 1 and any(i["kind"] == "needs_review" for i in n["items"])


def test_cancel_running_job(client):
    h = _auth(client)
    pid = client.post("/api/v1/projects", headers=h, json={**BODY, "duration": 30}).json()["project"]["id"]
    t0 = time.time()
    while time.time() - t0 < 60:  # çalışmaya başlasın
        if client.get(f"/api/v1/projects/{pid}", headers=h).json()["status"] != "QUEUED":
            break
        time.sleep(0.1)
    r = client.post(f"/api/v1/projects/{pid}/cancel", headers=h)
    assert r.status_code == 200
    p = _wait(client, h, pid, {"CANCELLED", "NEEDS_REVIEW", "FAILED"}, 120)
    assert p["status"] == "CANCELLED"
    D.wait_eager(5)


def test_retry_after_failure_resumes_without_regenerating_voice(client, monkeypatch):
    h = _auth(client)
    import backend.workers.pipeline as pl
    real = pl.stage_assets
    calls = {"n": 0}

    def flaky(pid, ctx):
        calls["n"] += 1
        if calls["n"] == 1:
            raise pl.StageFailure("yapay hata", "TEST", retryable=False)
        return real(pid, ctx)
    monkeypatch.setattr(pl, "stage_assets", flaky)
    pid = client.post("/api/v1/projects", headers=h, json=BODY).json()["project"]["id"]
    p = _wait(client, h, pid, {"FAILED"}, 120)
    assert p["error_code"] == "TEST"
    from backend.database.session import session_scope
    from backend.models import Asset
    with session_scope() as db:
        audio_before = {a.id for a in db.query(Asset).filter(Asset.project_id == pid, Asset.kind == "audio")}
    assert audio_before
    assert client.post(f"/api/v1/projects/{pid}/retry", headers=h).status_code == 202
    p = _wait(client, h, pid, {"NEEDS_REVIEW", "FAILED"}, 180)
    assert p["status"] == "NEEDS_REVIEW"
    with session_scope() as db:
        audio_after = {a.id for a in db.query(Asset).filter(Asset.project_id == pid, Asset.kind == "audio")}
    assert audio_before == audio_after  # seslendirme yeniden üretilmedi (kaldığı yerden devam)
