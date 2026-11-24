"""Gerçek Redis + Celery worker entegrasyonu (ayrı süreçte çalışır)."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("redis-server") is None, reason="redis-server kurulu değil")
def test_real_celery_redis_flow():
    p = subprocess.run([sys.executable, "-m", "tests.integration.celery_e2e"], cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert p.returncode == 0, p.stdout[-3000:] + p.stderr[-1500:]
    assert '"ok": true' in p.stdout
