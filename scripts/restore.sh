#!/usr/bin/env bash
# Geri yükleme: scripts/restore.sh <db_*.dump> [storage_*.tar.gz]   (DATABASE_URL hedef veritabanı; MEVCUT VERİLERİN ÜZERİNE YAZAR)
set -euo pipefail
DUMP="${1:?db dump dosyası gerekli}"; : "${DATABASE_URL:?DATABASE_URL gerekli}"
URL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"
read -r -p "Hedef veritabanı silinip geri yüklenecek. Devam? (evet/hayır) " a; [ "$a" = "evet" ] || exit 1
pg_restore --clean --if-exists --no-owner --dbname "$URL" "$DUMP"
[ -n "${2:-}" ] && tar -C "$(dirname "${LOCAL_STORAGE_DIR:-./data/storage}")" -xzf "$2"
echo "Geri yükleme tamam"
