# AI Video Factory V1 — Android yönetimli MVP

Bu proje; konu → Türkçe senaryo → sahne görselleri → dikey MP4 render → temel kalite kontrolü akışını çalışan bir MVP olarak sunar. Mobil arayüz PWA'dır; Android Chrome üzerinden ana ekrana eklenebilir.

## Gerçekçi kapsam / önemli sınırlar

- API anahtarı olmadan demo senaryosu ve FFmpeg ile metin tabanlı test videosu üretir. Bu, gerçek AI video görüntüsü değildir.
- `OPENAI_API_KEY` ve `USE_AI_IMAGES=true` ayarlanırsa sahne görselleri OpenAI Images API ile üretilir ve FFmpeg ile hareketli dikey kliplere dönüştürülür.
- `USE_AI_VOICE=true` ayarlanırsa OpenAI TTS ile ses dosyası oluşturulur. V1 renderer ses parçasını henüz videoya mux etmez; bu, V1.1 geliştirme maddesidir.
- Gerçek metinden hareketli video üretimi (text-to-video) için ayrı bir video sağlayıcı adaptörü gerekir. V1'de bu entegrasyon yoktur; görsel üretimi + hareketli kurgu kullanılır.
- YouTube, TikTok ve Instagram canlı yayınlama OAuth/API bağlantıları bu MVP'de uygulanmamıştır. Sistem hiçbir zaman yayın yapılmadığı halde "yayınlandı" demez. Resmî API izinleri ve platforma özel upload akışları sonraki entegrasyon aşamasıdır.
- Otomatik kalite puanı teknik bir ilk kapıdır; içerik doğruluğu, telif ve platform politikası için insan kontrolünün yerini tutmaz.

## 1. Bilgisayarda çalıştırma (en kolay)

Python 3.11+, FFmpeg ve ffprobe kurulu olmalı.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Tarayıcıdan `http://127.0.0.1:8000` aç.

## 2. Android telefonda Termux ile çalıştırma

1. Termux'u güncel F-Droid/GitHub sürümünden kur.
2. Termux içinde:

```bash
pkg update -y && pkg upgrade -y
pkg install python ffmpeg git -y
```

3. ZIP'i telefonuna çıkar. Proje klasörüne Termux'tan gir.
4. Çalıştır:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

5. Telefonda Chrome ile `http://127.0.0.1:8000` adresini aç.
6. Chrome menüsünden **Ana ekrana ekle** seçeneğini kullan.

Termux'u kapatmak backend'i durdurur. Android pil optimizasyonu ve arka plan kısıtlamaları da uzun görevleri kesebilir. Sürekli otomasyon için V1.5'te VPS/worker dağıtımı önerilir.

## 3. OpenAI AI görsellerini açma

`.env` dosyasında:

```env
OPENAI_API_KEY=anahtarini_buraya_yaz
USE_AI_IMAGES=true
USE_AI_VOICE=false
```

Anahtarını paylaşma, APK içine gömme veya GitHub'a yükleme. Görsel üretimi API kullanımına göre ücretlidir. İlk denemeyi tek video ve düşük üretim adediyle yap.

İsteğe bağlı TTS:

```env
USE_AI_VOICE=true
```

Not: V1 TTS çıktısını üretir fakat MP4'e ses mux işlemi henüz tamamlanmış değildir.

## 4. Android'den kullanım

- Konu gir.
- Kategori, stil ve süre seç.
- YouTube Shorts / TikTok / Instagram hedeflerini işaretle.
- Üretimi başlat.
- İşler listesinden ilerlemeyi izle.
- Hazır MP4'ü aç.

## 5. API uçları

- `GET /api/health`
- `POST /api/jobs`
- `GET /api/jobs`
- `GET /api/jobs/{id}`
- `GET /api/jobs/{id}/video`
- `POST /api/jobs/{id}/publish`

Örnek iş isteği:

```json
{
  "topic": "GTA 6 hakkında bilinmeyen 5 detay",
  "category": "Oyun",
  "style": "cinematic",
  "duration": 30,
  "platforms": ["youtube", "tiktok", "instagram"]
}
```

## 6. V1 sonrası zorunlu geliştirmeler

1. Worker kuyruğu: Redis + Celery/RQ, retry, idempotency, job locking.
2. Ses: TTS dosyasını sahnelere göre zamanlama, altyazı (SRT/ASS), müzik miksajı, loudness normalizasyonu.
3. Gerçek video sağlayıcı adaptörü: sağlayıcıya göre async job oluşturma, polling, webhook ve maliyet takibi.
4. Kalite kontrol: ffprobe, sessizlik, siyah kare, OCR, altyazı-ses hizası, içerik güvenliği ve telif kontrol listesi.
5. Yayınlama: YouTube Data API, TikTok Content Posting API, Instagram Graph API için ayrı OAuth bağlantıları; hesap uygunluğu, token yenileme, medya URL şartları, yayın durum sorgusu.
6. Çok kullanıcılı güvenlik: kullanıcı hesabı, şifreli token saklama, rate limit, audit log, HTTPS, yedekleme.
7. PostgreSQL + nesne depolama (S3 uyumlu) ve VPS deployment.

## Güvenlik

Bu MVP internete açık şekilde doğrudan yayınlanmamalıdır. Kimlik doğrulama, HTTPS, kullanıcı izolasyonu ve gizli anahtar yönetimi eklenmeden portu internete açma. `data/` klasörünü ve `.env` dosyasını yedekle/gizli tut.
