# 02 — AI Video Factory Pro V2: Mimari ve Geliştirme Planı

## 1. Genel mimari

```
Android (Flutter)  ──HTTPS──▶  Caddy (TLS)  ──▶  FastAPI (api)  ──▶ PostgreSQL
      ▲  SSE / push                                   │  ▲
      │                                               ▼  │
      └────────────── bildirim ◀── Celery workers ◀── Redis (broker, kilit, rate limit)
                                       │   │
                    ┌──────────────────┘   └───────────────────┐
                    ▼                                          ▼
         Sağlayıcı katmanı (LLM/Görsel/Video/TTS/STT/Stok)   FFmpeg editör + QC
                    │                                          │
                    └────────────▶ S3 uyumlu depolama ◀────────┘
                                   (MinIO / S3 / yerel dizin)
        Yayınlama: YouTube Data API · TikTok Content Posting API · Instagram Graph API
```

Telefon yalnızca **kontrol paneli**dir. Üretim, render ve yayın bulutta Celery işçilerinde koşar;
uygulama kapansa da devam eder. İlerleme `job_events` tablosundan SSE ile akar.

## 2. Üretim hattı ve durum makinesi

`TOPIC → RESEARCH → IDEA → SCRIPT → STORYBOARD → ASSETS → VOICE → EDIT → QC → PUBLISH`

Proje durumları (zorunlu liste): `QUEUED, PROCESSING, WAITING_PROVIDER, RENDERING, QUALITY_CHECK,
APPROVED, NEEDS_REVIEW, PUBLISHING, PUBLISHED, FAILED, CANCELLED`.

- Her aşama **idempotent**: çıktısı (script, sahne varlıkları, ses…) zaten varsa atlanır; böylece
  "yeniden dene" kaldığı yerden devam eder.
- Aynı işin iki kez çalışması: veritabanında *compare-and-swap* (`UPDATE … WHERE status IN (…)` rowcount) +
  Redis kilidi (varsa) + Celery `acks_late`. API tarafında `Idempotency-Key` başlığı.
- İptal: `cancel_requested` bayrağı aşama sınırlarında ve sağlayıcı polling döngülerinde kontrol edilir.
- Zaman aşımı: Celery `soft_time_limit/time_limit` + proje seviyesi son tarih + takılı iş temizleyici (beat).
- Yayın kararı (QC): 90–100 otomatik; 80–89 yalnızca risk bayrağı yoksa; 60–79 kullanıcı incelemesi;
  0–59 reddedilir (FAILED, `qc_decision=rejected`, yeniden üretim önerisi). **Kritik bayrak puandan bağımsız yayını engeller.**

## 3. Dizin yapısı

```
backend/
  api/            FastAPI yönlendiricileri (v1) + uyumluluk (/api/jobs)
  core/           ayarlar, güvenlik, log, hata, rate limit, şifreleme
  models/         SQLAlchemy ORM
  schemas/        Pydantic şemaları
  database/       oturum/engine
  services/       iş mantığı (projeler, maliyet, bildirim, kimlik…)
  providers/      llm/ image/ video/ tts/ stt/ stock/ music/ publishing/ + router + fiyatlar
  workers/        Celery uygulaması, pipeline, beat görevleri
  automation/     otomasyon motoru (kanal zamanlayıcı, trend→fikir→proje)
  quality/        14 kontrollü QC motoru
  editor/         FFmpeg editör (sahne, geçiş, altyazı, miks, renk, kapak)
  analytics/      metrik toplama, öğrenme motoru, A/B
  storage/        yerel + S3 depolama
  security/       (core/security ile birlikte) şifreleme, parola, JWT
  tests/          (kök tests/ altında)
android_app/      Flutter (Android) uygulaması
frontend/         Web yönetim konsolu (aynı API)
database/         Alembic göçleri + init SQL
docker/ scripts/ docs/ tests/ legacy_v1/
```

`workers/` ve `providers/` kök dizinlerinde, kodun yaşadığı `backend/` yollarına işaret eden README ve
çalıştırma betikleri bulunur (kod tekrarı yok).

## 4. Sağlayıcı mimarisi (doğrulanmış dokümanlara göre — 2026-11-24)

Her tür için `Provider` soyut sınıfı: `name`, `kind`, `is_configured()`, `estimate_cost()`, `run()`; hata sınıfları
`transient / rate_limit / auth / permanent / budget`. `ProviderRouter` kullanıcı tercih sırasına göre dener,
geçici hatada bir sonrakine düşer, her çağrıyı `provider_stats` ve `cost_ledger` tablolarına yazar
(maliyet, gecikme, başarı, son hata). **Pahalı sağlayıcıya otomatik geçiş**, bütçe politikası izin vermezse engellenir.

