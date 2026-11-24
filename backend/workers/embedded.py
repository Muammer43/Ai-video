"""Gömülü zamanlayıcı: CELERY_EAGER=true (Redis/beat olmayan, tek süreçli kurulum — ör. Termux) için `celery beat` yerine geçer.
Üretimde (Redis + beat) KULLANILMAZ; orada celery_app.beat_schedule çalışır."""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)
_started = False

# (görev adı, saniye)
SCHEDULE = [("scheduler_tick_task", 60), ("reap_stuck_task", 120), ("publish_due_task", 60), ("collect_metrics_task", 1800), ("refresh_trends_task", 6 * 3600)]


def run_due(last: dict[str, float], now: float) -> list[str]:
    """Zamanı gelen görevleri çalıştırır (saf mantık: test edilebilir). Çalışanların adlarını döndürür."""
    from . import tasks

    ran = []
    for name, every in SCHEDULE:
        if now - last.get(name, 0.0) >= every:
            last[name] = now
            try:
                getattr(tasks, name).run()
            except Exception:  # noqa: BLE001
                log.exception("gömülü zamanlayıcı görev hatası: %s", name)
            ran.append(name)
    return ran


def start() -> bool:
    global _started
    if _started:
        return False
    _started = True
    last: dict[str, float] = {n: time.time() for n, _ in SCHEDULE}  # açılışta hemen değil, ilk aralıktan sonra
    last["reap_stuck_task"] = 0.0  # ama takılı işleri açılışta hemen toparla (süreç öldürülmüş olabilir)

    def loop() -> None:
        time.sleep(5)
        while True:
            run_due(last, time.time())
            time.sleep(15)

    threading.Thread(target=loop, daemon=True, name="embedded-scheduler").start()
    log.info("gömülü zamanlayıcı başlatıldı (eager mod)")
    return True
