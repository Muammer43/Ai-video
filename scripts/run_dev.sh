#!/usr/bin/env bash
# Geliştirme: tek süreç (SQLite + yerel depolama + eager kuyruk). Redis/PostgreSQL gerekmez.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
export ENV=dev CELERY_EAGER=true DATABASE_URL="${DATABASE_URL:-sqlite:///./data/dev.db}" SECRET_KEY="${SECRET_KEY:-dev-only-$(python3 -c 'import secrets;print(secrets.token_hex(16))')}"
exec .venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8000}" --reload
