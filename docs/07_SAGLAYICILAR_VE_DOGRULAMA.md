# 07 — Sağlayıcılar: Doğrulanan API Bilgileri ve Sınırlar

Resmî dokümanlar **2026-11-24** tarihinde okundu (paralel okuma ajanlarıyla). "Bulunamadı" = okunan sayfalarda yok; tahmin edilmedi, kod buna göre yorumlandı.

## Doğrulama sonucunda koda yansıyan düzeltmeler
| Bulgu | Etki |
|---|---|
| OpenAI `gpt-image-1` **2026-10-23'te kapatılmış** | Varsayılan görsel modeli `gpt-image-2`; model adı `OPENAI_IMAGE_MODEL` ile ayarlanır |
| OpenAI Sora/Videos API **2026-09-24'te kapatılmış** | Sora adaptörü **yazılmadı** |
| OpenAI `tts-1`/`gpt-4o-mini-tts` **2027-01-06'da kapanacak** | `OPENAI_TTS_MODEL` yapılandırılabilir |
| Anthropic yeni API sürümünde `temperature/top_p/top_k` göndermek **400** | Anthropic adaptörü bunları göndermez (`anthropic-version: 2023-06-01`) |
| Pexels `/videos/` yolu kullanımdan kalkıyor | `/v1/videos/search` kullanılır |
| Pixabay'de **müzik API'si yok**; Freesound API ticari kullanım için sözleşme ister; Jamendo ticari yolu lisans satın alma | **Otomatik müzik indirme uygulanmadı**; yerine (a) lisans alanları zorunlu kullanıcı kütüphanesi, (b) FFmpeg ile sentezlenen telifsiz müzik |
| Pixabay: sonuçlar 24 sa önbelleğe alınmalı, toplu indirme yasak | Adaptör tek sahne başına tek sorgu yapar |
| YouTube dokümanı "denetimsiz projelerde yüklemeler özel olmaya zorlanır" iddiasını **doğrulamadı** (aksine yazıyor) | Sistem varsayım yapmaz: yüklemeden sonra `videos.list` ile **gerçek gizlilik** okunur; istenenden farklıysa `NEEDS_ACTION` |
| TikTok: denetimsiz istemci yalnızca `SELF_ONLY`; refresh token döndürüldükçe **rotasyon** | `creator_info` ile izinli gizlilik seviyeleri okunur, uygunsuzsa **yüklenmeden** `NEEDS_ACTION`; yenilenen refresh token saklanır |
| Instagram: Graph v27.0; 24 saatte 100 (karuselde 50) yayın çelişkisi; `plays` yok, `views` var; `is_ai_generated` parametresi var | `GRAPH_API_VERSION=v27.0`; metrik `views`; AI içerik beyanı gönderilir |
| YouTube `containsSyntheticMedia`, TikTok `is_aigc`, Instagram `is_ai_generated` alanları var | Üretilen içerik için **sentetik medya beyanı** gönderilir |

## Sağlayıcı matrisi
| Tür | Adaptör | Doğrulama durumu |
|---|---|---|
| LLM | OpenAI chat (`response_format: json_object`), Anthropic messages | İstek/yanıt biçimi dokümana göre; **canlı çağrı yapılmadı** (anahtar yok) — mock testli |
| Görsel | OpenAI Images (`b64_json`), fal.ai Flux (`images[].url`) | mock testli |
| Video | fal.ai kuyruk (Kling şeması **doğrulandı**: `prompt, start_image_url, duration, generate_audio`; başka model ailesi için şema doğrulanmadı), Runway (`/v1/image_to_video`, `/v1/text_to_video`, `X-Runway-Version`, kredi maliyeti), Replicate (genel; model girdi adları `prompt/image/duration/aspect_ratio` olmalı), Pexels/Pixabay stok | mock testli; **canlı doğrulanmadı** |
| TTS | OpenAI speech, ElevenLabs (varsayılan ses kimlikleri değiştirilebilir), espeak-ng (yerel, robotik) | OpenAI/ElevenLabs mock; espeak **gerçek** |
| STT | OpenAI transcriptions (`verbose_json` + `timestamp_granularities[]=word`), yerel tahmini hizalayıcı | OpenAI mock; hizalayıcı gerçek ama **ASR değil** (etiketli) |
| Yayın | YouTube resumable upload + `videos.list`; TikTok Direct Post FILE_UPLOAD + status fetch; Instagram REELS konteyner + `media_publish` | mock HTTP testli; **canlı hesapla test edilmedi** |
| Trend | YouTube mostPopular (kullanıcı API anahtarı), Hacker News, Wikimedia Pageviews | HN/Wikimedia anahtarsızdır; bu ortamda canlı sınanmadı |

