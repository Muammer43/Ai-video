#!/usr/bin/env bash
# TEMİZ ORTAM KURULUM TESTİ (Docker'sız): sıfır venv + yalnızca requirements.txt + PostgreSQL + Redis + API + worker + beat.
# Önkoşul: çalışan PostgreSQL (CLEAN_PG_URL), redis-server, ffmpeg, espeak-ng.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"; T="$(mktemp -d /tmp/aivf_clean_XXXX)"; PG="${CLEAN_PG_URL:?CLEAN_PG_URL gerekli, örn. postgresql://aivf:pw@127.0.0.1:5432/aivf_clean}"
PIDS=()
cleanup(){ for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done; rm -rf "$T"; }
trap cleanup EXIT
python3 -m venv "$T/venv" && "$T/venv/bin/pip" install -q -r requirements.txt   # yalnızca çalışma zamanı bağımlılıkları
export ENV=prod SECRET_KEY="$("$T/venv/bin/python" -c 'import secrets;print(secrets.token_urlsafe(48))')" ENCRYPTION_KEY="$("$T/venv/bin/python" -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"
export DATABASE_URL="$PG" REDIS_URL=redis://127.0.0.1:6392/0 STORAGE_BACKEND=local LOCAL_STORAGE_DIR="$T/storage" WORK_DIR="$T/work" PUBLIC_BASE_URL=https://clean.example.test ALLOW_REGISTRATION=true
redis-server --port 6392 --save "" --appendonly no >/dev/null & PIDS+=($!)
"$T/venv/bin/alembic" upgrade head
"$T/venv/bin/uvicorn" backend.main:app --port 8078 >"$T/api.log" 2>&1 & PIDS+=($!)
"$T/venv/bin/celery" -A backend.workers.celery_app worker -Q default,render -c 2 >"$T/worker.log" 2>&1 & PIDS+=($!)
"$T/venv/bin/celery" -A backend.workers.celery_app beat -s "$T/beat" >"$T/beat.log" 2>&1 & PIDS+=($!)
for i in $(seq 1 40); do curl -fsS localhost:8078/api/v1/health >/dev/null 2>&1 && break; sleep 1; done
"$T/venv/bin/python" scripts/smoke_test.py http://127.0.0.1:8078
echo "TEMİZ KURULUM TESTİ GEÇTİ"
