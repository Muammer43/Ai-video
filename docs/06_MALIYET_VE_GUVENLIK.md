# 06 — Maliyet Yönetimi ve Güvenlik

## Maliyet yönetimi
**Üretim öncesi tahmin:** `POST /api/v1/projects/estimate` (uygulamada "Maliyet tahmini"). Yönlendiricinin seçeceği sağlayıcılar için kalem kalem:
LLM (token), görsel, video (saniye), TTS (karakter), STT (dakika), sunucu (render dakikası, **yapılandırılmış tahmin — ölçüm değil**), depolama (GB-ay tahmini). %15 pay eklenir.

**Takip:** her sağlayıcı çağrısı `cost_ledger`'a yazılır: `estimated=false` yalnızca sağlayıcı gerçek maliyeti bildirdiyse (Runway `cost.credits`), aksi halde fiyat tablosundan hesaplanır ve `estimated=true` işaretlenir. Ayrıca sağlayıcı istatistikleri: çağrı, başarı oranı, ortalama gecikme/maliyet, rate-limit sayısı, son hata, son çıktı çözünürlüğü/süresi.

**Sınırlar (kullanıcı başına, uygulamadan ayarlanır):**
| Sınır | Davranış |
|---|---|
| Günlük / aylık bütçe | Aşılacaksa **yeni üretim reddedilir**, kullanıcı `budget` bildirimi alır, otomasyon durur (`paused`) — limit artırılıp "devam et" denene kadar |
| Video başına | Oluşturma anında tahmin sınırı aşıyorsa `402 per_video_budget`; üretim sırasında her ücretli çağrı kalan video bütçesine göre sınırlanır |
| Uyarı eşiği | Varsayılan %80'de günde bir `budget_alert` bildirimi |
| Pahalı yedeğe geçiş engeli | Açıkken yedek sağlayıcı daha **pahalı kademedeyse** (ör. OpenAI → Runway) otomatik kullanılmaz |

Fiyat tablosu: `backend/providers/pricing.py` — her kayıt kaynak+tarih taşır. **Doğrulanmış (2026-11-24, resmî sayfalar):** Runway kredi fiyatları (0.01 USD/kredi), fal.ai Kling v3 Pro t2v $0.14/sn, Veo 3.1 Fast $0.15/sn, Wan 3.0 i2v $0.05/sn, Flux schnell/dev, ElevenLabs $0.08/1K karakter (Multilingual v2). **Doğrulanamayan** (OpenAI token/görsel/TTS/STT, Anthropic): varsayılan tahmin, `price_verified=false`; güncel fiyatları `PRICING_OVERRIDES_JSON` ile girin.

## Güvenlik
| Alan | Uygulama | Test |
|---|---|---|
| Kimlik doğrulama | Argon2id parola, JWT (HS256, 30 dk), tek kullanımlık rotasyonlu refresh, yeniden kullanım tespitinde tüm oturumlar kapanır, parola değişimi tüm oturumları iptal eder | `test_api`, `test_security` |
| Oturum yönetimi | `auth_sessions` tablosu (IP/UA, iptal), `token_version` | ✔ |
| Gizli bilgiler | Sağlayıcı anahtarları + OAuth token'ları **Fernet** ile şifreli (`ENCRYPTION_KEY`); API hiçbir zaman geri döndürmez (yalnızca maskeli ipucu); loglarda/hata gövdelerinde/audit'te redakte | `test_secrets_never_logged_or_returned`, `test_provider_errors_are_redacted` |
| Kaynak kodda sır yok | `.env` git'te yok (`.gitignore`), `.env.example` boş; `ENV=prod` iken varsayılan `SECRET_KEY` ve boş `ENCRYPTION_KEY` ile **başlamaz** | `test_production_refuses_insecure_defaults` |
| OAuth | PKCE + imzalı/süreli `state`, yönlendirme adresi sabit, token yenileme, başarısızlıkta `needs_reauth` + bildirim | `test_oauth_*` |
| Rate limiting | IP başına dakikada 240; giriş IP+e-posta başına 10/dk; Redis varsa paylaşımlı, yoksa bellek | `test_login_rate_limit` |
| Girdi doğrulama | Pydantic sınırları/enum'lar (süre, platform, stil…), boyut sınırı (30 MB), SQL için yalnızca parametreli ORM | `test_sql_injection_in_filters_is_inert` |
| Yetki / izolasyon | Her sorgu `user_id` ile; başka kullanıcının kaydı **404** | `test_user_isolation`, `test_media_token_scoped_to_owner_and_key` |
| Dosya erişimi | Dosyalar yalnızca (a) Bearer'lı sahip indirmesi veya (b) kısa ömürlü, kullanıcıya + dosyaya bağlı imzalı token ile; depolama anahtarı yol geçişine karşı doğrulanır | ✔ |
| Güvenli yükleme | Logo/müzik: içerik imzası (magic bytes) + ffprobe doğrulaması + boyut/süre sınırı; müzik için **lisans beyanı zorunlu** | `test_logo_upload_*`, `test_music_upload_*` |
| FFmpeg enjeksiyonu | Kullanıcı/LLM metni **asla** filtre dizgesine girmez; ASS dosyası + `ass_escape` (V1'deki `drawtext` sınıfı açık kapatıldı) | `test_ffmpeg_filter_injection_*` |
| HTTPS | Caddy otomatik TLS; uygulama HSTS gönderir (`PUBLIC_BASE_URL` https ise); Android `http://` için uyarır | — |
| Başlıklar / CORS | CSP, X-Frame-Options, nosniff, Referrer-Policy; CORS varsayılan **kapalı** (V1'deki `*` kaldırıldı) | `test_cors_closed…` |
| Audit log | Giriş/çıkış/başarısız giriş, proje işlemleri, kimlik bilgisi değişimi, bütçe/kalite ayarı, OAuth bağlama… (`audit_logs`) | ✔ |
| Yedekleme | `scripts/backup.sh` / `restore.sh` (PostgreSQL + depolama + SHA256) | gerçek PG ile doğrulandı |
| Konteyner | root olmayan kullanıcı, healthcheck | (imaj derlenmedi) |

**Kapsam dışı / kullanıcı sorumluluğu:** sunucu sertleştirme (güvenlik duvarı, SSH), Redis/PostgreSQL/MinIO'nun dışarıya kapalı tutulması (compose'ta yalnızca Caddy portları yayınlar), yedeklerin şifrelenmesi, `ENCRYPTION_KEY`'in güvenli saklanması (kaybedilirse kayıtlı anahtar/token'lar çözülemez — yeniden girilir).
Android: `usesCleartextTraffic=true` yalnızca yerel ağ testi içindir; üretimde HTTPS kullanın.