## Dokümanda doğrulanamayan, bilgiye dayalı kısımlar (canlıda ilk denemede kontrol edin)
- YouTube OAuth yetkilendirme URL'si, Analytics metrik adları (`averageViewDuration`, `averageViewPercentage`, `shares`, `subscribersGained`), `uploadStatus` enum değerleri (iki biçim de kabul edilir: `processed` / `STATUS_PROCESSED`).
- TikTok yetkilendirme URL'si (`/v2/auth/authorize/`), status değerleri (`PUBLISH_COMPLETE`, `FAILED`), `publicaly_available_post_id` alan adı. **Resmî Display API izlenme süresi/tamamlanma oranı vermez** → TikTok için bu metrikler `null` kalır (uydurulmaz); öğrenme motoru etkileşim oranına düşer.
- Instagram kısa→uzun ömürlü token değişimi uçları, Reels teknik sınırları (süre/boyut), `ig_reels_avg_watch_time` birimi (ms varsayıldı).
- fal.ai kuyruk durum/sonuç URL'leri gönderim yanıtındaki `status_url/response_url`'den alınır (yol varsayımı yok).

## Uygulanmayan / kısmi maddeler (bilerek)
| Madde | Durum |
|---|---|
| Video-to-video ("uygunsa") | Adaptör **yok**: doğrulanmış, kararlı bir resmî API şeması bulunmadı. Sağlayıcı arayüzü (`VideoRequest`) genişletmeye açık |
| Yerel `faster-whisper` | Yok; OpenAI Whisper (anahtar gerekir) veya etiketli tahmini hizalayıcı |
| Otomatik ticari müzik indirme | Yok (bkz. yukarı: lisans/API engeli). Lisanslı kullanıcı kütüphanesi + FFmpeg sentezi |
| Karakter tutarlılığı | Stil kılavuzu (`style_bible`) + proje başına sabit `seed` + keyframe→image-to-video akışı; sağlayıcıların `seed` desteğine bağlıdır, **garanti değildir** |
| Tarayıcı otomasyonu / resmî olmayan yayın | Bilerek **yok** |
| Android'de kapalı-uygulama push (FCM istemcisi) | Sunucu hazır; istemci Firebase kurulumu gerektirir (docs/04) |
| Web konsolu | Dashboard + üretim + projeler (onay/iptal/yeniden dene); 10 ekranın tamamı yalnızca Android uygulamasında |

