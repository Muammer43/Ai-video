import json
import time

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.workers import dispatch as D


@pytest.fixture()
def client(env):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def no_dispatch(monkeypatch):
    sent = []
    monkeypatch.setattr("backend.services.projects.dispatch", lambda *a, **k: sent.append(a) or "t1")
    return sent


def register(client, email="a@example.com", pw="Passw0rd!xyz"):
    r = client.post("/api/v1/auth/register", json={"email": email, "password": pw, "display_name": "A"})
    assert r.status_code == 201, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}, r.json()


BODY = {"topic": "Uzayın derinlikleri hakkında 5 gerçek", "category": "Bilim", "duration": 20, "quality_tier": "draft", "media_mode": "slideshow",
        "platforms": ["youtube"], "publish_mode": "auto"}


def test_unauthenticated_requests_rejected(client):
    for path in ["/api/v1/projects", "/api/v1/dashboard", "/api/v1/costs/summary", "/api/v1/providers", "/api/jobs"]:
        r = client.get(path)
        assert r.status_code == 401, path
        assert r.json()["error"]["code"] == "auth_required"
    assert client.get("/api/v1/health").status_code == 200  # yalnızca sağlık herkese açık


def test_auth_flow_refresh_rotation_and_reuse_detection(client):
    h, tokens = register(client)
    assert client.get("/api/v1/auth/me", headers=h).json()["role"] == "admin"  # ilk kullanıcı
    r1 = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r1.status_code == 200
    new = r1.json()
    # eski refresh token yeniden kullanılırsa tüm oturumlar kapanır (çalıntı token tespiti)
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + new["access_token"]}).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": new["refresh_token"]}).status_code == 401


def test_password_policy_and_login_errors(client):
    assert client.post("/api/v1/auth/register", json={"email": "x@example.com", "password": "short"}).status_code == 422
    assert client.post("/api/v1/auth/register", json={"email": "x@example.com", "password": "onlyletterspassword"}).status_code == 422
    register(client)
    assert client.post("/api/v1/auth/register", json={"email": "a@example.com", "password": "Passw0rd!xyz"}).status_code == 409
    r = client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "wrong-password1"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "bad_credentials"
    assert client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "Passw0rd!xyz"}).status_code == 200


def test_login_rate_limit(client):
    for _ in range(10):
        client.post("/api/v1/auth/login", json={"email": "z@example.com", "password": "nope-nope-1"})
    r = client.post("/api/v1/auth/login", json={"email": "z@example.com", "password": "nope-nope-1"})
    assert r.status_code == 429


def test_security_headers_and_error_shape(client):
    r = client.get("/api/v1/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY" and "x-request-id" in r.headers
    h, _ = register(client)
    bad = client.post("/api/v1/projects", headers=h, json={"topic": "x"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation_error"
    bad2 = client.post("/api/v1/projects", headers=h, json={**BODY, "duration": 9999})
    assert bad2.status_code == 422


def test_user_isolation(client, no_dispatch):
    ha, _ = register(client, "a@example.com")
    hb, _ = register(client, "b@example.com")
    pid = client.post("/api/v1/projects", headers=ha, json=BODY).json()["project"]["id"]
    assert client.get(f"/api/v1/projects/{pid}", headers=ha).status_code == 200
    for method, path in [("get", f"/api/v1/projects/{pid}"), ("post", f"/api/v1/projects/{pid}/cancel"), ("delete", f"/api/v1/projects/{pid}"),
                         ("get", f"/api/v1/projects/{pid}/events"), ("get", f"/api/v1/projects/{pid}/media")]:
        assert getattr(client, method)(path, headers=hb).status_code == 404, path
    assert client.get("/api/v1/projects", headers=hb).json()["total"] == 0
    assert client.get("/api/jobs", headers=hb).json() == []


def test_create_idempotency_and_estimate(client, no_dispatch):
    h, _ = register(client)
    est = client.post("/api/v1/projects/estimate", headers=h, json=BODY).json()
    assert est["items"] and est["total_usd"] >= 0 and any(w for w in est["warnings"])  # AI anahtarı yok → uyarı
    r1 = client.post("/api/v1/projects", headers={**h, "Idempotency-Key": "k-1"}, json=BODY).json()
    r2 = client.post("/api/v1/projects", headers={**h, "Idempotency-Key": "k-1"}, json=BODY).json()
    assert r1["project"]["id"] == r2["project"]["id"] and r2["replayed"] is True
    assert len(no_dispatch) == 1  # yalnızca bir kez kuyruğa alındı
    r3 = client.post("/api/v1/projects", headers={**h, "Idempotency-Key": "k-1"}, json={**BODY, "topic": "Başka konu burada"})
    assert r3.status_code == 409


def test_cancel_queued_and_retry_rules(client, no_dispatch):
    h, _ = register(client)
    pid = client.post("/api/v1/projects", headers=h, json=BODY).json()["project"]["id"]
    assert client.post(f"/api/v1/projects/{pid}/retry", headers=h).status_code == 409  # QUEUED yeniden denenemez
    c = client.post(f"/api/v1/projects/{pid}/cancel", headers=h)
    assert c.json()["status"] == "CANCELLED"
    assert client.post(f"/api/v1/projects/{pid}/cancel", headers=h).status_code == 409
    r = client.post(f"/api/v1/projects/{pid}/retry", headers=h)
    assert r.status_code == 202 and r.json()["status"] == "QUEUED"
    assert client.delete(f"/api/v1/projects/{pid}", headers=h).status_code == 200  # kuyruktaki iş silinebilir (çalışan/yayınlanan silinemez)
    assert client.get(f"/api/v1/projects/{pid}", headers=h).status_code == 404


def test_budget_blocks_creation_and_resume(client, no_dispatch):
    h, _ = register(client)
    r = client.put("/api/v1/costs/budget", headers=h, json={"per_video_usd": 0.001})
    assert r.status_code == 200
    blocked = client.post("/api/v1/projects", headers=h, json=BODY)  # sunucu+depolama tahmini bile $0.001'i aşar
    assert blocked.status_code == 402 and blocked.json()["error"]["code"] == "per_video_budget"
    assert client.put("/api/v1/costs/budget", headers=h, json={"per_video_usd": 1.0}).status_code == 200
    assert client.post("/api/v1/projects", headers=h, json=BODY).status_code == 202
    b = client.get("/api/v1/costs/budget", headers=h).json()
    assert b["per_video_usd"] == 1.0 and "spent_today_usd" in b
    assert client.put("/api/v1/costs/budget", headers=h, json={"daily_usd": -5}).status_code == 422


def test_providers_integrations_and_credentials(client):
    h, _ = register(client)
    p = client.get("/api/v1/providers", headers=h).json()
    names = {(x["kind"], x["name"]): x for x in p["providers"]}
    assert names[("llm", "openai")]["configured"] is False  # anahtar yok → çalışıyormuş gibi gösterilmez
    assert names[("tts", "espeak")]["configured"] is True and names[("tts", "espeak")]["is_ai"] is False
    r = client.put("/api/v1/providers/openai/credential", headers=h, json={"secret": "sk-test-supersecretvalue123"})
    assert r.status_code == 200 and "supersecret" not in r.text
    p2 = client.get("/api/v1/providers", headers=h).json()
    o = {(x["kind"], x["name"]): x for x in p2["providers"]}[("llm", "openai")]
    assert o["configured"] is True and o["key_source"] == "kullanıcı" and "supersecret" not in json.dumps(p2)
    from backend.database.session import session_scope
    from backend.models import ProviderCredential
    with session_scope() as db:
        assert "sk-test" not in db.query(ProviderCredential).one().encrypted_secret  # DB'de şifreli
    assert client.put("/api/v1/providers/preferences", headers=h, json={"llm": ["nope"]}).status_code == 422
    integ = client.get("/api/v1/integrations", headers=h).json()
    assert {x["platform"] for x in integ["platforms"]} == {"youtube", "tiktok", "instagram"} and not any(x["oauth_configured"] for x in integ["platforms"])
    a = client.post("/api/v1/integrations/youtube/authorize", headers=h)
    assert a.status_code == 422 and a.json()["error"]["code"] == "oauth_not_configured"


def test_oauth_authorize_state_and_callback_rejects_bad_state(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "gid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "gs")
    from backend.core import config
    config.reset_settings_cache()
    h, _ = register(client)
    a = client.post("/api/v1/integrations/youtube/authorize", headers=h).json()
    assert "accounts.google.com" in a["url"] and "code_challenge=" in a["url"] and "state=" in a["url"]
    bad = client.get("/api/v1/oauth/youtube/callback?code=abc&state=tampered.sig")
    assert bad.status_code == 400 and "Bağlanamadı" in bad.text


def test_music_upload_requires_license_and_valid_audio(client, tmp_path):
    h, _ = register(client)
    import subprocess
    wav = tmp_path / "m.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=d=12", str(wav)], check=True)
    data = {"title": "T", "mood": "calm", "license_type": "CC0", "license_source": "https://example.com/l"}
    r = client.post("/api/v1/music", headers=h, data={**data, "commercial_use": "false"}, files={"file": ("m.wav", wav.read_bytes())})
    assert r.status_code == 422
    r = client.post("/api/v1/music", headers=h, data={**data, "commercial_use": "true"}, files={"file": ("x.mp3", b"MZ-not-audio-at-all-padding")})
    assert r.status_code == 415
    r = client.post("/api/v1/music", headers=h, data={**data, "commercial_use": "true"}, files={"file": ("m.wav", wav.read_bytes())})
    assert r.status_code == 201, r.text
    assert len(client.get("/api/v1/music", headers=h).json()) == 1


def test_channel_crud_and_automation_tick(client, monkeypatch):
    h, _ = register(client)
    ch = client.post("/api/v1/channels", headers=h, json={"name": "Bilim TR", "category": "Bilim", "platforms": ["youtube"], "automation_enabled": True,
                                                            "videos_per_day": 2, "posting_hours": [9, 18], "media_mode": "slideshow", "quality_tier": "draft"})
    assert ch.status_code == 201
    cid = ch.json()["id"]
    assert client.post("/api/v1/channels", headers=h, json={"name": "x", "category": "y", "brand": {"evil": 1}}).status_code == 422
    sent = []
    monkeypatch.setattr("backend.services.projects.dispatch", lambda *a, **k: sent.append(a) or "t")
    monkeypatch.setattr("backend.workers.dispatch.dispatch", lambda *a, **k: sent.append(a) or "t")
    # fikir yok → ilk tick fikir üretimi başlatır, proje oluşturmaz
    from backend.automation.engine import tick
    r = tick()
    assert r["created"] == 0 and any("fikir" in s[1] for s in r["skipped"])
    # fikir ekle → proje oluşturulur; günlük sınır ve aktif iş sınırı uygulanır
    from backend.database.session import session_scope
    from backend.models import Idea
    with session_scope() as db:
        uid = db.query(Idea).count() or None
        from backend.models import User
        u = db.query(User).one().id
        for i in range(4):
            db.add(Idea(user_id=u, channel_id=cid, category="Bilim", title=f"Fikir numara {i} uzay", score=90 - i, fingerprint=f"fp{i}", status="new"))
    assert tick()["created"] == 1
    assert tick()["created"] == 1
    assert tick()["created"] == 0  # günlük hedef (2) doldu
    assert client.post("/api/v1/automation/pause", headers=h).json()["paused"] is True
    assert client.get("/api/v1/automation/status", headers=h).json()["paused"] is True
    assert client.delete(f"/api/v1/channels/{cid}", headers=h).status_code == 200


def test_v1_compat_endpoints(client, no_dispatch):
    h, _ = register(client)
    r = client.post("/api/jobs", headers=h, json={"topic": "GTA 6 hakkında 5 detay", "category": "Oyun", "style": "cinematic", "duration": 30, "platforms": ["youtube"]})
    assert r.status_code == 200 and r.json()["status"] == "queued"
    jid = r.json()["id"]
    j = client.get(f"/api/jobs/{jid}", headers=h).json()
    assert j["status"] == "queued" and j["topic"].startswith("GTA 6") and "v2" in j
    assert client.get("/api/health").json()["app"]


def test_compat_llm_credential_validation_ssrf_and_use(client):
    """Özel (OpenAI uyumlu) LLM: adres doğrulama (SSRF), şifreli saklama, ayarlanınca 'yapılandırıldı'."""
    h, _ = register(client)
    P = "/api/v1/providers/compat/credential"
    assert client.put(P, headers=h, json={"secret": "key-123456789"}).status_code == 422  # base_url/model zorunlu
    for bad in ["http://api.example.com/v1", "https://localhost/v1", "https://127.0.0.1/v1", "https://10.0.0.5/v1", "https://169.254.169.254/latest", "https://intranet/v1", "ftp://x.y/z"]:
        assert client.put(P, headers=h, json={"secret": "key-123456789", "base_url": bad, "model": "m"}).status_code == 422, bad
    r = client.put(P, headers=h, json={"secret": "key-123456789", "base_url": "https://api.groq.example.com/openai/v1/", "model": "llama-x"})
    assert r.status_code == 200
    prov = {(x["kind"], x["name"]): x for x in client.get("/api/v1/providers", headers=h).json()["providers"]}
    assert prov[("llm", "compat")]["configured"] is True and prov[("llm", "compat")]["is_ai"] is True
    from backend.database.session import session_scope
    from backend.models import ProviderCredential
    with session_scope() as db:
        row = db.query(ProviderCredential).filter_by(provider="compat").one()
        assert "key-1234" not in row.encrypted_secret and row.extra["base_url"] == "https://api.groq.example.com/openai/v1"
