# 08 — Test Raporu ve Bilinen Sınırlar

Tarih: 2026-11-24 · Ortam: Linux, Python 3.13, FFmpeg 6.1, PostgreSQL 16.15, Redis 7.0, Flutter 3.50.1 / Dart 3.14, Android SDK 37.
Etiketler: **GERÇEK** = gerçek bileşen (FFmpeg, PostgreSQL, Redis, Celery, tarayıcı); **MOCK** = HTTP/servis sahte; **DOĞRULANMADI** = test edilemedi.

## Özet
| Paket | Sonuç | Tür |
|---|---|---|
| Backend `pytest` — SQLite | **56/56 geçti** (208 sn) | karma (aşağıya bakın) |
| Backend `pytest` — **PostgreSQL 16** (`TEST_DATABASE_URL`) | **56/56 geçti** (253 sn) | karma |
| Gerçek Redis + gerçek Celery worker (`tests/integration/celery_e2e.py`) | geçti | GERÇEK |
| Temiz ortam kurulumu (`scripts/clean_install_test.sh`: sıfır venv, yalnızca `requirements.txt`, `ENV=prod`, PG+Redis+API+worker+beat) | geçti | GERÇEK |
| Yedekleme/geri yükleme (PostgreSQL `pg_dump`/`pg_restore`, SHA256) | geçti; satır sayıları birebir | GERÇEK |
| Flutter `analyze` / `test` | 0 hata, 2 bilgi düzeyi uyarı / **17/17 geçti** | GERÇEK (widget testleri) |
| Android istemci ağ katmanı → canlı backend (`dart run tool/connect_check.dart`) | **10/10 geçti** | GERÇEK |
| Web konsolu, tarayıcı E2E (Playwright/Chromium, 390×844) | **8/8 geçti**, konsol/CSP hatası yok | GERÇEK |
| Release APK derleme | başarılı (61.6 MB) | GERÇEK |
| Gerçek cihaz/emülatörde APK çalıştırma | **DOĞRULANMADI** (bu ortamda yok) — bkz. aşağıdaki "kaçırılan hata" | — |
| Docker imaj derleme / compose çalıştırma | **DOĞRULANMADI** (daemon yok); `docker compose config` sözdizimi geçti | — |
| Canlı AI / YouTube / TikTok / Instagram API'leri | **DOĞRULANMADI** (anahtar/hesap yok) | — |

## Backend testleri (56) — dosya bazında
| Dosya | # | Ne sınar | Tür |
|---|---|---|---|
| `test_pipeline_offline.py` | 3 | Anahtarsız uçtan uca üretim: **gerçek MP4** (ffprobe: h264+aac, 720×1280), 14+ QC kontrolü, risk bayrakları (şablon/robotik ses/yer tutucu → otomatik yayın YOK), geçici dosya temizliği, çift çalışma engeli (CAS), trend filtresi | GERÇEK FFmpeg/espeak (trend filtresi MOCK) |
| `test_pipeline_ai_mock.py` | 3 | AI yolu: hibrit mod (AI video + stok), sağlayıcı çökünce **dürüst yedekleme** ve `NEEDS_REVIEW`, bütçe aşımı üretimi durdurur, maliyet defteri = proje maliyeti, sağlayıcı istatistikleri | **MOCK HTTP**; medya GERÇEK FFmpeg |
| `test_publishing_mock.py` | 8 | YouTube/TikTok/Instagram: `PUBLISHED` yalnızca platform doğrulamasından sonra; gizlilik düşürme → `NEEDS_ACTION`; token yenileme; geçici hata → yeniden deneme; TikTok denetimsiz kısıtı; Instagram HTTPS şartı; bağlı hesap yoksa "yayınlandı" denmez | **MOCK HTTP** |
| `test_analytics.py` | 6 | Yetersiz veride iddia yok, gerçek farkı yakalama, aynı gruplarda yanlış pozitif kontrolü, permütasyon/bootstrap, hook sınıflandırma, deney şartları | **SENTETİK veri** (fonksiyon doğruluğu; gerçek performans değil) |
| `test_api.py` | 14 | Kimlik doğrulama, refresh rotasyonu + yeniden kullanım tespiti, rate limit, kullanıcı izolasyonu, Idempotency-Key, iptal/yeniden dene, bütçe, sağlayıcı/entegrasyon/anahtar, OAuth state, müzik yükleme, kanal+otomasyon tick, V1 uyumluluk | GERÇEK (FastAPI+DB) |
| `test_e2e_api.py` | 3 | API üzerinden gerçek üretim: SSE ilerleme, medya **HTTP Range**, onay (hesap yok → yayınlanmadı), çalışan işi iptal, hatadan sonra kaldığı yerden devam (ses yeniden üretilmedi) | GERÇEK |
| `test_security.py` | 13 | JWT kurcalama/alg=none, SQL enjeksiyonu, yol geçişi, medya token kapsamı, **FFmpeg/ASS enjeksiyonu**, sır sızıntısı (log/audit/yanıt/hata gövdesi), yükleme doğrulama, CORS/CSP, prod varsayılanları, şifreleme/yanlış anahtar, OAuth state, parola değişimi | GERÇEK |
| `test_recovery_units.py` | 4 | Reaper (yeniden kuyruğa / `STUCK`), taze iş dokunulmaz, yeniden deneme sınırı, proje zaman aşımı | GERÇEK |
| `test_storage_s3.py` | 1 | S3 depolama: yükle/indir/presign/sil/yol doğrulama | **moto (simüle S3)** — gerçek AWS/MinIO değil |
| `test_celery_integration.py` | 1 | Gerçek Redis + Celery: aynı iş iki kez gönderildi → **tek çalışma**; worker `SIGKILL` → reaper → yeni worker tamamladı (`attempts=2`) | GERÇEK |

