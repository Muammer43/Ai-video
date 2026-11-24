"""Güvenlik testleri: enjeksiyon, yol geçişi, token kurcalama, yetki/izolasyon, gizli bilgi sızıntısı, yükleme güvenliği."""
import base64
import json
import logging

import pytest
from fastapi.testclient import TestClient

from backend.core import security
from backend.core.errors import Unauthorized
from backend.main import app


@pytest.fixture()
def client(env):
    with TestClient(app) as c:
        yield c


def reg(client, email="s@example.com"):
    r = client.post("/api/v1/auth/register", json={"email": email, "password": "Passw0rd!xyz"}).json()
    return {"Authorization": "Bearer " + r["access_token"]}, r


def test_jwt_tampering_alg_none_and_wrong_type(client):
    h, r = reg(client)
    tok = r["access_token"]
    head, payload, sig = tok.split(".")
    # imza kırpılmış / değiştirilmiş
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {head}.{payload}.{sig[:-2]}xx"}).status_code == 401
    # alg=none saldırısı
    none_head = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).decode().rstrip("=")
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {none_head}.{payload}."}).status_code == 401
    # başka kullanıcı kimliği ile imzasız payload
    p = json.loads(base64.urlsafe_b64decode(payload + "=="))
    p["sub"] = "0" * 32
    forged = base64.urlsafe_b64encode(json.dumps(p).encode()).decode().rstrip("=")
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {head}.{forged}.{sig}"}).status_code == 401
    # medya token'ı erişim token'ı olarak kullanılamaz
    mt = security.create_media_token("u", "k")
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {mt}"}).status_code == 401
    with pytest.raises(Unauthorized):
        security.decode_media_token(tok)  # erişim token'ı medya token'ı olarak kullanılamaz


def test_sql_injection_in_filters_is_inert(client):
    h, _ = reg(client)
    for q in ["' OR 1=1 --", "'; DROP TABLE projects; --", "%' UNION SELECT * FROM users --"]:
        r = client.get("/api/v1/projects", headers=h, params={"q": q, "status": q})
        assert r.status_code == 200 and r.json()["total"] == 0
    assert client.get("/api/v1/projects", headers=h).status_code == 200  # tablo hâlâ var


def test_path_traversal_in_storage(env):
    from backend.storage.base import LocalStorage
    st = LocalStorage(env / "s")
    for bad in ["../x", "/etc/passwd", "a/../../b", "a\\b", "a\x00b"]:
        with pytest.raises(ValueError):
            st.put_bytes(bad, b"x")
    st.put_bytes("u1/p1/final/a.mp4", b"ok")
    assert st.exists("u1/p1/final/a.mp4")


def test_media_token_scoped_to_owner_and_key(client, tmp_path):
    from backend.database.session import session_scope
    from backend.models import Asset, User
    from backend.services.assets import store_asset
    ha, ra = reg(client, "a@example.com")
    hb, rb = reg(client, "b@example.com")
    f = tmp_path / "x.mp4"
    f.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 100)
    with session_scope() as db:
        uid_a = db.query(User).filter(User.email == "a@example.com").one().id
        uid_b = db.query(User).filter(User.email == "b@example.com").one().id
        a = store_asset(db, uid_a, None, "final", f)
        key = a.storage_key
    ok = client.get(f"/api/v1/media/{security.create_media_token(uid_a, key)}")
    assert ok.status_code == 200
    # B kullanıcısı adına imzalı token, A'nın dosyasını açamaz
    assert client.get(f"/api/v1/media/{security.create_media_token(uid_b, key)}").status_code == 404
    # süresi dolmuş token
    assert client.get(f"/api/v1/media/{security.create_media_token(uid_a, key, ttl=-5)}").status_code == 401
    # yetkili indirme uç noktası başka kullanıcıya kapalı
    assert client.get(f"/api/v1/assets/{a.id}/download", headers=hb).status_code == 404
    assert client.get(f"/api/v1/assets/{a.id}/download", headers=ha).status_code == 200


def test_ffmpeg_filter_injection_payloads_do_not_break_or_execute(user, env):
    """V1'deki drawtext enjeksiyon sınıfı: ASS/dosya tabanlı metin hattında kötü niyetli anlatım render'ı bozmaz ve komut çalıştırmaz."""
    import subprocess
    from pathlib import Path
    from backend.editor import ffmpeg as ff, subtitles as sub
    evil = "%{pict_type}\\,drawtext=text=x:fontfile=/etc/passwd,movie='/etc/passwd'[x];{\\an8\\fs200}[0:v]; $(touch /tmp/pwned_aivf) `id` ; ' \" , :"
    words = [{"word": w, "start": i * 0.3, "end": i * 0.3 + 0.25} for i, w in enumerate(evil.split())]
    cues = sub.group_cues(words)
    ass = sub.build_ass(cues, 720, 1280)
    assert "{\\an8" not in ass and "\\fs200" not in ass  # ASS override enjeksiyonu etkisiz
    work = Path(env) / "inj"
    work.mkdir()
    (work / "s.ass").write_text(ass, encoding="utf-8")
    ff.run(["-f", "lavfi", "-i", "color=c=black:s=720x1280:d=3", "-vf", "ass=s.ass", "-frames:v", "5", "out.mp4"], cwd=work, timeout=60)
    assert (work / "out.mp4").exists()
    assert not Path("/tmp/pwned_aivf").exists()
    assert ff.ass_escape("a{\\b1}b\nc") == "a(＼b1)b c"


