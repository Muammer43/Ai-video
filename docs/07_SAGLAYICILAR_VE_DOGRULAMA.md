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
