# workers/

Celery işçileri ve zamanlayıcı **`backend/workers/`** altındadır (kod tekrarı olmaması için burada yalnızca giriş noktaları belgelenir).

| Bileşen | Dosya | Çalıştırma |
|---|---|---|
| Celery uygulaması + beat takvimi | `backend/workers/celery_app.py` | — |
| Görevler (proje, fikir, trend, yayın, metrik, reaper, scheduler) | `backend/workers/tasks.py` | — |
| Üretim hattı (SCRIPT→STORYBOARD→VOICE→ASSETS→EDIT→QC) | `backend/workers/pipeline.py` | — |
| Görev gönderme (Celery / eager) | `backend/workers/dispatch.py` | — |
| Worker | `celery -A backend.workers.celery_app worker -Q default,render -c 2` | `docker/entrypoint.sh worker` |
| Beat | `celery -A backend.workers.celery_app beat` | `docker/entrypoint.sh beat` |

Garantiler: `acks_late` + `reject_on_worker_lost`; **CAS ile tek çalışma** (`QUEUED→PROCESSING` rowcount); aşama başına idempotent çıktı; iptal/zaman aşımı kontrolü; takılı işleri `reap_stuck_task` (2 dk) toparlar; geçici hatalarda üstel geri çekilmeyle (en çok 3 deneme) yeniden kuyruğa alır.
Gerçek Redis+worker davranışı `tests/integration/celery_e2e.py` ile test edilir (çift gönderim → tek çalışma; worker `SIGKILL` → kurtarma).
