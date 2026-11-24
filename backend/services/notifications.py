from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DeviceToken, Notification
from .push import send_push


def notify(db: Session, user_id: str, kind: str, title: str, body: str = "", *, level: str = "info",
           data: dict | None = None, push: bool = True) -> Notification:
    n = Notification(user_id=user_id, kind=kind, title=title[:200], body=body[:2000], level=level, data=data or {})
    db.add(n)
    db.flush()
    if push:
        tokens = [t for (t,) in db.execute(select(DeviceToken.token).where(DeviceToken.user_id == user_id)).all()]
        n.push_status = send_push(tokens, title, body, {"kind": kind, **(data or {})})
    db.commit()
    return n
