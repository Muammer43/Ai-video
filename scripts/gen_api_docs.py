#!/usr/bin/env python3
"""OpenAPI şemasından docs/openapi.json ve docs/05_API_REFERANS.md üretir (kod değişince yeniden çalıştırın)."""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENV", "test")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.main import app  # noqa: E402

spec = app.openapi()
root = Path(__file__).resolve().parents[1] / "docs"
(root / "openapi.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1))
groups: dict[str, list] = {}
for path, ops in sorted(spec["paths"].items()):
    for method, op in ops.items():
        tag = (op.get("tags") or ["diğer"])[0]
        groups.setdefault(tag, []).append((method.upper(), path, op.get("summary", "") or op.get("operationId", "")))
head = """# 05 — API Referansı

Etkileşimli doküman (Swagger UI): **`/docs`** · ReDoc: `/redoc` · OpenAPI JSON: `/openapi.json` (bu dizinde `openapi.json`).

## Genel kurallar
- **Kimlik doğrulama:** `POST /api/v1/auth/login` → `access_token` (JWT, 30 dk) + `refresh_token` (30 gün, tek kullanımlık, rotasyonlu).
  Tüm uçlar `Authorization: Bearer <access_token>` ister (yalnızca `/api/health`, `/api/v1/health`, `/api/v1/oauth/*/callback`, `/api/v1/media/{token}` hariç).
  Yenileme anahtarı yeniden kullanılırsa kullanıcının tüm oturumları kapatılır (çalıntı token tespiti).
- **Hata biçimi:** `{"error": {"code": "...", "message": "Türkçe açıklama", "data": {...}}}` — örn. `auth_required`, `validation_error`, `budget_exceeded`, `per_video_budget`, `rate_limited`, `critical_findings`.
- **Idempotency:** `POST /api/v1/projects` için `Idempotency-Key` başlığı. Aynı anahtar + aynı gövde aynı projeyi döndürür (`replayed: true`); farklı gövde `409 idempotency_mismatch`.
- **Rate limit:** IP başına dakikada 240 istek, giriş denemesi IP+e-posta başına dakikada 10 (`429` + `Retry-After`).
- **Canlı ilerleme:** `GET /api/v1/projects/{id}/stream` ve `GET /api/v1/events/stream` — Server-Sent Events (`event: progress`, `event: end`); `Last-Event-ID` ile kaldığı yerden devam. Token URL'de değil `Authorization` başlığında gönderilir.
- **Dosya erişimi:** `GET /api/v1/projects/{id}/media` kısa ömürlü, kullanıcıya bağlı imzalı yol döndürür → `GET /api/v1/media/{token}` (HTTP Range destekli; S3'te presigned yönlendirme).
- **Proje durumları:** `QUEUED, PROCESSING, WAITING_PROVIDER, RENDERING, QUALITY_CHECK, APPROVED, NEEDS_REVIEW, PUBLISHING, PUBLISHED, FAILED, CANCELLED`. `PUBLISHED` yalnızca platform doğrulamasından sonra yazılır.
- **V1 uyumluluk:** `/api/jobs`, `/api/jobs/{id}`, `/api/jobs/{id}/video`, `/api/jobs/{id}/publish`, `/api/health`, `/api/config` (kimlik doğrulamalı; kimlikler artık UUID).

## Uç noktalar
"""
body = ""
for tag, items in groups.items():
    body += f"\n### {tag}\n\n| Yöntem | Yol | Özet |\n|---|---|---|\n"
    for m, p, s in items:
        body += f"| `{m}` | `{p}` | {s.replace('_', ' ')} |\n"
(root / "05_API_REFERANS.md").write_text(head + body)
print(sum(len(v) for v in groups.values()), "uç nokta belgelendi")
