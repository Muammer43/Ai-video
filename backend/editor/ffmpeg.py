"""FFmpeg/ffprobe çalıştırma yardımcıları. Kullanıcı kaynaklı metin ASLA filtre dizgesine girmez (ASS/dosya üzerinden)."""
from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..core.config import get_settings

log = logging.getLogger(__name__)

DIMS = {
    ("9:16", "720p"): (720, 1280), ("9:16", "1080p"): (1080, 1920),
    ("16:9", "720p"): (1280, 720), ("16:9", "1080p"): (1920, 1080),
    ("1:1", "720p"): (720, 720), ("1:1", "1080p"): (1080, 1080),
}
FPS = 30


class FFmpegError(RuntimeError):
    pass


def dims(aspect: str, resolution: str) -> tuple[int, int]:
    try:
        return DIMS[(aspect, resolution)]
    except KeyError as e:
        raise ValueError(f"Desteklenmeyen biçim: {aspect} {resolution}") from e


def run(args: list[str], *, timeout: int = 600, cancel_check: Callable[[], None] | None = None,
        binary: str | None = None, cwd: str | Path | None = None) -> subprocess.CompletedProcess:
    s = get_settings()
    cmd = [s.ffmpeg_bin, "-hide_banner", "-nostdin", "-y", *args] if binary is None else [binary, *args]
    if cancel_check is None:
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        except subprocess.TimeoutExpired as e:
            raise FFmpegError(f"ffmpeg zaman aşımı ({timeout} sn)") from e
    else:  # iptal edilebilir çalıştırma
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd)
        import time
        t0 = time.monotonic()
        while True:
            try:
                out, err = proc.communicate(timeout=1.0)
                p = subprocess.CompletedProcess(cmd, proc.returncode, out, err)
                break
            except subprocess.TimeoutExpired:
                try:
                    cancel_check()
                except BaseException:
                    proc.kill()
                    proc.wait()
                    raise
                if time.monotonic() - t0 > timeout:
                    proc.kill()
                    proc.wait()
                    raise FFmpegError(f"ffmpeg zaman aşımı ({timeout} sn)") from None
    if p.returncode != 0:
        tail = "\n".join((p.stderr or "").strip().splitlines()[-12:])
        raise FFmpegError(f"ffmpeg başarısız (kod {p.returncode}): {tail[-1500:]}")
    return p


@dataclass
class MediaInfo:
    duration: float
    width: int
    height: int
    fps: float
    has_video: bool
    has_audio: bool
    vcodec: str
    acodec: str
    sample_rate: int
    size: int
    pix_fmt: str
    bit_rate: int


def probe(path: str | Path) -> MediaInfo:
    s = get_settings()
    p = subprocess.run([s.ffprobe_bin, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                       capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise FFmpegError(f"ffprobe başarısız: {p.stderr.strip()[-300:]}")
    d = json.loads(p.stdout or "{}")
    v = next((x for x in d.get("streams", []) if x.get("codec_type") == "video"), None)
    a = next((x for x in d.get("streams", []) if x.get("codec_type") == "audio"), None)
    fmt = d.get("format", {})
    fps = 0.0
    if v and v.get("avg_frame_rate", "0/0") not in ("0/0", ""):
        n, _, den = v["avg_frame_rate"].partition("/")
        fps = float(n) / float(den or 1) if float(den or 1) else 0.0
    dur = float(fmt.get("duration") or (v or a or {}).get("duration") or 0)
    return MediaInfo(duration=dur, width=int((v or {}).get("width", 0)), height=int((v or {}).get("height", 0)), fps=fps,
                     has_video=v is not None, has_audio=a is not None, vcodec=(v or {}).get("codec_name", ""),
                     acodec=(a or {}).get("codec_name", ""), sample_rate=int((a or {}).get("sample_rate", 0) or 0),
                     size=int(fmt.get("size", 0) or 0), pix_fmt=(v or {}).get("pix_fmt", ""),
                     bit_rate=int(fmt.get("bit_rate", 0) or 0))


def audio_duration(path: str | Path) -> float:
    return probe(path).duration


def ass_escape(text: str) -> str:
    """ASS Dialogue metni için kaçış: override blokları ve satır sonları etkisizleştirilir."""
    t = text.replace("\\", "＼").replace("{", "(").replace("}", ")")
    t = re.sub(r"[\r\n]+", " ", t)
    return t.strip()


def filter_path(p: str | Path) -> str:
    """Filtre dizgesinde kullanılacak yol kaçışı (sadece sistemin ürettiği yollar için)."""
    return str(p).replace("\\", "/").replace(":", r"\:").replace("'", r"\'").replace(",", r"\,").replace("[", r"\[").replace("]", r"\]")
