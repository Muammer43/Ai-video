#!/usr/bin/env bash
# Tüm test paketi (SQLite). PostgreSQL ile: TEST_DATABASE_URL=postgresql://... scripts/run_tests.sh
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements-dev.txt
.venv/bin/python -m pytest -q --timeout 600 "$@"