| Tür | Gerçek HTTP adaptörleri | Yerel/çevrimdışı (etiketli, AI değil) |
|---|---|---|
| LLM | OpenAI Chat Completions, Anthropic Messages | `template` (şablon) |
| Görsel | OpenAI Images (`gpt-image-2` ailesi; **gpt-image-1 kapatıldı**), fal.ai | `procedural` (FFmpeg) |
| Video | fal.ai queue (Kling/Veo/Wan i2v+t2v), Runway (`/v1/image_to_video`, `/v1/text_to_video`), Replicate | `ken_burns` (still→hareket; **AI video değil**, etiketli) |
| Stok | Pexels (`/v1/videos/search`), Pixabay | — |
| TTS | OpenAI (`/v1/audio/speech`), ElevenLabs | `espeak-ng` (yerel) |
| STT | OpenAI transcriptions (`whisper-1`, kelime zamanlı `verbose_json`) | `aligner` (tahmini zamanlama, etiketli) |
| Müzik | Kullanıcı lisanslı kütüphane (lisans alanı zorunlu) | `synth` (FFmpeg ile sentez, lisans sorunu yok) |

Doğrulama notları (kaynak: sağlayıcı dokümanları, 2026-11-24): OpenAI Sora/Videos API kapatılmış (adaptör **yok**);
`tts-1`/`gpt-4o-mini-tts` 2027-01-06'da kapanacak (model adı yapılandırılabilir); Anthropic yeni API sürümünde
`temperature` göndermek 400 döndürür (gönderilmez); Freesound API ticari kullanıma sözleşme gerektirir ve Pixabay'da
müzik API'si yoktur → otomatik müzik indirme **uygulanmadı**, yerine lisanslı kütüphane + sentez.
Fiyat tablosu `providers/pricing.py` içindedir, tarih ve kaynak etiketlidir, `PRICING_OVERRIDES_JSON` ile ezilebilir.

## 5. Yayınlama

Her platform ayrı sağlayıcı + OAuth 2.0 (PKCE). Tokenlar Fernet ile şifrelenir. `PUBLISHED` yalnızca platform doğrulamasıyla:
YouTube `videos.list` (`status.uploadStatus` işlenmiş + gerçek `privacyStatus` okunur), TikTok `publish/status/fetch`
(`PUBLISH_COMPLETE`), Instagram konteyner `FINISHED` + `media_publish` sonrası medya sorgusu. Doğrulanamazsa durum
`PUBLISHING`/`FAILED` kalır. TikTok denetimsiz istemcilerde yalnızca `SELF_ONLY` yayınlanabilir; sistem bunu kullanıcıya bildirir.
Instagram yayını, videonun herkese açık erişilebilir HTTPS URL'si gerektirir (kısa ömürlü imzalı URL).

## 6. Geliştirme planı (fazlar)

| Faz | Kapsam | Çıkış ölçütü |
|---|---|---|
| 1 | Analiz + mimari | Bu iki belge |
| 2 | Backend iskeleti, DB, auth, depolama, API temeli | Testler + gerçek PostgreSQL ile çalışma |
| 3 | Sağlayıcı altyapısı + router + maliyet | Sağlayıcı mock testleri + yerel sağlayıcılar |
| 4 | Görsel/ses/video üretim hattı | Uçtan uca varlık üretimi |
| 5 | Editör + QC | **Gerçek MP4 + ffprobe doğrulaması** |
| 6 | Celery otomasyon | Gerçek Redis + worker testi |
| 7 | Android uygulaması | `flutter analyze/test` + APK derleme |
| 8 | Yayınlama adaptörleri + OAuth | HTTP-mock adaptör testleri (canlı API ile test **edilmedi**) |
| 9 | Analiz/öğrenme/A-B | İstatistik birim testleri |
| 10 | Test, güvenlik, paketleme | Rapor + ZIP |

## 7. Dürüstlük ilkeleri (tasarım gereği)

1. Sağlayıcı anahtarı yoksa o sağlayıcı "yapılandırılmamış" görünür; hiçbir zaman çalışıyormuş gibi gösterilmez.
2. Yerel yedek sağlayıcılar çıktıyı `origin` etiketiyle işaretler (`ai_video`, `ai_image_motion`, `stock`, `slideshow`, `procedural`).
3. `media_mode=ai_video` seçilip hareketli AI video elde edilemediyse proje `NEEDS_REVIEW`'a düşer.
4. Mock ile test edilen entegrasyonlar test raporunda "mock" olarak, canlı doğrulanmayanlar "doğrulanmadı" olarak işaretlenir.
