"""Görev gönderme soyutlaması. Üretimde Celery (Redis); CELERY_EAGER=true ise süreç içi iş parçacığı (yalnızca dev/test)."""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from ..core.config import get_settings

log = logging.getLogger(__name__)
_threads: list[threading.Thread] = []


def dispatch(task_name: str, args: list | tuple = (), countdown: int | None = None, queue: str = "default") -> str:
    s = get_settings()
    if s.celery_eager:
        from . import tasks

        fn: Callable[..., Any] = getattr(tasks, task_name).run

        def _run() -> None:
            import time
            if countdown:
                time.sleep(min(countdown, 3))  # eager modda beklemeyi kısalt
            try:
                fn(*args)
            except Exception:  # noqa: BLE001
                log.exception("eager görev hatası: %s", task_name)

        t = threading.Thread(target=_run, daemon=True, name=f"eager-{task_name}")
        t.start()
        _threads.append(t)
        return f"eager-{t.ident}"
    from .celery_app import celery

    res = celery.send_task(f"backend.workers.tasks.{task_name}", args=list(args), countdown=countdown, queue=queue)
    return res.id


def wait_eager(timeout: float = 120) -> None:
    for t in list(_threads):
        t.join(timeout)
    _threads.clear()
