#!/data/data/com.termux/files/usr/bin/bash
# Sunucuyu başlatır. Uygulamada sunucu adresi:  http://127.0.0.1:8000
# Aynı Wi-Fi'deki başka cihazlardan erişim için:  bash scripts/termux_run.sh 0.0.0.0
cd "$(dirname "$0")/.."
HOST="${1:-127.0.0.1}"
command -v termux-wake-lock >/dev/null && termux-wake-lock   # telefon uyurken Termux'un öldürülmesini azaltır
exec .venv/bin/uvicorn backend.main:app --host "$HOST" --port 8000
