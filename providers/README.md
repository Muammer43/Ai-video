# providers/

Sağlayıcı adaptörleri **`backend/providers/`** altındadır.

```
base.py        Provider, ProviderError(kind), istek/sonuç tipleri
router.py      tercih sırası, yedekleme, maliyet koruması, istatistik+maliyet defteri
pricing.py     fiyat tablosu (kaynak+tarih etiketli, override edilebilir)
http.py        ortak HTTP istemcisi, hata eşleme, polling (testler transport'u değiştirir)
llm/ image/ video/ tts/ stt/    türe göre adaptörler
publishing/    youtube.py tiktok.py instagram.py (OAuth + yükleme + platform doğrulaması)
```
Yeni sağlayıcı eklemek: `Provider` alt sınıfı yaz (`name, kind, cred_name, is_configured, estimate, execute`) ve `register(...)` çağır; paketin `__init__.py`'sine içe aktar. Hata türleri: `transient`/`rate_limit` (yeniden dene → sonraki sağlayıcı), `auth`/`permanent` (sonrakine geç), `needs_action` (yayın: kullanıcı işlemi).
Doğrulanan API bilgileri ve sınırlar: `docs/07_SAGLAYICILAR_VE_DOGRULAMA.md`.
