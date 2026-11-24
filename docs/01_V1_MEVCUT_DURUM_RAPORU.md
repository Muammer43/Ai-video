# 01 — V1 MVP Mevcut Durum Raporu (FAZ 1)

İncelenen paket: `AI_Video_Factory_V1_MVP.zip` (20 dosya, ~600 satır). Orijinal kod değiştirilmeden
`legacy_v1/` altında korunmuştur. Bulguların bir kısmı **çalıştırılarak ölçülmüştür** (ÖLÇÜLDÜ),
kalanı **kod incelemesidir** (İNCELEME) — raporda ayrım açıkça yapılmıştır.

## 1. V1 neyi yapıyor?

| Alan | V1 durumu |
|---|---|
| Backend | FastAPI, tek süreç, `BackgroundTasks` ile iş çalıştırma, SQLite (ham `sqlite3`) |
| Arayüz | Tek sayfalık PWA (`index.html`), 5 sn'de bir polling |
| Senaryo | OpenAI Chat Completions **veya** sabit şablon metin (API anahtarı yoksa) |
| Görsel | OpenAI Images (isteğe bağlı) → FFmpeg `zoompan` ile hareketli still |
| Ses | OpenAI TTS dosyası üretir ama **videoya eklenmez** |
| Kalite kontrolü | `ffprobe` süre ≥ 5 sn ve sahne ≥ 3 ise sabit **88 puan** |
| Yayınlama | Yok (`awaiting_integration` döner — bu dürüst) |
| Test | 1 adet smoke test (şablon senaryo) |

## 2. Kritik hatalar

| # | Bulgu | Kanıt | Önem |
|---|---|---|---|
| K1 | **Varsayılan yapılandırmada video render'ı çöküyor.** `render.py` `concat.txt` içine göreli yol (`data/outputs/1/clip_0.mp4`) yazıyor; ffmpeg concat demuxer göreli yolları *liste dosyasının dizinine* göre çözdüğü için dosyalar bulunamıyor. İş `failed` oluyor, `final.mp4` hiç oluşmuyor. | ÖLÇÜLDÜ (15 sn'lik iş, `status=failed`) | Kritik |
| K2 | **Kimlik doğrulama yok.** `GET /api/jobs`, `/api/jobs/{id}`, `/video` herkese açık; ID'ler 1,2,3… ardışık (numaralandırılabilir). | ÖLÇÜLDÜ (kimliksiz 200) | Kritik |
| K3 | **CORS `*`** tüm origin'lere açık. | ÖLÇÜLDÜ (`access-control-allow-origin: *`) | Yüksek |
| K4 | **Kalite puanı sahte:** `score = 88 if süre≥5 and sahne≥3 else 40`. Siyah kare, ses, altyazı, güvenlik, telif kontrol edilmiyor; iş yine de "completed / Otomatik temel kontroller geçti" yazıyor. | İNCELEME (`pipeline.py`) | Kritik |
| K5 | **Sesli video yok:** TTS çıktısı (`voice.mp3`) hiç mux edilmiyor; üretilen tüm videolar sessiz. | İNCELEME | Kritik |
| K6 | **Gerçek kuyruk yok:** işler web sürecindeki `BackgroundTasks` içinde koşuyor; süreç yeniden başlarsa iş `processing`'de sonsuza kadar kalır; iptal, yeniden deneme, zaman aşımı, idempotency, aynı işin iki kez çalışmasını engelleme yok. | İNCELEME | Kritik |
| K7 | `publish_status="queued"` değeri puan ≥ 80 olduğunda yazılıyor ama bunu tüketen hiçbir bileşen yok → kullanıcıya "yayın kuyruğunda" izlenimi veriyor. | İNCELEME | Orta |

## 3. Güvenlik açıkları ve zayıflıklar

