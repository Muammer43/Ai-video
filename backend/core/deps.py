from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from ..database.session import get_db
from ..models import AuditLog, AuthSession, User
from .errors import Forbidden, Unauthorized
from .security import decode_access_token


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else ""))[:64]


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise Unauthorized("Kimlik doğrulama gerekli", code="auth_required")
    payload = decode_access_token(auth[7:].strip())
    user = db.get(User, payload["sub"])
    if user is None or not user.is_active or user.token_version != payload.get("tv"):
        raise Unauthorized("Oturum geçersiz", code="token_invalid")
    sess = db.get(AuthSession, payload.get("sid", ""))
    if sess is None or sess.revoked_at is not None:
        raise Unauthorized("Oturum sonlandırılmış", code="session_revoked")
    request.state.user_id = user.id
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise Forbidden("Yönetici yetkisi gerekli")
    return user


def audit(db: Session, request: Request | None, user_id: str | None, action: str, entity: str = "", entity_id: str = "", **meta) -> None:
    db.add(AuditLog(user_id=user_id, action=action, entity=entity, entity_id=entity_id, ip=client_ip(request) if request else "",
                    user_agent=(request.headers.get("user-agent", "")[:300] if request else ""), meta=meta))
    db.commit()
