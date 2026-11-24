# 03 — Kurulum Kılavuzu

## Gereksinimler
| Bileşen | Sürüm | Not |
|---|---|---|
| Python | 3.11+ (3.12/3.13 test edildi) | |
| FFmpeg + ffprobe | 6+ | `libass` (altyazı) ve `libx264` zorunlu |
| espeak-ng | 1.50+ | yalnızca çevrimdışı yedek TTS için (isteğe bağlı) |
| PostgreSQL | 14+ (16 test edildi) | üretim |
| Redis | 6+ (7 test edildi) | görev kuyruğu |
| Docker + Compose v2 | | üretim dağıtımı |
| Flutter | 3.50 (Dart 3.14) + Android SDK 37 | yalnızca APK derlemek için |
| Font | DejaVu Sans (Türkçe karakterler) | Docker imajında hazır |

## A) Geliştirme (Docker'sız, tek süreç)
```bash
git clone <repo> && cd Ai-video
scripts/run_dev.sh          # venv + bağımlılıklar + uvicorn (SQLite, yerel depolama, eager kuyruk)
```
Eager kuyruk işleri süreç içi iş parçacığında çalıştırır — **yalnızca geliştirme**. Gerçek kuyruk için B/C.

## B) Elle üretim benzeri (PostgreSQL + Redis, Docker'sız)
```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
export ENV=prod SECRET_KEY=... ENCRYPTION_KEY=... DATABASE_URL=postgresql://aivf:***@localhost/aivf \
       REDIS_URL=redis://localhost:6379/0 STORAGE_BACKEND=local LOCAL_STORAGE_DIR=/var/lib/aivf/storage PUBLIC_BASE_URL=https://video.alanadiniz.com
.venv/bin/alembic upgrade head
.venv/bin/uvicorn backend.main:app --port 8000 &
.venv/bin/celery -A backend.workers.celery_app worker -Q default,render -c 2 &
.venv/bin/celery -A backend.workers.celery_app beat -s /tmp/beat &
```
Bu akış `scripts/clean_install_test.sh` ile otomatik doğrulanır (sıfır venv, yalnızca `requirements.txt`).

## C) Docker Compose (önerilen)
```bash
cp .env.example .env && python scripts/gen_keys.py   # çıkan satırları .env'ye yazın; DOMAIN'i ayarlayın
docker compose up -d --build
docker compose logs -f api worker
```
- DNS'te `DOMAIN` sunucuya işaret etmeli; **Caddy** Let's Encrypt sertifikasını otomatik alır (80/443 açık olmalı).
- İlk hesabı uygulamadan/`/` konsolundan oluşturun (ilk kullanıcı **admin** olur), sonra `.env` içinde `ALLOW_REGISTRATION=false` yapıp `docker compose up -d`.
- Ölçekleme: `docker compose up -d --scale worker=3`; işçi başına eşzamanlılık `WORKER_CONCURRENCY` (varsayılan 2; render CPU yoğundur).
- Şema güncellemeleri `api` konteyneri açılırken `alembic upgrade head` ile uygulanır.

> **Doğrulama durumu:** Compose dosyası `docker compose config` ile sözdizimi açısından doğrulandı. Bu geliştirme ortamında Docker daemon bulunmadığından imajlar **derlenmedi/çalıştırılmadı**; aynı yığının Docker'sız eşdeğeri (PostgreSQL+Redis+API+worker+beat) temiz ortamda çalıştırılıp test edildi.

## AI sağlayıcı anahtarları
İki yol: (1) `.env` içine sunucu düzeyinde, (2) **uygulama → AI Modelleri → Anahtar ekle** (kullanıcı başına, DB'de Fernet ile şifreli, hiçbir yerde düz metin görünmez).
Minimum gerçek AI hattı için: bir LLM (OpenAI veya Anthropic) + bir TTS (OpenAI veya ElevenLabs) + (hareketli video için) fal.ai veya Runway; stok video için Pexels/Pixabay.

## Sosyal medya OAuth
Her platform için geliştirici uygulaması oluşturup yönlendirme (redirect) adresini kaydedin:
`https://DOMAIN/api/v1/oauth/{youtube|tiktok|instagram}/callback`.
| Platform | `.env` | Not |
|---|---|---|
| YouTube | `GOOGLE_CLIENT_ID/SECRET` | YouTube Data API v3 etkin; yükleme kapsamı `youtube.upload`; günlük 100 yükleme varsayılan kota |
| TikTok | `TIKTOK_CLIENT_KEY/SECRET` | Content Posting API + `video.publish`; **denetimsiz uygulama yalnızca özel (SELF_ONLY) paylaşabilir** |
| Instagram | `INSTAGRAM_APP_ID/SECRET` | Business/Creator hesap; video herkese açık **HTTPS** URL'den erişilebilir olmalı |
Hesap türü/izin uygun değilse uygulama nedenini kullanıcıya açıkça gösterir (Entegrasyonlar ekranı).

## Yedekleme
`scripts/backup.sh /var/backups/aivf` (PostgreSQL dökümü + yerel depolama arşivi + SHA256; 14 gün saklama) — cron: `15 3 * * *`. Geri yükleme: `scripts/restore.sh db_*.dump`.
S3/MinIO için nesneleri `mc mirror` ile ayrıca yedekleyin. Yedek/geri yükleme PostgreSQL üzerinde doğrulandı.

## Sorun giderme
| Belirti | Neden / çözüm |
|---|---|
| İşler `QUEUED`'da bekliyor | Worker yok: `docker compose logs worker`; Dashboard'daki "İşçi: YOK" göstergesi |
| `SECRET_KEY üretimde değiştirilmelidir` | `ENV=prod` iken varsayılan anahtar yasak — `scripts/gen_keys.py` |
| Altyazıda kare/eksik harf | Türkçe destekli font gerekir (DejaVu Sans); `FONT_DIR` |
| TikTok `NEEDS_ACTION` | Uygulama denetimsiz → yalnızca SELF_ONLY; denetimi tamamlayın |
| Instagram `HTTPS` hatası | `PUBLIC_BASE_URL` https olmalı ve internetten erişilebilir |
