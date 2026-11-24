import os
import shutil
import tempfile
from pathlib import Path

import pytest

PROVIDER_ENV = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "FAL_KEY", "RUNWAY_API_KEY", "REPLICATE_API_TOKEN", "ELEVENLABS_API_KEY",
                "PEXELS_API_KEY", "PIXABAY_API_KEY"]


@pytest.fixture()
def env(monkeypatch):
    """Her test için izole DB + yerel depolama + eager kuyruk. Sağlayıcı anahtarları temizlenir."""
    tmp = Path(tempfile.mkdtemp(prefix="aivf_test_"))
    for k in PROVIDER_ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-" + "x" * 32)
    monkeypatch.setenv("DATABASE_URL", os.environ.get("TEST_DATABASE_URL", f"sqlite:///{tmp}/t.db"))
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp / "storage"))
    monkeypatch.setenv("WORK_DIR", str(tmp / "work"))
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("CELERY_EAGER", "true")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://testserver")
    from backend.core import config, ratelimit
    from backend.database import session
    from backend.providers import http as H
    from backend.storage import reset_storage
    config.reset_settings_cache()
    session.reset_engine()
    reset_storage()
    ratelimit.reset()
    H.set_transport_factory(None)
    from backend.models import Base
    eng = session.get_engine()
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield tmp
    session.reset_engine()
    H.set_transport_factory(None)
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture()
def user(env):
    from backend.core.security import hash_password
    from backend.database.session import session_scope
    from backend.models import User
    with session_scope() as db:
        u = User(email="t@example.com", password_hash=hash_password("Passw0rd!x"), display_name="Test")
        db.add(u)
        db.flush()
        return u.id


def make_project(user_id, **kw):
    from backend.database.session import session_scope
    from backend.models import Project
    base = dict(user_id=user_id, topic="Güneş sistemindeki gezegenler", category="Bilim", language="tr", style="cinematic",
                aspect_ratio="9:16", resolution="720p", duration_target=18, quality_tier="draft", media_mode="slideshow",
                voice={"gender": "female"}, options={}, platforms=["youtube"], publish_mode="auto", status="QUEUED")
    base.update(kw)
    with session_scope() as db:
        p = Project(**base)
        db.add(p)
        db.flush()
        return p.id
