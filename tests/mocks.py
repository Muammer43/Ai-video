"""MOCK sağlayıcı API'leri (httpx.MockTransport). Bunlar canlı servis DEĞİLDİR; yalnızca adaptörlerin istek/yanıt mantığını,
yedeklemeyi, maliyet kaydını ve pipeline entegrasyonunu doğrular. Medya çıktıları gerçek FFmpeg ile üretilmiş gerçek dosyalardır."""
from __future__ import annotations

import base64
import json
import subprocess
import tempfile
from pathlib import Path

import httpx

_cache: dict[str, bytes] = {}


def _ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-nostdin", *args], check=True)


def media(kind: str, i: int = 0) -> bytes:
    key = f"{kind}{i}"
    if key in _cache:
        return _cache[key]
    d = Path(tempfile.mkdtemp(prefix="mockmedia_"))
    if kind == "png":
        src = ["testsrc2", "mandelbrot", "rgbtestsrc", "testsrc", "smptebars", "cellauto"][i % 6]
        out = d / "a.png"
        _ff("-f", "lavfi", "-i", f"{src}=s=512x768", "-frames:v", "1", str(out))
    elif kind == "mp3":
        out = d / "a.mp3"
        _ff("-f", "lavfi", "-i", f"sine=frequency={180 + 40 * i}:duration={2.5 + 0.4 * i}", "-af", "tremolo=f=5:d=0.6,volume=0.6", str(out))
    else:  # mp4
        src = ["testsrc2", "mandelbrot", "rgbtestsrc", "testsrc"][i % 4]
        out = d / "a.mp4"
        _ff("-f", "lavfi", "-i", f"{src}=s=540x960:r=30", "-t", "5", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out))
    _cache[key] = out.read_bytes()
    return _cache[key]


class FakeAPI:
    def __init__(self, *, fail_hosts: set[str] | None = None, script: dict | None = None, fal_fail_first: int = 0):
        self.calls: list[tuple[str, str]] = []
        self.counter = {"img": 0, "tts": 0, "vid": 0}
        self.fail_hosts = fail_hosts or set()
        self.script = script
        self.fal_fail_first = fal_fail_first
        self.bodies: list[dict] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, req: httpx.Request) -> httpx.Response:
        host, path = req.url.host, req.url.path
        self.calls.append((req.method, f"{host}{path}"))
        if host in self.fail_hosts:
            return httpx.Response(503, json={"error": "unavailable"})
        body = {}
        if req.content and "json" in req.headers.get("content-type", ""):
            try:
                body = json.loads(req.content)
                self.bodies.append({"url": f"{host}{path}", **body})
            except Exception:  # noqa: BLE001
                body = {}
        if host == "api.openai.com":
            return self._openai(path, body, req)
        if host == "queue.fal.run":
            return self._fal(req, path, body)
        if host == "fal.media":
            return httpx.Response(200, content=media("mp4", self.counter["vid"]))
        if host == "api.pexels.com":
            return httpx.Response(200, json={"videos": [{"id": 77 + i, "duration": 8, "url": "https://pexels.com/video/x", "user": {"name": "Jane"},
                                                         "video_files": [{"file_type": "video/mp4", "link": "https://videos.pexels.com/v.mp4", "height": 1280, "width": 720}]}
                                                        for i in range(5)]}, headers={"x-ratelimit-remaining": "190"})
        if host == "videos.pexels.com":
            return httpx.Response(200, content=media("mp4", 3))
        if host == "api.elevenlabs.io":
            return httpx.Response(200, content=media("mp3", 1))
        return httpx.Response(404, json={"error": f"mock: bilinmeyen {host}{path}"})

    def _openai(self, path: str, body: dict, req: httpx.Request) -> httpx.Response:
        if path == "/v1/chat/completions":
            user = body["messages"][1]["content"]
            if '"flagged"' in user:
                out = {"flagged": False, "severity": "none", "misleading": False, "reasons": []}
            elif '"ideas"' in user:
                out = {"ideas": [{"title": f"Mock fikir {i}: uzayın şaşırtıcı gerçekleri", "angle": "a", "audience": "genel", "format": "listicle",
                                  "score": 80 - i, "reason": "r"} for i in range(8)]}
            else:
                out = self.script or default_script()
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(out, ensure_ascii=False)}}],
                                             "usage": {"prompt_tokens": 1200, "completion_tokens": 800, "total_tokens": 2000}})
        if path == "/v1/images/generations":
            i = self.counter["img"]
            self.counter["img"] += 1
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(media("png", i)).decode()}]})
        if path == "/v1/audio/speech":
            i = self.counter["tts"]
            self.counter["tts"] += 1
            return httpx.Response(200, content=media("mp3", i % 3))
        if path == "/v1/audio/transcriptions":
            # kelime zamanları (mock): 0.1 sn aralıklarla
            words = [{"word": w, "start": 0.1 + 0.3 * k, "end": 0.35 + 0.3 * k} for k, w in enumerate("deneme kelime zamanı için sahte yanıt".split())]
            return httpx.Response(200, json={"duration": 3.0, "text": " ".join(w["word"] for w in words), "words": words})
        return httpx.Response(404, json={"error": "mock openai path"})

    def _fal(self, req: httpx.Request, path: str, body: dict) -> httpx.Response:
        if req.method == "POST":
            if self.fal_fail_first > 0:
                self.fal_fail_first -= 1
                return httpx.Response(500, json={"error": "boom"})
            self.counter["vid"] += 1
            return httpx.Response(200, json={"request_id": "r1", "status_url": "https://queue.fal.run/x/requests/r1/status",
                                             "response_url": "https://queue.fal.run/x/requests/r1"})
        if path.endswith("/status"):
            return httpx.Response(200, json={"status": "COMPLETED"})
        return httpx.Response(200, json={"video": {"url": "https://fal.media/out.mp4", "content_type": "video/mp4"}})


def default_script(n: int = 4) -> dict:
    scenes = [{"narration": f"Bu bir sahte senaryonun {i + 1}. sahnesidir ve uzayla ilgili gerçek bir bilgi verir.",
               "visual_prompt": f"A wide shot of planet number {i + 1} in deep space", "camera": "slow push-in", "lighting": "soft rim light",
               "composition": "centered", "transition": ["fade", "dissolve", "slide", "wipe"][i % 4], "on_screen_text": "", "stock_query": "space planet"}
              for i in range(n)]
    return {"title": "Güneş sistemi hakkında 4 gerçek", "hook": scenes[0]["narration"], "scenes": scenes, "cta": "Takip et.",
            "description": "Bilimsel gerçekler.", "hashtags": ["uzay", "#bilim"], "style_bible": "consistent deep-space palette, teal and orange",
            "facts_to_verify": [], "claims_risk": "low", "sources": []}
