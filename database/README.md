# database/

Alembic göçleri: `database/migrations/versions/`. Yapılandırma kökte `alembic.ini` (URL `DATABASE_URL` ortamından).
```bash
alembic upgrade head                           # uygula
alembic revision --autogenerate -m "açıklama"  # model değişince yeni göç
alembic check                                  # model ↔ şema kayması var mı?
```
İlk göç (`0001`) gerçek PostgreSQL 16'ya karşı üretildi ve uygulandı; `alembic check` kayma bildirmedi. Geliştirme/test (SQLite) şemayı `create_all` ile kurar.
Şema: 24 tablo (kullanıcı/oturum, kanal, proje/sahne/varlık, görev/olay, yayın/metrik/deney, maliyet/istatistik, bildirim/audit…) — bkz. `backend/models/`.
