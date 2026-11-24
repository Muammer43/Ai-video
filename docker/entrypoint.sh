#!/bin/sh
set -e
case "$1" in
  api)
    alembic upgrade head
    exec uvicorn backend.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' --workers "${API_WORKERS:-2}" ;;
  worker)
    exec celery -A backend.workers.celery_app worker -Q default,render -c "${WORKER_CONCURRENCY:-2}" --loglevel=INFO ;;
  beat)
    exec celery -A backend.workers.celery_app beat -s /tmp/celerybeat-schedule --loglevel=INFO ;;
  *) exec "$@" ;;
esac
