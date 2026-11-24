from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core import ratelimit
from ..core.config import get_settings
from ..core.deps import audit, client_ip, current_user
from ..core.errors import AppError, Forbidden, Unauthorized
from ..core.security import create_access_token, hash_password, new_refresh_token, sha256_hex, verify_password
from ..database.session import get_db
from ..models import AuthSession, User, utcnow
from ..schemas.api import LoginIn, PasswordChangeIn, RefreshIn, RegisterIn

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "display_name": u.display_name, "role": u.role, "created_at": u.created_at.isoformat()}


def _issue(db: Session, u: User, request: Request) -> dict:
    s = get_settings()
    refresh = new_refresh_token()
    sess = AuthSession(user_id=u.id, refresh_hash=sha256_hex(refresh), user_agent=request.headers.get("user-agent", "")[:300], ip=client_ip(request),
                       expires_at=utcnow() + timedelta(days=s.refresh_token_days))
    db.add(sess)
    db.flush()
    access, ttl = create_access_token(u.id, u.token_version, sess.id)
    db.commit()
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer", "expires_in": ttl, "user": _user_out(u)}


@router.post("/register", status_code=201)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    ok, wait = ratelimit.hit(f"reg:{client_ip(request)}", 10, 3600)
    if not ok:
        raise AppError("Çok fazla kayıt denemesi", code="rate_limited", status_code=429)
    count = db.execute(select(func.count()).select_from(User)).scalar() or 0
    if count > 0 and not s.allow_registration:
        raise Forbidden("Kayıt kapalı (ALLOW_REGISTRATION=false)")
    if db.execute(select(User).where(User.email == body.email)).scalar_one_or_none():
        raise AppError("Bu e-posta zaten kayıtlı", code="email_taken", status_code=409)
    u = User(email=body.email, password_hash=hash_password(body.password), display_name=body.display_name or body.email.split("@")[0],
             role="admin" if count == 0 else "user")  # ilk kullanıcı yönetici
    db.add(u)
    db.commit()
    audit(db, request, u.id, "auth.register", "user", u.id)
    return _issue(db, u, request)


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    email = body.email.strip().lower()
    ok, wait = ratelimit.hit(f"login:{client_ip(request)}:{email}", s.login_rate_limit_per_minute, 60)
    if not ok:
        raise AppError(f"Çok fazla giriş denemesi; {wait} sn sonra tekrar deneyin", code="rate_limited", status_code=429)
    u = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    # zamanlama farkını azaltmak için kullanıcı yoksa da hash doğrula
    valid = verify_password(body.password, u.password_hash if u else "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHRzb21l$" + "A" * 43)
    if not u or not valid or not u.is_active:
        audit(db, request, u.id if u else None, "auth.login_failed", "user", email)
        raise Unauthorized("E-posta veya parola hatalı", code="bad_credentials")
    u.last_login_at = utcnow()
    audit(db, request, u.id, "auth.login", "user", u.id)
    return _issue(db, u, request)


@router.post("/refresh")
def refresh(body: RefreshIn, request: Request, db: Session = Depends(get_db)):
    sess = db.execute(select(AuthSession).where(AuthSession.refresh_hash == sha256_hex(body.refresh_token))).scalar_one_or_none()
    if sess is None or sess.revoked_at is not None or sess.expires_at < utcnow():
        if sess is not None and sess.revoked_at is not None:  # çalınmış/yeniden kullanılmış token: kullanıcının tüm oturumlarını kapat
            for o in db.execute(select(AuthSession).where(AuthSession.user_id == sess.user_id, AuthSession.revoked_at.is_(None))).scalars():
                o.revoked_at = utcnow()
            db.commit()
            audit(db, request, sess.user_id, "auth.refresh_reuse_detected", "session", sess.id)
        raise Unauthorized("Yenileme anahtarı geçersiz", code="refresh_invalid")
    u = db.get(User, sess.user_id)
    if u is None or not u.is_active:
        raise Unauthorized("Hesap devre dışı", code="refresh_invalid")
    sess.revoked_at = utcnow()  # rotasyon: eski anahtar tek kullanımlık
    db.commit()
    return _issue(db, u, request)


@router.post("/logout")
def logout(body: RefreshIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sess = db.execute(select(AuthSession).where(AuthSession.refresh_hash == sha256_hex(body.refresh_token), AuthSession.user_id == user.id)).scalar_one_or_none()
    if sess:
        sess.revoked_at = utcnow()
        db.commit()
    audit(db, request, user.id, "auth.logout", "user", user.id)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return _user_out(user)


@router.post("/change-password")
def change_password(body: PasswordChangeIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not verify_password(body.old_password, user.password_hash):
        raise Unauthorized("Eski parola hatalı", code="bad_credentials")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # tüm erişim token'ları geçersiz
    for o in db.execute(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))).scalars():
        o.revoked_at = utcnow()
    db.commit()
    audit(db, request, user.id, "auth.change_password", "user", user.id)
    return {"ok": True, "message": "Parola değişti; tüm oturumlar kapatıldı, yeniden giriş yapın."}
