"""Gerçek FFmpeg + espeak-ng ile uçtan uca üretim (AI anahtarı YOK → çevrimdışı/etiketli sağlayıcılar).
Bu test AI entegrasyonunu doğrulamaz; hattın, render'ın ve QC'nin gerçek çalıştığını doğrular."""
from pathlib import Path

from sqlalchemy import select

from backend.database.session import session_scope
from backend.editor import ffmpeg as ff
from backend.models import Asset, JobEvent, Project, Scene
from backend.storage import get_storage
from backend.workers.pipeline import run_project

from .conftest import make_project


def test_offline_pipeline_produces_real_mp4(user, env):
    pid = make_project(user)
    out = run_project(pid)
    with session_scope() as db:
        p = db.get(Project, pid)
        assert p.status == "NEEDS_REVIEW", (p.status, p.error)  # şablon+robotik ses+yer tutucu → otomatik yayın YOK
        assert p.qc_decision == "review"
        flags = {f["id"] for f in p.quality_report["risk_flags"]}
        assert {"template_script", "offline_voice", "placeholder_visuals"} <= flags
        assert p.quality_score is not None and 0 <= p.quality_score <= 100
        assert len(p.quality_report["checks"]) >= 14
        final = db.get(Asset, p.final_asset_id)
        path = get_storage().local_path(final.storage_key)
        info = ff.probe(path)
        assert info.has_video and info.has_audio and (info.width, info.height) == (720, 1280)
        assert info.vcodec == "h264" and info.acodec == "aac" and info.duration > 8
        scenes = db.execute(select(Scene).where(Scene.project_id == pid)).scalars().all()
        assert scenes and all(s.origin == "procedural" for s in scenes)
        assert all(s.meta["stt_estimated"] for s in scenes)  # tahmini hizalama etiketli
        kinds = {a.kind for a in db.execute(select(Asset).where(Asset.project_id == pid)).scalars()}
        assert {"audio", "video", "image", "final", "thumbnail", "subtitle"} <= kinds
        assert db.execute(select(JobEvent).where(JobEvent.project_id == pid)).scalars().all()
    assert not (Path(env) / "work" / pid).exists()  # geçici dosyalar temizlendi


def test_claim_prevents_double_run(user, env):
    from backend.workers.pipeline import claim
    pid = make_project(user)
    assert claim(pid) is True
    assert claim(pid) is False  # ikinci işçi aynı işi alamaz
    assert run_project(pid)["status"] == "skipped"


def test_trend_filters_skip_main_page():
    """Wikimedia yanıtı (MOCK) — ana sayfa ve özel sayfalar trend sayılmaz."""
    import httpx
    from backend.providers import http as H
    from backend.services import trends
    arts = [{"article": a, "views": 100 - i, "rank": i + 1} for i, a in enumerate(["Anasayfa", "Özel:Ara", "Büyük_Patlama", "Vikipedi:Hakkında", "Mars"])]
    H.set_transport_factory(lambda: httpx.MockTransport(lambda r: httpx.Response(200, json={"items": [{"articles": arts}]})))
    try:
        out = trends.fetch_wikipedia("tr", limit=10)
    finally:
        H.set_transport_factory(None)
    assert [t["title"] for t in out] == ["Büyük Patlama", "Mars"]
