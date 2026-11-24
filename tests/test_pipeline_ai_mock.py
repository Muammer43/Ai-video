"""AI sağlayıcı yolunun MOCK HTTP ile entegrasyon testi (canlı API doğrulaması DEĞİLDİR)."""
import time

import pytest
from sqlalchemy import select

from backend.database.session import session_scope
from backend.models import CostEntry, Project, ProviderStat, Scene
from backend.providers import http as H
from backend.workers.pipeline import run_project

from .conftest import make_project
from .mocks import FakeAPI


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)


def _keys(monkeypatch, **extra):
    for k, v in {"OPENAI_API_KEY": "sk-test-abcdefghijklmnop", "FAL_KEY": "fal-test-key-000000000000", **extra}.items():
        monkeypatch.setenv(k, v)
    from backend.core import config
    config.reset_settings_cache()


def test_hybrid_ai_pipeline_auto_approves(user, env, monkeypatch):
    _keys(monkeypatch, PEXELS_API_KEY="pexels-test-key")
    api = FakeAPI()
    H.set_transport_factory(api.transport)
    pid = make_project(user, media_mode="hybrid", quality_tier="standard", duration_target=22)
    run_project(pid)
    with session_scope() as db:
        p = db.get(Project, pid)
        assert p.status == "APPROVED", (p.status, p.error, p.quality_report.get("reasons"), p.quality_report.get("risk_flags"))
        assert p.qc_decision == "auto_publish" and p.quality_score >= 80
        origins = [s.origin for s in db.execute(select(Scene).where(Scene.project_id == pid).order_by(Scene.idx)).scalars()]
        assert origins[0] == "ai_video" and "stock" in origins  # hook sahnesi AI video, diğerleri stok
        assert p.media_report["ai_video_ratio"] > 0
        assert p.script["_meta"]["is_ai"] is True
        ledger = db.execute(select(CostEntry).where(CostEntry.project_id == pid)).scalars().all()
        kinds = {c.kind for c in ledger}
        assert {"llm", "image", "video", "tts", "stt", "server", "storage"} <= kinds
        assert p.cost_actual > 0 and abs(p.cost_actual - sum(c.cost_usd for c in ledger)) < 1e-6
        stats = {(s.provider, s.kind): s for s in db.execute(select(ProviderStat)).scalars()}
        assert stats[("fal", "video")].successes >= 1 and stats[("openai", "llm")].successes >= 2  # senaryo + güvenlik incelemesi
    # Anthropic'e temperature gönderilmediği ve OpenAI chat isteğinin biçimi
    chat = [b for b in api.bodies if b["url"].endswith("/v1/chat/completions")][0]
    assert chat["response_format"] == {"type": "json_object"} and "max_completion_tokens" in chat


def test_video_provider_failure_falls_back_to_motion(user, env, monkeypatch):
    _keys(monkeypatch)
    api = FakeAPI(fail_hosts={"queue.fal.run"})
    H.set_transport_factory(api.transport)
    pid = make_project(user, media_mode="ai_video", quality_tier="standard", duration_target=15)
    run_project(pid)
    with session_scope() as db:
        p = db.get(Project, pid)
        origins = {s.origin for s in db.execute(select(Scene).where(Scene.project_id == pid)).scalars()}
        assert origins == {"ai_image_motion"}  # AI video alınamadı → dürüstçe 'görsel+hareket'
        assert p.media_report["ai_video_ratio"] == 0
        assert p.status == "NEEDS_REVIEW"  # ai_video modu karşılanmadı → otomatik yayın yok
        assert "ai_video_shortfall" in {f["id"] for f in p.quality_report["risk_flags"]}
        assert p.media_report["fallbacks"]
        st = db.execute(select(ProviderStat).where(ProviderStat.provider == "fal", ProviderStat.kind == "video")).scalar_one()
        assert st.failures >= 1 and st.successes == 0 and st.last_error


def test_budget_blocks_expensive_calls(user, env, monkeypatch):
    _keys(monkeypatch)
    from backend.services.usersettings import update_user_settings
    with session_scope() as db:
        update_user_settings(db, user, {"budget": {"daily_usd": 0.0001}})
    H.set_transport_factory(FakeAPI().transport)
    pid = make_project(user, media_mode="ai_video")
    out = run_project(pid)
    with session_scope() as db:
        p = db.get(Project, pid)
        assert p.status == "FAILED" and p.error_code == "BUDGET_EXCEEDED", (p.status, p.error)
        from backend.models import Notification
        assert db.execute(select(Notification).where(Notification.user_id == user, Notification.kind.in_(["budget", "job_failed"]))).first()
