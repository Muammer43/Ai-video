#!/usr/bin/env bash
# Yedekleme: PostgreSQL dökümü + nesne depolama kopyası. Kullanım: scripts/backup.sh [hedef_dizin]
#   DATABASE_URL (postgresql://...) zorunlu. Yerel depolama: LOCAL_STORAGE_DIR; S3/MinIO: `mc` ile aynalayın (aşağıya bakın).
# Cron örneği (her gece 03:15, 14 gün sakla):  15 3 * * * cd /opt/aivf && scripts/backup.sh /var/backups/aivf
set -euo pipefail
DEST="${1:-./backups}"; STAMP="$(date -u +%Y%m%dT%H%M%SZ)"; KEEP_DAYS="${KEEP_DAYS:-14}"
mkdir -p "$DEST"
: "${DATABASE_URL:?DATABASE_URL gerekli}"
URL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"
pg_dump --format=custom --no-owner --file "$DEST/db_$STAMP.dump" "$URL"
if [ "${STORAGE_BACKEND:-local}" = "local" ] && [ -d "${LOCAL_STORAGE_DIR:-./data/storage}" ]; then
  tar -C "$(dirname "${LOCAL_STORAGE_DIR:-./data/storage}")" -czf "$DEST/storage_$STAMP.tar.gz" "$(basename "${LOCAL_STORAGE_DIR:-./data/storage}")"
else
  echo "S3/MinIO: nesneleri ayrıca yedekleyin, örn.: mc mirror --overwrite local/\$S3_BUCKET $DEST/s3_$STAMP/" >&2
fi
sha256sum "$DEST"/*_"$STAMP"* > "$DEST/SHA256SUMS_$STAMP"
find "$DEST" -type f -mtime +"$KEEP_DAYS" -delete
echo "Yedek tamam: $DEST ($STAMP)"
