#!/usr/bin/env bash
# Teslim ZIP'i üretir: kaynak + APK + dokümanlar (venv, build çıktıları, veri, .env hariç).
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${1:-dist/AI_VIDEO_FACTORY_PRO.zip}"; mkdir -p "$(dirname "$OUT")"; rm -f "$OUT"
git ls-files -z --cached --others --exclude-standard | grep -zv '^dist/' | xargs -0 zip -q "$OUT"
[ -f dist/AI_Video_Factory_Pro.apk ] && zip -q "$OUT" dist/AI_Video_Factory_Pro.apk dist/AI_Video_Factory_Pro.apk.sha256
unzip -l "$OUT" | tail -1
