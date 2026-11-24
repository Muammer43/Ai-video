#!/data/data/com.termux/files/usr/bin/bash
# AI Video Factory Pro — Termux (Android) kurulumu. Sunucu telefonun kendisinde çalışır (SQLite + yerel depolama + süreç içi kuyruk).
# Kullanım:  cd aivf_termux && bash scripts/termux_setup.sh      (10-40 dk sürebilir: Python paketleri telefonda derlenir)
set -e
cd "$(dirname "$0")/.."
ROOT="$PWD"
echo "==> 1/5 Termux paketleri"
pkg update -y
pkg install -y python ffmpeg espeak-ng ttf-dejavu clang rust make pkg-config libffi openssl unzip curl python-cryptography python-numpy || \
  pkg install -y python ffmpeg espeak ttf-dejavu clang rust make pkg-config libffi openssl unzip curl
pkg install -y python-pydantic 2>/dev/null || true   # varsa hazır paket (derleme süresini kısaltır)
echo "==> 2/5 Python sanal ortamı"
python -m venv --system-site-packages "$ROOT/.venv"
export ANDROID_API_LEVEL="$(getprop ro.build.version.sdk 2>/dev/null || echo 24)"
export CARGO_BUILD_TARGET="" MATHLIB=m
"$ROOT/.venv/bin/pip" install --upgrade pip wheel setuptools
echo "==> 3/5 Python bağımlılıkları (pydantic-core/argon2 derlenebilir; sabırlı olun)"
"$ROOT/.venv/bin/pip" install -r requirements-termux.txt
echo "==> 4/5 Yapılandırma (.env)"
if [ ! -f "$ROOT/.env" ]; then
  FONT_DIR="$(dirname "$(find "$PREFIX/share/fonts" -name 'DejaVuSans.ttf' 2>/dev/null | head -1)")"
  SECRET="$("$ROOT/.venv/bin/python" -c 'import secrets;print(secrets.token_urlsafe(48))')"
  ENCKEY="$("$ROOT/.venv/bin/python" -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"
  mkdir -p "$HOME/aivf_data"
  cat > "$ROOT/.env" <<ENVEOF
ENV=dev
CELERY_EAGER=true
SECRET_KEY=$SECRET
ENCRYPTION_KEY=$ENCKEY
DATABASE_URL=sqlite:///$HOME/aivf_data/aivf.db
LOCAL_STORAGE_DIR=$HOME/aivf_data/storage
WORK_DIR=$HOME/aivf_data/work
PUBLIC_BASE_URL=http://127.0.0.1:8000
ALLOW_REGISTRATION=true
FONT_DIR=${FONT_DIR:-/usr/share/fonts/truetype/dejavu}
ENVEOF
  chmod 600 "$ROOT/.env"
fi
echo "==> 5/5 Doğrulama"
"$ROOT/.venv/bin/python" - <<'PYEOF'
import shutil, subprocess
from backend.core.config import get_settings
s = get_settings()
print("ffmpeg  :", shutil.which("ffmpeg") or "YOK")
print("espeak  :", shutil.which("espeak-ng") or "YOK (yalnızca çevrimdışı TTS etkilenir)")
out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
print("libass  :", "ass " in out, "| loudnorm:", "loudnorm" in out, "| sidechaincompress:", "sidechaincompress" in out, "| xfade:", "xfade" in out)
print("yazı tipi dizini:", s.font_dir)
PYEOF
echo; echo "Kurulum bitti. Sunucuyu başlatmak için:  bash scripts/termux_run.sh"
