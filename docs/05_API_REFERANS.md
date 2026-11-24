# 05 — API Referansı

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

### v1-compat

| Yöntem | Yol | Özet |
|---|---|---|
| `GET` | `/api/config` | Config |
| `GET` | `/api/health` | Health |
| `GET` | `/api/jobs` | List Jobs |
| `POST` | `/api/jobs` | Create Job |
| `GET` | `/api/jobs/{job_id}` | Get Job |
| `POST` | `/api/jobs/{job_id}/publish` | Publish |
| `GET` | `/api/jobs/{job_id}/video` | Get Video |

### ops

| Yöntem | Yol | Özet |
|---|---|---|
| `POST` | `/api/v1/analytics/collect` | Analytics Collect |
| `GET` | `/api/v1/analytics/experiments` | Experiments |
| `POST` | `/api/v1/analytics/experiments` | Experiment Create |
| `DELETE` | `/api/v1/analytics/experiments/{eid}` | Experiment Stop |
| `GET` | `/api/v1/analytics/insights` | Analytics Insights |
| `GET` | `/api/v1/analytics/overview` | Analytics Overview |
| `GET` | `/api/v1/costs/budget` | Budget Get |
| `PUT` | `/api/v1/costs/budget` | Budget Put |
| `GET` | `/api/v1/costs/ledger` | Cost Ledger |
| `POST` | `/api/v1/costs/resume` | Budget Resume |
| `GET` | `/api/v1/costs/summary` | Cost Summary |
| `GET` | `/api/v1/dashboard` | Dashboard Get |
| `POST` | `/api/v1/devices` | Device Register |
| `GET` | `/api/v1/integrations` | Integrations |
| `DELETE` | `/api/v1/integrations/accounts/{aid}` | Integration Disconnect |
| `POST` | `/api/v1/integrations/{platform}/authorize` | Integration Authorize |
| `GET` | `/api/v1/music` | Music List |
| `POST` | `/api/v1/music` | Music Upload |
| `DELETE` | `/api/v1/music/{tid}` | Music Delete |
| `GET` | `/api/v1/notifications` | Notifications |
| `POST` | `/api/v1/notifications/read` | Notifications Read |
| `GET` | `/api/v1/providers` | Providers |
| `PUT` | `/api/v1/providers/preferences` | Provider Prefs |
| `PUT` | `/api/v1/providers/{name}/credential` | Provider Cred Set |
| `DELETE` | `/api/v1/providers/{name}/credential` | Provider Cred Del |
| `POST` | `/api/v1/providers/{name}/test` | Provider Test |
| `GET` | `/api/v1/settings` | Settings Get |
| `PUT` | `/api/v1/settings/quality` | Settings Quality |
| `GET` | `/api/v1/system/status` | System Status |

### projects

| Yöntem | Yol | Özet |
|---|---|---|
| `GET` | `/api/v1/assets/{asset_id}/download` | Download |
| `GET` | `/api/v1/events/stream` | Stream All |
| `GET` | `/api/v1/media/{token}` | Media |
| `POST` | `/api/v1/projects` | Create |
| `GET` | `/api/v1/projects` | List Projects |
| `POST` | `/api/v1/projects/estimate` | Estimate |
| `GET` | `/api/v1/projects/{pid}` | Get One |
| `DELETE` | `/api/v1/projects/{pid}` | Delete |
| `POST` | `/api/v1/projects/{pid}/approve` | Approve |
| `POST` | `/api/v1/projects/{pid}/cancel` | Cancel |
| `GET` | `/api/v1/projects/{pid}/events` | Events |
| `GET` | `/api/v1/projects/{pid}/media` | Media Links |
| `POST` | `/api/v1/projects/{pid}/publish` | Publish Now |
| `POST` | `/api/v1/projects/{pid}/reject` | Reject |
| `POST` | `/api/v1/projects/{pid}/retry` | Retry |
| `GET` | `/api/v1/projects/{pid}/stream` | Stream |

### auth

| Yöntem | Yol | Özet |
|---|---|---|
| `POST` | `/api/v1/auth/change-password` | Change Password |
| `POST` | `/api/v1/auth/login` | Login |
| `POST` | `/api/v1/auth/logout` | Logout |
| `GET` | `/api/v1/auth/me` | Me |
| `POST` | `/api/v1/auth/refresh` | Refresh |
| `POST` | `/api/v1/auth/register` | Register |

### content

| Yöntem | Yol | Özet |
|---|---|---|
| `POST` | `/api/v1/automation/pause` | Automation Pause |
| `POST` | `/api/v1/automation/resume` | Automation Resume |
| `GET` | `/api/v1/automation/status` | Automation Status |
| `GET` | `/api/v1/calendar` | Calendar |
| `GET` | `/api/v1/channels` | Channels |
| `POST` | `/api/v1/channels` | Channel Create |
| `PUT` | `/api/v1/channels/{cid}` | Channel Update |
| `DELETE` | `/api/v1/channels/{cid}` | Channel Delete |
| `POST` | `/api/v1/channels/{cid}/logo` | Channel Logo |
| `POST` | `/api/v1/channels/{cid}/run-now` | Channel Run |
| `GET` | `/api/v1/ideas` | Ideas |
| `POST` | `/api/v1/ideas/generate` | Ideas Generate |
| `DELETE` | `/api/v1/ideas/{iid}` | Idea Reject |
| `POST` | `/api/v1/ideas/{iid}/produce` | Idea Produce |
| `POST` | `/api/v1/publications/{pid}/cancel` | Pub Cancel |
| `POST` | `/api/v1/publications/{pid}/reschedule` | Pub Reschedule |
| `POST` | `/api/v1/publications/{pid}/retry` | Pub Retry |
| `GET` | `/api/v1/tasks` | Tasks |
| `GET` | `/api/v1/tasks/{tid}` | Task Get |
| `POST` | `/api/v1/tasks/{tid}/cancel` | Task Cancel |
| `GET` | `/api/v1/trends` | Trends |
| `POST` | `/api/v1/trends/refresh` | Trends Refresh |

### system

| Yöntem | Yol | Özet |
|---|---|---|
| `GET` | `/api/v1/health` | Health V1 |
