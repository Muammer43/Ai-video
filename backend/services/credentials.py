"""Sağlayıcı anahtarı çözümleme: kullanıcı (şifreli) → sunucu ortamı → yok."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.security import decrypt_secret, encrypt_secret, mask_secret
from ..models import ProviderCredential

ENV_KEYS = {
    "openai": "openai_api_key", "anthropic": "anthropic_api_key", "fal": "fal_key", "runway": "runway_api_key",
    "replicate": "replicate_api_token", "elevenlabs": "elevenlabs_api_key", "pexels": "pexels_api_key",
    "pixabay": "pixabay_api_key",
}
KNOWN_PROVIDERS = set(ENV_KEYS)


class CredentialResolver:
    def __init__(self, db: Session | None, user_id: str | None):
        self.db = db
        self.user_id = user_id
        self._cache: dict[str, str] = {}

    def get(self, provider: str) -> str:
        if provider in self._cache:
            return self._cache[provider]
        val = ""
        if self.db is not None and self.user_id:
            row = self.db.execute(select(ProviderCredential).where(
                ProviderCredential.user_id == self.user_id, ProviderCredential.provider == provider)).scalar_one_or_none()
            if row:
                try:
                    val = decrypt_secret(row.encrypted_secret)
                except ValueError:
                    val = ""
        if not val and provider in ENV_KEYS:
            val = getattr(get_settings(), ENV_KEYS[provider], "") or ""
        self._cache[provider] = val
        return val

    def has(self, provider: str) -> bool:
        return bool(self.get(provider))


def set_credential(db: Session, user_id: str, provider: str, secret: str) -> ProviderCredential:
    row = db.execute(select(ProviderCredential).where(
        ProviderCredential.user_id == user_id, ProviderCredential.provider == provider)).scalar_one_or_none()
    if row is None:
        row = ProviderCredential(user_id=user_id, provider=provider, encrypted_secret="")
        db.add(row)
    row.encrypted_secret = encrypt_secret(secret)
    row.hint = mask_secret(secret)
    db.commit()
    return row


def delete_credential(db: Session, user_id: str, provider: str) -> bool:
    row = db.execute(select(ProviderCredential).where(
        ProviderCredential.user_id == user_id, ProviderCredential.provider == provider)).scalar_one_or_none()
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True
