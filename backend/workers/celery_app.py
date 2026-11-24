from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from ..core.config import get_settings
from ..core.logging import setup_logging

s = get_settings()
setup_logging()
celery = Celery("aivf", broker=s.redis_url, backend=s.redis_url, include=["backend.workers.tasks"])
celery.conf.update(
    task_serializer="json", accept_content=["json"], result_serializer="json", timezone="UTC", enable_utc=True,
    task_acks_late=True, task_reject_on_worker_lost=True, worker_prefetch_multiplier=1,
    task_default_queue="default",
    task_routes={"backend.workers.tasks.run_project_task": {"queue": "render"}},
    task_time_limit=s.project_deadline_minutes * 60 + 120, task_soft_time_limit=s.project_deadline_minutes * 60,
    broker_connection_retry_on_startup=True, result_expires=3600,
    beat_schedule={
        "reap-stuck": {"task": "backend.workers.tasks.reap_stuck_task", "schedule": 120.0},
        "scheduler-tick": {"task": "backend.workers.tasks.scheduler_tick_task", "schedule": 60.0},
        "publish-due": {"task": "backend.workers.tasks.publish_due_task", "schedule": 60.0},
        "collect-metrics": {"task": "backend.workers.tasks.collect_metrics_task", "schedule": crontab(minute="*/30")},
        "refresh-trends": {"task": "backend.workers.tasks.refresh_trends_task", "schedule": crontab(minute=5, hour="*/6")},
    },
)