## Ücretsiz / düşük maliyetli yol (2026-11-24 doğrulaması)
Genel "OpenAI uyumlu" LLM sağlayıcısı (`compat`) eklendi: kullanıcı adres + model + anahtar girer (uygulama → AI Modelleri → Özel LLM). Adres yalnızca `https` ve genel (iç ağ/loopback/link-local olmayan) olabilir (SSRF önlemi). Sağlayıcı `json_object` kipini reddederse istek ek yönergeyle otomatik yeniden denenir. Fiyat bilinmediğinden varsayılan 0 USD kaydedilir ve `price_verified=false` etiketlenir (isteğe bağlı `in_per_m/out_per_m`).
| Servis | Doğrulanan | Dikkat |
|---|---|---|
| Google Gemini (OpenAI uyumlu uç: `https://generativelanguage.googleapis.com/v1beta/openai/`) | `chat/completions` destekli; bazı modeller ücretsiz katmanda | **Ücretsiz katmanda içerik Google ürünlerini geliştirmek için kullanılabilir.** `json_object` kipi dokümanda yok (yedek yol çalışır). Türkiye'de kullanılabilirlik doğrulanamadı. Limitler AI Studio'da |
| Groq (`https://api.groq.com/openai/v1`) | OpenAI uyumlu; ücretsiz plan var | Ücretsiz plan limitleri dokümanda net değil (console.groq.com/settings/limits) |
| OpenRouter (`https://openrouter.ai/api/v1`) | `:free` ekli modeller; ücretsiz hesapta günde 50 istek | Doğrulanmış, Türkçe/JSON'da iyi bir ücretsiz model adı bulunamadı |
| **Pexels** stok video | Anahtar ücretsiz tanımlanıyor | **Şu an yeni anahtar verilmesi duraklatılmış** ("issuance paused"); zaten anahtarı olanlar kullanabilir. Atıf zorunlu |
| Pixabay stok video | Anahtar ücretsiz; ücretsiz kayıt | Bu oturumda kayıt akışı doğrulanmadı; atıf istenir, toplu indirme yasak |
Model adları sağlayıcılar tarafından sık değişir: koda gömülmedi; kullanıcı sağlayıcının güncel listesinden girer.

## Gemini ile tamamen ücretsiz yığın (2026-11-24 doğrulaması)
Tek bir Google AI Studio anahtarı (`gemini` kimlik bilgisi) hem metin (OpenAI uyumlu uç, model `GEMINI_TEXT_MODEL`, bulunamazsa `models.list` ile otomatik keşif) hem **TTS** için kullanılır.
| Bulgu (resmî doküman) | Koda yansıma |
|---|---|
| TTS, "Interactions API": `POST /v1beta/interactions`, `x-goog-api-key`; gövde `input[].content[].text` (+`annotations[].speech_metadata.style`), `response_format.type=audio`, `generation_config.speech_config[].voice`; yanıtta base64 ses `steps[].content[].data`; tek seferlik yanıt WAV 24 kHz mono 16-bit | `providers/tts/gemini_tts.py` (başsız PCM de işlenir) |
| TTS modelleri `gemini-3.8-flash-tts`, `gemini-3.8-flash-lite-tts`: **ücretsiz katmanda "free of charge"**, Türkçe destekli (dil otomatik) | `GEMINI_TTS_MODEL` / `GEMINI_TTS_FALLBACK_MODEL` ile ayarlanır |
| Ses cinsiyeti dokümanda yok | Kore/Aoede/Leda (kadın), Puck/Charon/Orus (erkek) **varsayım**; `voice.gemini_voice` ile değiştirilebilir |
| Ücretsiz katmanda limitler (RPM/RPD) ve **ticari kullanım koşulları belirtilmemiş**; içerik Google ürünlerini geliştirmek için kullanılabilir | Uygulamada uyarı; kendi sorumluluğunuzda kontrol edin |
| **Görsel üretim (Nano Banana) ücretsiz katmanda yok** | Gemini görsel adaptörü yazılmadı |
| Google Cloud TTS ücretsiz kotası ve kart şartı alınamadı; Azure F0: 0.5M karakter/ay (kart/ticari koşullar belirtilmemiş); Cloudflare Workers AI'da Türkçe TTS yok | Adaptör yazılmadı (doğrulanmadı) |
**Canlı Gemini çağrısı bu ortamda yapılmadı (mock testli).** Model adları dokümandan alındı; sağlayıcılar adları değiştirirse `.env`'den güncelleyin.