def test_secrets_never_logged_or_returned(client, caplog):
    from backend.core.logging import RedactFilter, redact
    assert "sk-abcdefghijklmnop12345" not in redact("key=sk-abcdefghijklmnop12345")
    assert "supersecretvalue" not in redact("Authorization: Bearer supersecretvalue")
    assert "hunter2pass" not in redact('{"password": "hunter2pass"}')
    h, _ = reg(client)
    with caplog.at_level(logging.INFO):
        client.put("/api/v1/providers/openai/credential", headers=h, json={"secret": "sk-live-VERYSECRETKEY123456"})
        r = client.get("/api/v1/providers", headers=h)
        client.post("/api/v1/auth/login", json={"email": "s@example.com", "password": "Passw0rd!xyz"})
    assert "VERYSECRETKEY" not in caplog.text and "VERYSECRETKEY" not in r.text
    from backend.database.session import session_scope
    from backend.models import AuditLog
    with session_scope() as db:
        assert "VERYSECRETKEY" not in json.dumps([a.meta for a in db.query(AuditLog)])  # audit log'da değer yok
        assert db.query(AuditLog).filter(AuditLog.action == "provider.credential_set").count() == 1


def test_provider_errors_are_redacted():
    from backend.providers import http as H
    import httpx
    r = httpx.Response(400, text='{"error":"bad key sk-leakedleakedleaked123 Authorization: Bearer abc123def456"}')
    from backend.providers.base import ProviderError
    with pytest.raises(ProviderError) as e:
        H.raise_for_provider(r, "x")
    assert "leakedleaked" not in str(e.value) and "abc123def456" not in str(e.value)


def test_logo_upload_validates_magic_bytes_and_size(client):
    h, _ = reg(client)
    ch = client.post("/api/v1/channels", headers=h, json={"name": "Kanal", "category": "Bilim"}).json()
    evil = client.post(f"/api/v1/channels/{ch['id']}/logo", headers=h, files={"file": ("logo.png", b"<?php system($_GET['x']); ?>")})
    assert evil.status_code == 415
    big = client.post(f"/api/v1/channels/{ch['id']}/logo", headers=h, files={"file": ("l.png", b"\x89PNG\r\n\x1a\n" + b"0" * (2 * 1024 * 1024 + 10))})
    assert big.status_code == 413


def test_cors_closed_by_default_and_headers(client):
    r = client.options("/api/v1/projects", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers  # V1'deki '*' açığı kapalı
    h = client.get("/api/v1/health").headers
    assert "default-src 'self'" in h["content-security-policy"] and "frame-ancestors 'none'" in h["content-security-policy"]


def test_production_refuses_insecure_defaults(monkeypatch, env):
    from backend.core import config
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("SECRET_KEY", config.INSECURE_DEFAULT_SECRET)
    config.reset_settings_cache()
    with pytest.raises(RuntimeError):
        config.get_settings().validate_for_runtime()
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    config.reset_settings_cache()
    with pytest.raises(RuntimeError, match="ENCRYPTION_KEY"):
        config.get_settings().validate_for_runtime()


def test_encryption_roundtrip_and_wrong_key(monkeypatch, env):
    from cryptography.fernet import Fernet
    from backend.core import config
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    config.reset_settings_cache()
    enc = security.encrypt_secret("tiktok-refresh-token")
    assert "tiktok" not in enc and security.decrypt_secret(enc) == "tiktok-refresh-token"
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    config.reset_settings_cache()
    with pytest.raises(ValueError):
        security.decrypt_secret(enc)


def test_oauth_state_tamper_and_expiry():
    s = security.sign_state({"u": "1", "p": "youtube", "v": "x"})
    assert security.verify_state(s)["u"] == "1"
    with pytest.raises(Unauthorized):
        security.verify_state(s[:-3] + "abc")
    with pytest.raises(Unauthorized):
        security.verify_state(security.sign_state({"u": "1"}, ttl=-1))


def test_password_change_revokes_sessions(client):
    h, r = reg(client)
    assert client.post("/api/v1/auth/change-password", headers=h, json={"old_password": "Passw0rd!xyz", "new_password": "N3wPassword!!"}).status_code == 200
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": r["refresh_token"]}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "s@example.com", "password": "N3wPassword!!"}).status_code == 200