## İstenen kalemlerin karşılığı
| İstek | Karşılık |
|---|---|
| Unit / Integration / API / Database test | yukarıdaki paketler; veritabanı testleri SQLite **ve** PostgreSQL'de |
| Worker test | `celery_e2e` (gerçek), `test_recovery_units` |
| **Video render test: en az bir gerçek MP4 + ffprobe** | `test_pipeline_offline`, `docs/ornek_cikti/` (ffprobe çıktısıyla), temiz kurulum duman testi (886 KB MP4) |
| AI provider mock test | `test_pipeline_ai_mock` (**mock olarak etiketli**) |
| Failure recovery | `test_recovery_units`, `celery_e2e` çökme senaryosu, yayın yeniden deneme, sağlayıcı yedekleme |
| Security test | `test_security`, `test_api` |
| Android bağlantı testi | `tool/connect_check.dart` (canlı backend, 10 adım) |
| Backend'i temiz ortamda kurup çalıştır | `scripts/clean_install_test.sh` |

## Testlerin bulduğu ve düzeltilen gerçek hatalar
1. **V1: varsayılan yapılandırmada render çöküyor** (göreli `concat.txt` yolları) — V2 yeniden yazıldı.
2. `pipeline`: senaryo `data` olarak geçirildiği için kaydedilmiyordu (offline test yakaladı).
3. Mock medya üretecinde geçersiz FFmpeg seçeneği (test altyapısı; sağlayıcı yedeklemesinin çalıştığını da gösterdi).
4. Giriş ekranı başlık satırı dar telefon genişliğinde taşıyordu (widget testi yakaladı).
5. Wikipedia "Anasayfa" trend olarak geliyordu (canlı sorgu yakaladı).
6. Dart istemci testi: ASCII olmayan karakterli sahte token HTTP başlığına yazılamıyordu (test verisi).

## ⚠ Testlerin kaçırdığı hata (kullanıcının cihazında ortaya çıktı)
Release APK'nın ilk sürümünde giriş formu yerine **gri hata kutusu** göründü. Neden: uygulama `tr` yerel ayarına zorlanmış ama Türkçe `MaterialLocalizations` temsilcileri eklenmemişti; widget testlerim varsayılan `en` ile koştuğu için hatayı görmedi.
**Düzeltme:** `material_ui` `GlobalMaterialLocalizations.delegates` eklendi; hata önce testte yeniden üretildi, düzeltme sonrası geçti; gerçek `App` kökünü `tr` yerel ayarında çizen regresyon testi eklendi. Ders: gerçek cihaz testi yerine geçmez — APK'nın telefonda ilk kez kullanıcı tarafından denendiği unutulmamalı; kalan ekranlarda (Dashboard, Studio vb.) cihaza özgü başka sorunlar çıkabilir.

## Bilinen sınırlar (özet)
- Canlı sağlayıcı/platform entegrasyonları test edilmedi; adaptörler resmî dokümana göre yazıldı, mock'la sınandı (docs/07: doğrulanamayan alanlar listelidir). Gerçek hesapla ilk denemede küçük uyarlamalar gerekebilir.
- Çevrimdışı sağlayıcılar (şablon, gradyan, espeak) yalnızca hattı sınamak içindir; çıktıları otomatik yayınlanmaz.
- AI güvenlik/telif denetimi **sezgisel + LLM** tabanlıdır; platform politikalarına/telif uygunluğuna **garanti vermez**. Wikipedia trendleri gerçek kişiler içerebilir — insan incelemesi önerilir.
- APK: debug anahtarıyla imzalı; kapalı-uygulama push (FCM istemcisi) yok; logo/müzik yükleme yalnızca API'den; cihazda çalıştırılarak test edilmedi (yukarıdaki hata bunun sonucu).
- Docker imajları derlenmedi; Alembic göçü yalnızca PostgreSQL 16'da denendi.
- SSE tek süreçte DB yoklamasıyla çalışır (1 sn); çok yüksek kullanıcı sayısında Redis pub/sub'a geçilmelidir.
- Render CPU yoğundur; worker başına eşzamanlılık 2 varsayılandır.
