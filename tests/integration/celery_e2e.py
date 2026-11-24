"""Gerçek Redis + gerçek Celery worker ile entegrasyon senaryosu (mock YOK; sağlayıcılar çevrimdışı/etiketli yerel olanlardır).
Çalıştırma: python -m tests.integration.celery_e2e   (çıktı: JSON rapor; hata → çıkış kodu 1)"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PORT = 6391


def sh(cmd, **kw):
    return subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **kw)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="celery_e2e_"))
    env = dict(os.environ, ENV="test", SECRET_KEY="e2e-secret-" + "x" * 32, DATABASE_URL=f"sqlite:///{tmp}/t.db", REDIS_URL=f"redis://127.0.0.1:{PORT}/0",
               LOCAL_STORAGE_DIR=str(tmp / "st"), WORK_DIR=str(tmp / "work"), CELERY_EAGER="false", PUBLIC_BASE_URL="http://testserver",
               STUCK_JOB_MINUTES="20")
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "FAL_KEY", "PEXELS_API_KEY"):
        env.pop(k, None)
    os.environ.update(env)
    report: dict = {}
    redis = sh(["redis-server", "--port", str(PORT), "--save", "", "--appendonly", "no", "--dir", str(tmp)])
    workers: list[subprocess.Popen] = []

    def start_worker(name: str):
        w = subprocess.Popen([sys.executable, "-m", "celery", "-A", "backend.workers.celery_app", "worker", "-Q", "default,render", "-c", "2",
                              "-n", f"{name}@%h", "--loglevel=INFO"], cwd=ROOT, env=env, stdout=open(tmp / f"{name}.log", "w"), stderr=subprocess.STDOUT)
        workers.append(w)
        return w

    try:
        time.sleep(1)
        w1 = start_worker("w1")
        from fastapi.testclient import TestClient
        from backend.core import config
        config.reset_settings_cache()
        from backend.main import app
        from backend.database.session import session_scope
        from backend.models import JobEvent, Project
        from backend.workers.celery_app import celery
        from backend.workers.tasks import reap_stuck_task

        t0 = time.time()
        while time.time() - t0 < 40:
            try:
                if celery.control.inspect(timeout=1).ping():
                    break
            except Exception:  # noqa: BLE001
                pass
        else:
            raise RuntimeError("worker başlamadı")
        with TestClient(app) as c:
            r = c.post("/api/v1/auth/register", json={"email": "c@example.com", "password": "Passw0rd!xyz"})
            h = {"Authorization": "Bearer " + r.json()["access_token"]}
            st = c.get("/api/v1/system/status", headers=h).json()
            report["system_status"] = {"redis": st["redis"], "workers": st["workers"], "queue_mode": st["queue_mode"]}
            assert st["redis"]["ok"] and st["workers"]["ok"], st
            body = {"topic": "Celery entegrasyon testi konusu", "category": "Bilim", "duration": 15, "quality_tier": "draft", "media_mode": "slideshow", "platforms": []}

            def wait(pid, want, timeout=240):
                t = time.time()
                while time.time() - t < timeout:
                    p = c.get(f"/api/v1/projects/{pid}", headers=h).json()
                    if p["status"] in want:
                        return p
                    time.sleep(0.5)
                raise RuntimeError(f"zaman aşımı {p['status']} {p['stage_message']}")

            # 1) normal akış + çift gönderim engeli
            pid = c.post("/api/v1/projects", headers=h, json=body).json()["project"]["id"]
            celery.send_task("backend.workers.tasks.run_project_task", args=[pid], queue="render")  # aynı iş ikinci kez gönderildi
            p = wait(pid, {"NEEDS_REVIEW", "FAILED", "APPROVED"})
            with session_scope() as db:
                starts = db.query(JobEvent).filter(JobEvent.project_id == pid, JobEvent.message.like("Üretim başladı%")).count()
                attempts = db.get(Project, pid).attempts
            report["normal_flow"] = {"status": p["status"], "score": p["quality_score"], "start_events": starts, "attempts": attempts}
            assert p["status"] == "NEEDS_REVIEW" and starts == 1 and attempts == 1, report

            # 2) çalışan işçi öldürülür → reaper → yeni işçi tamamlar
            pid2 = c.post("/api/v1/projects", headers=h, json={**body, "topic": "Çökme kurtarma testi konusu"}).json()["project"]["id"]
            t = time.time()
            while time.time() - t < 60 and c.get(f"/api/v1/projects/{pid2}", headers=h).json()["status"] == "QUEUED":
                time.sleep(0.2)
            time.sleep(2)
            w1.send_signal(signal.SIGKILL)
            subprocess.run(["pkill", "-9", "-f", "celery -A backend.workers.celery_app worker -Q default,render -c 2 -n w1"], check=False)
            time.sleep(1)
            mid = c.get(f"/api/v1/projects/{pid2}", headers=h).json()["status"]
            from datetime import timedelta
            from backend.models import utcnow
            with session_scope() as db:
                db.get(Project, pid2).heartbeat_at = utcnow() - timedelta(minutes=45)  # işçi kayboldu: heartbeat eski
            w2 = start_worker("w2")
            reaped = reap_stuck_task.run()
            report["crash_recovery"] = {"status_after_kill": mid, "reaper": reaped}
            p2 = wait(pid2, {"NEEDS_REVIEW", "FAILED"})
            with session_scope() as db:
                attempts2 = db.get(Project, pid2).attempts
            report["crash_recovery"].update(final=p2["status"], attempts=attempts2)
            assert p2["status"] == "NEEDS_REVIEW" and reaped["requeued"] >= 1, report
        report["ok"] = True
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0
    except Exception as e:  # noqa: BLE001
        report["ok"] = False
        report["error"] = f"{type(e).__name__}: {e}"
        for i, w in enumerate(workers):
            lf = tmp / f"w{i + 1}.log"
            report[f"worker{i + 1}_log_tail"] = lf.read_text()[-1500:] if lf.exists() else ""
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 1
    finally:
        for w in workers:
            if w.poll() is None:
                w.terminate()
                try:
                    w.wait(10)
                except subprocess.TimeoutExpired:
                    w.kill()
        redis.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
