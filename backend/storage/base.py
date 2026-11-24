"""S3 uyumlu veya yerel nesne depolama. Anahtar şeması: {user_id}/{project_id|library}/{kind}/{dosya}."""
from __future__ import annotations

import mimetypes
import shutil
from pathlib import Path
from typing import Protocol

from ..core.config import get_settings


class Storage(Protocol):
    name: str

    def put_file(self, key: str, path: str | Path, content_type: str | None = None) -> int: ...
    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> int: ...
    def get_file(self, key: str, dest: str | Path) -> Path: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def local_path(self, key: str) -> Path | None: ...
    def presigned_url(self, key: str, ttl: int, filename: str | None = None) -> str | None: ...
    def size(self, key: str) -> int: ...


def _safe_key(key: str) -> str:
    if key.startswith("/") or ".." in key.split("/") or "\\" in key or "\x00" in key:
        raise ValueError("Geçersiz depolama anahtarı")
    return key


class LocalStorage:
    name = "local"

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _p(self, key: str) -> Path:
        p = (self.root / _safe_key(key)).resolve()
        if self.root not in p.parents:
            raise ValueError("Depolama yolu kök dışına çıkıyor")
        return p

    def put_file(self, key, path, content_type=None):  # noqa: ANN001
        dst = self._p(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dst)
        return dst.stat().st_size

    def put_bytes(self, key, data, content_type=None):  # noqa: ANN001
        dst = self._p(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        return len(data)

    def get_file(self, key, dest):  # noqa: ANN001
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self._p(key), dest)
        return dest

    def exists(self, key):  # noqa: ANN001
        return self._p(key).is_file()

    def delete(self, key):  # noqa: ANN001
        p = self._p(key)
        if p.is_file():
            p.unlink()

    def local_path(self, key):  # noqa: ANN001
        p = self._p(key)
        return p if p.is_file() else None

    def presigned_url(self, key, ttl, filename=None):  # noqa: ANN001
        return None  # yerel depoda API üzerinden imzalı medya token'ı kullanılır

    def size(self, key):  # noqa: ANN001
        return self._p(key).stat().st_size


class S3Storage:
    name = "s3"

    def __init__(self, endpoint_url: str, bucket: str, region: str, access_key: str, secret_key: str):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            region_name=region,
            aws_access_key_id=access_key or None,
            aws_secret_access_key=secret_key or None,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}, retries={"max_attempts": 4}),
        )

    def ensure_bucket(self) -> None:
        from botocore.exceptions import ClientError

        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)

    def put_file(self, key, path, content_type=None):  # noqa: ANN001
        ct = content_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.client.upload_file(str(path), self.bucket, _safe_key(key), ExtraArgs={"ContentType": ct})
        return Path(path).stat().st_size

    def put_bytes(self, key, data, content_type=None):  # noqa: ANN001
        self.client.put_object(Bucket=self.bucket, Key=_safe_key(key), Body=data,
                               ContentType=content_type or "application/octet-stream")
        return len(data)

    def get_file(self, key, dest):  # noqa: ANN001
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, _safe_key(key), str(dest))
        return dest

    def exists(self, key):  # noqa: ANN001
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=_safe_key(key))
            return True
        except ClientError:
            return False

    def delete(self, key):  # noqa: ANN001
        self.client.delete_object(Bucket=self.bucket, Key=_safe_key(key))

    def local_path(self, key):  # noqa: ANN001
        return None

    def presigned_url(self, key, ttl, filename=None):  # noqa: ANN001
        params = {"Bucket": self.bucket, "Key": _safe_key(key)}
        if filename:
            params["ResponseContentDisposition"] = f'inline; filename="{filename}"'
        return self.client.generate_presigned_url("get_object", Params=params, ExpiresIn=ttl)

    def size(self, key):  # noqa: ANN001
        return int(self.client.head_object(Bucket=self.bucket, Key=_safe_key(key))["ContentLength"])


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        s = get_settings()
        if s.storage_backend == "s3":
            st = S3Storage(s.s3_endpoint_url, s.s3_bucket, s.s3_region, s.s3_access_key, s.s3_secret_key)
            st.ensure_bucket()
            _storage = st
        else:
            _storage = LocalStorage(s.local_storage_dir)
    return _storage


def reset_storage() -> None:
    global _storage
    _storage = None
