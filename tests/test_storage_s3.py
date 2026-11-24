"""S3 uyumlu depolama (moto ile SİMÜLE edilmiş S3 — gerçek AWS/MinIO değil)."""
import pytest
from moto import mock_aws

from backend.storage.base import S3Storage


@pytest.fixture()
def s3():
    with mock_aws():
        st = S3Storage("", "aivf-test", "us-east-1", "test", "test")
        st.ensure_bucket()
        yield st


def test_s3_roundtrip_presign_delete(s3, tmp_path):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"0123456789" * 1000)
    assert s3.put_file("u1/p1/final/v.mp4", f, "video/mp4") == 10000
    assert s3.exists("u1/p1/final/v.mp4") and s3.size("u1/p1/final/v.mp4") == 10000
    out = s3.get_file("u1/p1/final/v.mp4", tmp_path / "dl" / "x.mp4")
    assert out.read_bytes() == f.read_bytes()
    url = s3.presigned_url("u1/p1/final/v.mp4", 600, "ai_video.mp4")
    assert url.startswith("https://") and "X-Amz-Signature" in url and "Expires" in url or "X-Amz-Expires=600" in url
    assert s3.local_path("u1/p1/final/v.mp4") is None
    s3.delete("u1/p1/final/v.mp4")
    assert not s3.exists("u1/p1/final/v.mp4")
    with pytest.raises(ValueError):
        s3.put_bytes("../escape", b"x")
