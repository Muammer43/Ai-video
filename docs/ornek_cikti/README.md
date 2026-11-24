# Örnek çıktı (gerçek üretim)

`ornek_uretim_cevrimdisi.mp4` — `scripts/clean_install_test.sh` içinde, **API anahtarı olmadan** (çevrimdışı/etiketli sağlayıcılar) gerçek PostgreSQL + Redis + Celery worker ile üretildi.
**Bu video AI içerik değildir:** senaryo şablondur, ses espeak-ng robotik sentezidir, görseller FFmpeg gradyanıdır. Amaç, hattın (ses → altyazı zamanlama → kurgu → ses miksajı/loudnorm → kapak → 14+ kontrollü QC) gerçekten çalıştığını göstermektir.
`ornek_kalite_raporu.json` — QC raporu: teknik kontroller geçti (puan yüksek) fakat sistem videoyu **`review`** olarak işaretledi (`template_script`, `offline_voice`, `placeholder_visuals`, `safety_llm_unavailable` risk bayrakları) → **otomatik yayına alınmaz**.
`ornek_ffprobe.txt` — ffprobe doğrulaması (h264 + aac, 720×1280, 30 fps).
