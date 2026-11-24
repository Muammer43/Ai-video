"""Parola, JWT, simetrik şifreleme ve imzalı durum (state) yardımcıları."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings
from .errors import Unauthorized

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def create_access_token(user_id: str, token_version: int, session_id: str) -> tuple[str, int]:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(minutes=s.access_token_minutes)
    payload = {"sub": user_id, "tv": token_version, "sid": session_id, "exp": exp, "typ": "access"}
    return jwt.encode(payload, s.secret_key, algorithm="HS256"), s.access_token_minutes * 60


def decode_access_token(token: str) -> dict:
    s = get_settings()
    try:
        payload = jwt.decode(token, s.secret_key, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as e:
        raise Unauthorized("Oturum süresi doldu", code="token_expired") from e
    except jwt.PyJWTError as e:
        raise Unauthorized("Geçersiz oturum anahtarı", code="token_invalid") from e
    if payload.get("typ") != "access":
        raise Unauthorized("Geçersiz oturum anahtarı", code="token_invalid")
    return payload


def create_media_token(user_id: str, key: str, ttl: int | None = None) -> str:
    """Video/dosya erişimi için kısa ömürlü, kullanıcıya bağlı imzalı token (ör. <video> oynatıcı)."""
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(seconds=ttl or s.signed_url_ttl_seconds)
    return jwt.encode({"sub": user_id, "key": key, "exp": exp, "typ": "media"}, s.secret_key, algorithm="HS256")


def decode_media_token(token: str) -> dict:
    s = get_settings()
    try:
        p = jwt.decode(token, s.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise Unauthorized("Geçersiz veya süresi dolmuş dosya bağlantısı", code="media_token_invalid") from e
    if p.get("typ") != "media":
        raise Unauthorized("Geçersiz dosya bağlantısı", code="media_token_invalid")
    return p


# ---------- Fernet ----------
def _fernet() -> Fernet:
    s = get_settings()
    key = s.encryption_key
    if not key:
        # dev/test: secret_key'den deterministik türet (üretimde validate_for_runtime engeller)
        key = base64.urlsafe_b64encode(hashlib.sha256(("enc:" + s.secret_key).encode()).digest()).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise ValueError("Şifre çözülemedi (ENCRYPTION_KEY değişmiş olabilir)") from e


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "••••"
    return value[:3] + "••••" + value[-3:]


# ---------- imzalı state (OAuth) ----------
def sign_state(data: dict, ttl: int = 900) -> str:
    s = get_settings()
    body = dict(data)
    body["exp"] = int(time.time()) + ttl
    raw = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(s.secret_key.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def verify_state(state: str) -> dict:
    s = get_settings()
    try:
        raw, sig = state.rsplit(".", 1)
        expected = hmac.new(s.secret_key.encode(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("imza")
        pad = "=" * (-len(raw) % 4)
        data = json.loads(base64.urlsafe_b64decode(raw + pad))
        if data.get("exp", 0) < time.time():
            raise ValueError("süre")
        return data
    except Exception as e:  # noqa: BLE001
        raise Unauthorized("Geçersiz veya süresi dolmuş OAuth durumu", code="oauth_state_invalid") from e


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge
