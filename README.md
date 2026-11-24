# AI Video Factory Pro V2

Android telefondan yönetilen, **bulutta 7/24 çalışan** otonom AI video üretim ve yayın platformu:
**konu → araştırma → fikir → senaryo → storyboard → ses → görsel/video → kurgu → kalite kontrol → yayın → performans öğrenmesi.**

> V1 MVP (`legacy_v1/`) korunmuştur; V2 onun üzerine mimari olarak yeniden kurulmuştur ve V1 API uçları uyumluluk katmanıyla sürer.
> Ayrıntılı V1 analizi: [`docs/01_V1_MEVCUT_DURUM_RAPORU.md`](docs/01_V1_MEVCUT_DURUM_RAPORU.md).

## Dürüstlük ilkeleri (bu üründe tasarım gereği)
1. API anahtarı yoksa sağlayıcı **"yapılandırılmamış"** görünür; çalışıyormuş gibi gösterilmez.
2. Yerel yedek sağlayıcılar (şablon senaryo, FFmpeg gradyan görsel, görselden hareket, espeak-ng ses) **AI değildir**, `origin` etiketiyle raporlanır ve **otomatik yayına alınmaz**.
3. `PUBLISHED` durumu yalnızca **platformun doğrulamasından** sonra yazılır (YouTube `videos.list` işlendi + gerçek gizlilik, TikTok `PUBLISH_COMPLETE`, Instagram konteyner `FINISHED` + medya sorgusu).
4. "Tam AI video" modunda gerçek hareketli AI video alınamazsa video **inceleme gerekli**ye düşer; slayt, AI video diye sunulmaz.
5. Maliyetler gizlenmez: üretim öncesi tahmin, kalem kalem defter, "tahmini / sağlayıcı bildirimi" ayrımı.
6. Mock ile test edilenler test raporunda **mock** olarak, canlı doğrulanamayanlar **doğrulanmadı** olarak işaretlidir ([`docs/08_TEST_RAPORU.md`](docs/08_TEST_RAPORU.md)).

## Mimari
```
Android (Flutter) ──HTTPS──▶ Caddy ──▶ FastAPI ──▶ PostgreSQL
   ▲  SSE / yerel bildirim                │ ▲
   │                                      ▼ │
   └──────────── bildirim ◀── Celery worker/beat ◀── Redis
                               │  FFmpeg editör + 14+ kontrollü QC
                               ▼
        Sağlayıcılar: LLM · Görsel · Video · TTS · STT · Stok     → S3/MinIO depolama
        Yayın: YouTube Data API · TikTok Content Posting API · Instagram Graph API
```
Ayrıntı: [`docs/02_V2_MIMARI_VE_PLAN.md`](docs/02_V2_MIMARI_VE_PLAN.md).

## Hızlı başlangıç
**Geliştirme (tek komut, Redis/PostgreSQL gerekmez):**
```bash
scripts/run_dev.sh                 # http://localhost:8000  (web konsolu)  ·  /docs (Swagger)
```
**Üretim (Docker, otomatik HTTPS):**
```bash
python scripts/gen_keys.py         # çıktıyı .env'ye yapıştırın (cp .env.example .env)
docker compose up -d --build       # caddy + api + worker + beat + postgres + redis + minio
```
Ayrıntılı kurulum, Android APK ve bağlama: [`docs/03_KURULUM.md`](docs/03_KURULUM.md) · [`docs/04_ANDROID_KULLANIM.md`](docs/04_ANDROID_KULLANIM.md).

## Dizin yapısı
```
backend/        FastAPI + iş mantığı  (api, core, models, schemas, services, providers, workers, automation, quality, editor, analytics, storage, database)
android_app/    Flutter Android uygulaması (10 ekran) + tool/connect_check.dart
frontend/       Web yönetim konsolu (aynı API)
workers/ providers/   → kodun yaşadığı backend/ yollarına işaret eden README'ler (kod tekrarı yok)
database/       Alembic göçleri
docker/ scripts/ docs/ tests/ legacy_v1/
```

## Testler
`scripts/run_tests.sh` (SQLite) · `TEST_DATABASE_URL=postgresql://… scripts/run_tests.sh` (PostgreSQL) · `cd android_app && flutter test` ·
`dart run tool/connect_check.dart http://sunucu:8000` · `node tests/e2e/web_console.js http://sunucu:8000` · `scripts/clean_install_test.sh`.
Sonuçlar: [`docs/08_TEST_RAPORU.md`](docs/08_TEST_RAPORU.md).

## Dokümanlar
| | |
|---|---|
| `docs/01` | V1 durum raporu (ölçülmüş bulgular) |
| `docs/02` | Mimari ve geliştirme planı |
| `docs/03` | Kurulum kılavuzu |
| `docs/04` | Android kullanım kılavuzu |
| `docs/05` | API referansı (+ `/docs` Swagger) |
| `docs/06` | Maliyet ve güvenlik |
| `docs/07` | Sağlayıcılar: doğrulanan API bilgileri ve sınırlar |
| `docs/08` | Test raporu ve bilinen sınırlar |
