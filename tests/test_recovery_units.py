"""Hata kurtarma: takılı iş toparlama, iptal, zaman aşımı, yeniden deneme sınırı."""
from datetime import timedelta

from backend.database.session import session_scope
from backend.models import Project, Publication, utcnow
from backend.workers import pipeline as pl
from backend.workers.tasks import reap_stuck_task

from .conftest import make_project


def test_reaper_requeues_then_fails_after_max_attempts(user, env, monkeypatch):
    sent = []
    monkeypatch.setattr("backend.workers.tasks.dispatch", lambda *a, **k: sent.append(a) or "x")
    a = make_project(user, status="RENDERING", attempts=1)
    b = make_project(user, status="PROCESSING", attempts=3)  # max_attempts=3 doldu
    with session_scope() as db:
        for pid in (a, b):
            db.get(Project, pid).heartbeat_at = utcnow() - timedelta(minutes=60)
    r = reap_stuck_task.run()
    assert r["requeued"] == 1 and r["failed"] == 1
    with session_scope() as db:
        assert db.get(Project, a).status == "QUEUED"
        pb = db.get(Project, b)
        assert pb.status == "FAILED" and pb.error_code == "STUCK"
    assert [x for x in sent if x[0] == "run_project_task" and x[1] == [a]]  # kurtarılan iş yeniden kuyruğa gönderildi


def test_reaper_ignores_fresh_jobs(user, env, monkeypatch):
    monkeypatch.setattr("backend.workers.tasks.dispatch", lambda *a, **k: "x")
    a = make_project(user, status="RENDERING")
    with session_scope() as db:
        db.get(Project, a).heartbeat_at = utcnow()
    assert reap_stuck_task.run()["requeued"] == 0


def test_retryable_error_requeues_then_fails_at_limit(user, env):
    pid = make_project(user, attempts=1, status="PROCESSING")
    r = pl._fail_or_retry(pid, user, "geçici", "PROVIDER_EXHAUSTED", True)
    assert r["status"] == "retry"
    with session_scope() as db:
        assert db.get(Project, pid).status == "QUEUED"
        db.get(Project, pid).attempts = 3
    r = pl._fail_or_retry(pid, user, "geçici", "PROVIDER_EXHAUSTED", True)
    assert r["status"] == "FAILED"
    r2 = pl._fail_or_retry(make_project(user, attempts=1), user, "kalıcı", "X", False)
    assert r2["status"] == "FAILED"


def test_deadline_exceeded_is_detected(user, env):
    from backend.core.errors import DeadlineExceeded
    from backend.services.runtime import cancel_checker
    pid = make_project(user, status="PROCESSING")
    with session_scope() as db:
        db.get(Project, pid).started_at = utcnow() - timedelta(hours=5)
    import pytest
    with pytest.raises(DeadlineExceeded):
        cancel_checker(pid)()
