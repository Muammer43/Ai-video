from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from ...editor import ffmpeg as ff


def data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def describe(path: Path) -> dict:
    try:
        i = ff.probe(path)
        return {"resolution": f"{i.width}x{i.height}", "duration": round(i.duration, 2), "fps": round(i.fps, 1)}
    except Exception:  # noqa: BLE001
        return {}
