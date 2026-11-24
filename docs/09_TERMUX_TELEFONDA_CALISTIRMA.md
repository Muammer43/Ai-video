# 09 — Sunucuyu Telefonun Kendisinde Çalıştırma (Termux)

Bilgisayar/VPS yoksa: backend **telefonda Termux** içinde çalışır, Android uygulaması aynı telefondan `http://127.0.0.1:8000` adresine bağlanır.

> **Doğrulama durumu (dürüst not):** Python tarafı, Termux'ta bulunmayan paketler (PostgreSQL sürücüsü, Redis, Alembic, `uvicorn[standard]`) **olmadan** bir sanal ortamda test edildi (offline hat, API ve uçtan uca testler geçti). Termux'un kendisinde (pydantic-core/argon2 derlemesi, Termux'taki FFmpeg süzgeçleri, yazı tipi yolu) **denenmedi** — bu adımlar ilk kez sizin telefonunuzda çalışacak. Hata alırsanız çıktıyı (ekran görüntüsü) gönderin, birlikte düzeltelim.

## Sınırlar (bu kurulum türü)
- Termux/telefon kapanır veya Android uygulamayı öldürürse sunucu durur; **7/24 çalışma garantisi yok**. Gerçek 7/24 için bir VPS gerekir (`docs/03_KURULUM.md`).
- Redis/Celery yok: işler sunucu içinde iş parçacığı olarak çalışır; açılışta takılı kalmış işler otomatik toparlanır, otomasyon ve zamanlanmış yayın gömülü zamanlayıcıyla çalışır.
- Telefonda render yavaştır (30 sn'lik video için birkaç dakika) ve pil/ısı tüketir.
- **Sosyal medya hesap bağlama (OAuth) çalışmaz:** YouTube/TikTok/Instagram geri dönüş adresi internetten erişilebilir HTTPS olmalıdır (`127.0.0.1` olamaz). Önce video üretimini deneyin; yayın için sonra bir tünel/VPS gerekir.

## Adımlar
1. **Termux'u kurun** — Play Store sürümü eskidir, **kullanmayın**. F-Droid (f-droid.org) veya Termux'un GitHub "Releases" sayfasından kurun.
2. Termux'u açın, depolama izni verin:
   ```
   termux-setup-storage
   ```
3. İndirdiğiniz `AI_Video_Factory_Termux.zip` dosyasını açın (Downloads klasöründe):
   ```
   cd ~ && cp ~/storage/downloads/AI_Video_Factory_Termux.zip . && unzip -o AI_Video_Factory_Termux.zip && cd aivf_termux
   ```
4. Kurulum (10–40 dk; ekranı açık tutun, şarjda olsun):
   ```
   bash scripts/termux_setup.sh
   ```
   Sonunda `ffmpeg`, `libass`, `loudnorm`, `xfade` için `True` görmelisiniz.
5. Sunucuyu başlatın (Termux penceresi açık kalmalı veya arka plana alın):
   ```
   bash scripts/termux_run.sh
   ```
   `Uvicorn running on http://127.0.0.1:8000` yazısını görün.
6. **Android uygulamasını** açın → sunucu adresi `http://127.0.0.1:8000` → "Bağlantıyı sına" ✅ → "Yeni hesap oluştur".
7. Kalıcı çalışma için: Android Ayarlar → Uygulamalar → Termux → Pil → **Kısıtlama yok**; Termux bildirimindeki "Wake lock"u açık tutun.

## Ücretsiz/ucuz daha iyi sonuç
1. **Stok video:** AI Modelleri → "Stok video ve diğer anahtarlar" → **Pixabay** anahtarı (ücretsiz kayıt). Studio'da **Hibrit** modu seçin → sahneler gerçek video görüntüleriyle dolar. (Pexels şu an yeni anahtar vermiyor.)
2. **Gerçek senaryo:** AI Modelleri → LLM bölümünde **Özel LLM (OpenAI uyumlu)** → Gemini/Groq/OpenRouter seçin, model adını sağlayıcıdan kopyalayın, anahtarı girin. Ücretsiz katmanlarda içerik sağlayıcıda ürün geliştirmede kullanılabilir (Gemini). Ses yine robotik kalır; videolar bu yüzden "inceleme gerekli" olur — doğal ses için ücretli OpenAI/ElevenLabs anahtarı gerekir.

## AI anahtarları
Uygulama → **AI Modelleri** → sağlayıcıya **Anahtar ekle**. Tek `OpenAI` anahtarı metin + görsel + seslendirme + altyazı zamanlamasını kapsar (ücretlidir; varsayılan video başı bütçe $2, günlük $5 — Ayarlar'dan değiştirin). Gerçek hareketli AI video için `fal.ai` veya `Runway` anahtarı ekleyin; yoksa sahneler "AI görsel + hareket" olarak etiketlenir (AI video değildir).
Anahtarsız üretim yalnızca hattı sınar (şablon metin, robotik ses): bu videolar **otomatik yayına alınmaz**.

## Sunucuyu yeniden başlatma / güncelleme
`bash scripts/termux_run.sh` (veriler `~/aivf_data` içinde kalır). Durdurmak: Termux'ta `Ctrl+C`.
