from __future__ import annotations

import hashlib
import mimetypes
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import Asset
from ..storage import get_storage

MIME = {".mp4": "video/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".png": "image/png", ".jpg": "image/jpeg",
        ".srt": "application/x-subrip", ".ass": "text/x-ssa", ".json": "application/json"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def store_asset(db: Session, user_id: str, project_id: str | None, kind: str, path: Path, *, duration: float | None = None,
                license: dict | None = None, meta: dict | None = None) -> Asset:
    ext = path.suffix.lower() or ".bin"
    key = f"{user_id}/{project_id or 'library'}/{kind}/{uuid.uuid4().hex}{ext}"
    mime = MIME.get(ext) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    size = get_storage().put_file(key, path, mime)
    a = Asset(user_id=user_id, project_id=project_id, kind=kind, storage_key=key, mime=mime, size=size, duration=duration,
              sha256=sha256_file(path), license=license or {}, meta=meta or {})
    db.add(a)
    db.commit()
    return a


def local_copy(db: Session, asset_id: str, work: Path) -> Path:
    a = db.get(Asset, asset_id)
    if a is None:
        raise FileNotFoundError(asset_id)
    st = get_storage()
    lp = st.local_path(a.storage_key)
    if lp is not None:
        return lp
    dest = work / "dl" / (a.id + Path(a.storage_key).suffix)
    if not dest.exists():
        st.get_file(a.storage_key, dest)
    return dest


def delete_asset(db: Session, a: Asset) -> None:
    try:
        get_storage().delete(a.storage_key)
    finally:
        db.delete(a)