- **FFmpeg filtre enjeksiyonu (İNCELEME):** `drawtext` metni yalnızca `'` ve `:` karakterlerinden arındırılıyor. `%{...}` metin genişletmesi, `\`, `,`, `[`, `]`, `;` filtre grafiği sözdizimini bozabilir. LLM veya kullanıcı kaynaklı metin doğrudan filtre dizgesine giriyor. (V2: tüm metinler dosyadan/ASS üzerinden, filtre dizgesine ham metin girmez.)
- Sağlayıcı hata gövdesi (≤1000 karakter) veritabanına ve API cevabına yazılıyor → olası bilgi sızıntısı.
- API anahtarı düz `.env`; kullanıcı başına anahtar yönetimi, şifreleme yok.
- Rate limit, audit log, girdi büyüklüğü sınırları (konu hariç), güvenlik başlıkları yok.
- Dockerfile root olarak çalışıyor; healthcheck yok; compose'ta PostgreSQL/Redis/nesne depolama yok.
- Kullanıcılar arası veri izolasyonu mümkün değil (tek kullanıcı varsayımı).
- `StaticFiles(directory="frontend")` göreli yol → servis başka çalışma dizininden başlatılırsa açılmaz.

## 4. Eksik özellikler (V2 kapsamına göre)

Kullanıcı hesabı/oturum · PostgreSQL · S3 uyumlu depolama · Redis+Celery kuyruğu · trend araştırma ·
fikir üretimi/puanlama/tekrar engelleme · storyboard · sağlayıcı soyutlaması ve yedekleme (fallback) ·
gerçek hareketli video (text/image-to-video) sağlayıcıları · stok medya · TTS sahne senkronu · müzik ·
Whisper/STT altyazı (SRT/ASS) · ses miksajı ve loudness normalizasyonu · geçişler, renk, intro/outro,
logo, kapak · 14 maddelik gerçek kalite kontrol · maliyet takibi/bütçe · OAuth + 3 platform yayınlama ·
performans takibi/öğrenme/A-B testi · bildirimler · Android uygulaması (V1 yalnızca PWA) ·
SSE/WebSocket · çok kullanıcı/izolasyon · yedekleme · kapsamlı test.

## 5. Teknik borç

- Ham SQL + şema göçü yok (Alembic yok) · `@app.on_event` (kullanımdan kalkmış) · tek dosyada karışık iş mantığı ·
  sürekli `subprocess.run` ile ham `ffprobe` çağrısı pipeline içinde · sahne süresi hesabı
  (`max(3, duration // n)`) hedef süreyi aşabilir (7 sahne × 3 sn = 21 sn, hedef 15 sn) ·
  `zoompan d=75` + `-loop 1` birleşimi, kare başına zoom'u sıfırlayabilir (İNCELEME, V2'de yeniden yazıldı) ·
  PWA manifest'te `icons: []` → Chrome "Yükle" ölçütlerini karşılamaz.

## 6. Korunan / taşınan davranışlar (geriye dönük uyumluluk)

- V1 API uçları `POST/GET /api/jobs`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/video`,
  `POST /api/jobs/{id}/publish`, `GET /api/health`, `GET /api/config` V2'de **uyumluluk katmanı**
  olarak sürer (aynı istek gövdesi; V2'de yalnızca kimlik doğrulama zorunlu hale gelmiştir).
- V1'in "yayınlanmadan yayınlandı deme" ilkesi korunmuş ve sıkılaştırılmıştır (platform doğrulaması olmadan `PUBLISHED` yok).
- V1'in API anahtarı yokken çalışan "demo" davranışı, **açıkça etiketli** çevrimdışı sağlayıcılar olarak korunur
  (şablon senaryo, FFmpeg ile üretilen yerel görsel/hareket, espeak-ng ses). Bu çıktılar "AI üretimi" diye sunulmaz;
  proje `media_report` alanında kökenleri yazılır ve otomatik yayın dışı bırakılır.
- Orijinal V1 kaynakları `legacy_v1/` içinde değişmeden durur.
