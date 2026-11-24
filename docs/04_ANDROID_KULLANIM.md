# 04 — Android Uygulaması Kullanım Kılavuzu

## APK
- Derlenmiş dosya: `dist/AI_Video_Factory_Pro.apk` (release, ~60 MB, **debug anahtarıyla imzalı**; Play Store için kendi keystore'unuzla imzalayın).
- Kurulum: APK'yı telefona aktarın → "bilinmeyen kaynaklardan yükleme"ye izin verin → açın. Android 7.0+ (minSdk 24).
- Kendiniz derlemek için: `cd android_app && flutter pub get && flutter build apk --release` (Flutter 3.50, Android SDK 37, Java 17+).
  Maven Central hız sınırı (429) hatası alırsanız komutu tekrarlayın; Gradle önbelleği ilerlemeyi korur.

## İlk açılış
1. **Sunucu adresi:** `https://video.alanadiniz.com` (üretim) — yerel testte `http://192.168.x.x:8000`. `http://` adreslerde uygulama "şifresiz bağlantı" uyarısı gösterir. Android emülatöründe bilgisayara `http://10.0.2.2:8000`.
2. "Bağlantıyı sına" → ✅ görünce e-posta/parola ile **hesap oluşturun** (ilk hesap yönetici olur) veya giriş yapın.
3. Oturum anahtarları cihazın güvenli deposunda (Android Keystore) saklanır; erişim anahtarı süresi dolunca otomatik yenilenir.

## Ekranlar (menü ☰ → 10 sayfa; alt çubukta ilk 4)
| Ekran | Ne yapar |
|---|---|
| **Dashboard** | Toplam/bugünkü video, kuyruk, tamamlanan, başarısız, yayına hazır, **doğrulanmış** yayın sayısı, izlenme/etkileşim (veri yoksa "—"), günlük maliyet, bütçe çubukları, AI servis durumu, sistem sağlığı, 14 günlük grafik |
| **AI Video Studio** | Konu, kategori (14 + özel), süre, stil, dil, ses (cinsiyet/duygu/hız), format (9:16/16:9/1:1), çözünürlük, kalite, medya modu, platformlar, yayın modu, görünürlük → **Maliyet tahmini** → **Üretimi başlat** (canlı ilerleme ekranı) |
| **Otomatik Üretim** | Otomasyonu duraklat/devam, kanal başına "Şimdi üret", fikir üretimi (gerçek trend + LLM), fikri üretime çevir, trend listesi, arka plan görevleri |
| **Projeler** | Filtre/arama, her proje: canlı pipeline, **video önizleme**, **MP4 indir/paylaş**, iptal, yeniden dene, sıfırdan üret, onayla/reddet, senaryo, kalite raporu (14+ kontrol), medya kökeni, yayın durumları, maliyet |
| **İçerik Kanalları** | Niş/kanal oluştur-düzenle: dil, stil, ses, platformlar, günlük video sayısı, yayın saatleri, otomatik yayın, intro/outro metni |
| **Yayın Takvimi** | Planlı/yayınlanan/işlem bekleyen yayınlar; yeniden zamanla, tekrar dene, iptal |
| **Analiz Merkezi** | Ölçülmüş performans, öğrenme içgörüleri (güven etiketli; yetersiz veride iddia yok), A/B testleri |
| **AI Modelleri** | Sağlayıcı durumu (yapılandırıldı mı, AI mı, başarı oranı, gecikme, ort. maliyet, son hata), anahtar ekle/sına/sil, öncelik sırası |
| **Entegrasyonlar** | YouTube/TikTok/Instagram hesap bağlama (OAuth tarayıcıda), gereksinimler, hesap durumu |
| **Ayarlar** | Hesap/parola, sunucu bilgisi, bütçe ve harcama (limit, duraklatma, devam), kalite eşikleri, bildirimler, müzik kütüphanesi |

## İş akışı
`Studio → Başlat` → sunucu işi kuyruğa alır. **Uygulamayı kapatabilirsiniz**; render/yayın bulutta sürer.
Kalite kontrolü geçen videolar otomatik yayın kuyruğuna girer; **eşiği geçemeyen/riskli** olanlar **"İnceleme gerekli"** olur → Projeler'den açıp videoyu izleyin, kalite raporunu okuyun, **Onayla ve yayınla** veya **Reddet**.
Kritik güvenlik/telif bulgusu varsa onay için ayrıca açık bir "yine de yayınla" kutusu işaretlenmelidir.

## Bildirimler
- Uygulama açıkken/arka plandayken: üretim bitti/başarısız/inceleme/bütçe/yayın olayları yerel bildirim olarak gösterilir (SSE + 45 sn yoklama).
- **Uygulama tamamen kapalıyken bildirim (FCM) bu APK'da yoktur.** Sunucu tarafı hazırdır (`POST /api/v1/devices`, FCM HTTP v1 gönderimi, `FCM_SERVICE_ACCOUNT_JSON`); istemci tarafı için Firebase projesi + `google-services.json` + `firebase_messaging` eklenmelidir. Bu eklenmediği için bildirim kaçırılmaz: bildirim merkezi (🔔) tüm olayları saklar.

## Bilinen sınırlar
- Logo/filigran yüklemesi yalnızca API'den (`POST /api/v1/channels/{id}/logo`); müzik yükleme de API'den (`POST /api/v1/music`).
- APK gerçek bir cihaz/emülatörde **çalıştırılarak test edilmedi** (geliştirme ortamında emülatör yok); `flutter analyze`, 16 birim/widget testi, release derlemesi ve canlı backend'e karşı ağ katmanı testi yapıldı.
