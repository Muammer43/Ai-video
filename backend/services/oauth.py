"""Sosyal hesap bağlama (OAuth 2.0 + PKCE), token şifreleme ve yenileme."""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.errors import AppError, NotFound
from ..core.security import decrypt_secret, encrypt_secret, pkce_pair, sign_state, verify_state
from ..models import SocialAccount, utcnow
from ..providers.base import ProviderError
from ..providers.publishing.base import TokenSet, get_publisher, redirect_uri
from .notifications import notify

log = logging.getLogger(__name__)


def start_authorize(user_id: str, platform: str, channel_id: str | None = None) -> dict:
    pub = get_publisher(platform)
    if not pub.configured():
        raise AppError(f"{pub.label} için OAuth uygulaması yapılandırılmamış: {pub.config_hint()}", code="oauth_not_configured", status_code=422)
    verifier, challenge = pkce_pair()
    state = sign_state({"u": user_id, "p": platform, "v": verifier, "c": channel_id})
    return {"url": pub.authorize_url(redirect_uri(platform), state, challenge), "requirements": pub.requirements, "redirect_uri": redirect_uri(platform)}


def _apply(acc: SocialAccount, ts: TokenSet) -> None:
    acc.access_token_enc = encrypt_secret(ts.access_token)
    if ts.refresh_token:
        acc.refresh_token_enc = encrypt_secret(ts.refresh_token)
    acc.token_expires_at = utcnow() + timedelta(seconds=ts.expires_in)
    if ts.refresh_expires_in:
        acc.refresh_expires_at = utcnow() + timedelta(seconds=ts.refresh_expires_in)
    acc.status, acc.last_error = "active", ""


def handle_callback(db: Session, platform: str, code: str, state: str) -> SocialAccount:
    data = verify_state(state)
    if data.get("p") != platform:
        raise AppError("OAuth platform uyuşmazlığı", code="oauth_state_invalid", status_code=400)
    pub = get_publisher(platform)
    ts = pub.exchange_code(code, redirect_uri(platform), data["v"])
    acc = db.execute(select(SocialAccount).where(SocialAccount.user_id == data["u"], SocialAccount.platform == platform,
                                                 SocialAccount.external_id == ts.external_id)).scalar_one_or_none()
    if acc is None:
        acc = SocialAccount(user_id=data["u"], platform=platform, external_id=ts.external_id)
        db.add(acc)
    acc.display_name, acc.account_type, acc.scopes, acc.capabilities = ts.display_name, ts.account_type, ts.scopes, ts.capabilities
    acc.channel_id = data.get("c")
    _apply(acc, ts)
    db.commit()
    return acc


def access_token(db: Session, acc: SocialAccount, *, margin_s: int = 300) -> str:
    """Geçerli erişim token'ı; süresi dolmak üzereyse yeniler. Yenileme başarısızsa hesap 'needs_reauth' olur ve kullanıcı bilgilendirilir."""
    if acc.status == "disconnected":
        raise ProviderError("hesap bağlantısı kesilmiş", "auth")
    exp = acc.token_expires_at
    if exp is None or exp - utcnow() > timedelta(seconds=margin_s):
        return decrypt_secret(acc.access_token_enc)
    pub = get_publisher(acc.platform)
    try:
        rt = decrypt_secret(acc.refresh_token_enc) if acc.refresh_token_enc else ""
        if acc.platform != "instagram" and not rt:
            raise ProviderError("refresh token yok", "auth")
        ts = pub.refresh(rt, decrypt_secret(acc.access_token_enc))
    except ProviderError as e:
        if e.kind == "auth":
            acc.status, acc.last_error = "needs_reauth", str(e)[:300]
            db.commit()
            notify(db, acc.user_id, "system", f"{pub.label} hesabı yeniden bağlanmalı", str(e)[:200], level="warning", data={"account_id": acc.id})
        raise
    _apply(acc, ts)
    db.commit()
    return ts.access_token


def disconnect(db: Session, user_id: str, account_id: str) -> None:
    acc = db.get(SocialAccount, account_id)
    if acc is None or acc.user_id != user_id:
        raise NotFound("Hesap bulunamadı")
    acc.status, acc.access_token_enc, acc.refresh_token_enc = "disconnected", "", ""
    db.commit()
