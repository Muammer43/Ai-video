"""Akıllı kalite kontrol motoru: 14 zorunlu kontrol + köken (provenance) kontrolü. Gerçek ffmpeg/ffprobe ölçümleri kullanır."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from ..core.config import get_settings
from ..editor import ffmpeg as ff
from . import safety

PLATFORM_LIMITS = {  # saniye; temkinli değerler (resmî dokümanda bulunamayanlar konservatif seçildi)
    "youtube": {"min": 3, "max": 180, "vertical_required": False},
    "tiktok": {"min": 3, "max": 180, "vertical_required": True, "fps": (23, 60), "min_side": 360, "max_bytes": 4 * 1024 ** 3},
    "instagram": {"min": 3, "max": 90, "vertical_required": True, "max_bytes": 1024 ** 3},
}
WEIGHTS = {"file_opens": 10, "duration": 6, "audio_present": 10, "loudness": 6, "black_frames": 8, "empty_scenes": 8,
           "resolution": 6, "subtitle_sync": 8, "av_match": 8, "repeated_scenes": 6, "visual_quality": 8,
           "content_safety": 8, "copyright": 6, "platform_format": 8}
TECHNICAL = {"file_opens", "audio_present", "resolution", "black_frames"}
SAFETY_IDS = {"content_safety", "copyright"}


@dataclass
class QCInput:
    video: Path
    work: Path
    aspect_ratio: str
    resolution: str
    duration_target: int
    platforms: list[str]
    scenes: list[dict]  # {"idx","narration","visual_prompt","origin","audio_path","audio_duration","license","provider"}
    timeline: list[dict]  # assemble sonucu
    cues: list[dict] = field(default_factory=list)  # {"start","end"}
    script: dict = field(default_factory=dict)
    media_mode: str = "hybrid"
    media_report: dict = field(default_factory=dict)
    music: dict = field(default_factory=dict)  # {"kind":"synth|library|none","license":{...}}
    category: str = ""
    expected_voice_is_ai: bool = True
    script_is_ai: bool = True
    has_subtitles: bool = True
    safety_llm: Callable[[dict], dict | None] | None = None  # script -> {"flagged","severity","reasons"}
    thresholds: dict = field(default_factory=lambda: {"auto_publish_min": 90, "low_risk_min": 80, "review_min": 60})


def _chk(id_: str, name: str, status: str, detail: str, score: float | None = None, critical: bool = False, data: dict | None = None) -> dict:
    sc = {"pass": 1.0, "warn": 0.6, "fail": 0.0}[status] if score is None else score
    return {"id": id_, "name": name, "status": status, "score": round(sc, 3), "critical": bool(critical and status == "fail"),
            "weight": WEIGHTS.get(id_, 0), "detail": detail, "data": data or {}}


# ---------- ffmpeg tabanlı ölçümler ----------
def _ff_stderr(args: list[str], timeout: int = 300) -> str:
    s = get_settings()
    p = subprocess.run([s.ffmpeg_bin, "-hide_banner", "-nostdin", *args], capture_output=True, text=True, timeout=timeout)
    return p.stderr


def full_decode_errors(path: Path) -> str:
    s = get_settings()
    p = subprocess.run([s.ffmpeg_bin, "-v", "error", "-nostdin", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True, timeout=600)
    return (p.stderr or "").strip() if p.returncode != 0 else (p.stderr or "").strip()


def sample_frames(path: Path, fps: float, w: int, h: int, max_frames: int = 400) -> np.ndarray:
    s = get_settings()
    p = subprocess.run([s.ffmpeg_bin, "-v", "error", "-nostdin", "-i", str(path), "-vf", f"fps={fps},scale={w}:{h},format=gray",
                        "-frames:v", str(max_frames), "-f", "rawvideo", "-"], capture_output=True, timeout=300)
    buf = np.frombuffer(p.stdout, dtype=np.uint8)
    n = len(buf) // (w * h)
    return buf[: n * w * h].reshape(n, h, w) if n else np.zeros((0, h, w), dtype=np.uint8)


def laplacian_var(img: np.ndarray) -> float:
    a = img.astype(np.float32)
    lap = -4 * a[1:-1, 1:-1] + a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:]
    return float(lap.var())


def dhash(img: np.ndarray) -> int:
    h, w = img.shape
    ys = np.linspace(0, h - 1, 8).astype(int)
    xs = np.linspace(0, w - 1, 9).astype(int)
    small = img[np.ix_(ys, xs)].astype(np.int16)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def ham(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def speech_intervals(audio: Path, offset: float = 0.0) -> list[tuple[float, float]]:
    """Temiz anlatım dosyasında konuşma aralıkları (silencedetect'in tersi)."""
    err = _ff_stderr(["-i", str(audio), "-af", "silencedetect=noise=-38dB:d=0.18", "-f", "null", "-"], 60)
    total = ff.audio_duration(audio)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    sil: list[tuple[float, float]] = []
    for i, st in enumerate(starts):
        sil.append((st, ends[i] if i < len(ends) else total))
    out, cur = [], 0.0
    for a, b in sil:
        if a - cur > 0.05:
            out.append((cur + offset, a + offset))
        cur = b
    if total - cur > 0.05:
        out.append((cur + offset, total + offset))
    return out


def _overlap(a: tuple[float, float], ivs: list[tuple[float, float]]) -> float:
    return sum(max(0.0, min(a[1], b) - max(a[0], x)) for x, b in ivs)


# ---------- kontroller ----------
def check_file_opens(q: QCInput, ctx: dict) -> dict:
    try:
        info = ff.probe(q.video)
    except Exception as e:  # noqa: BLE001
        return _chk("file_opens", "Video dosyası açılıyor", "fail", f"ffprobe okuyamadı: {e}", critical=True)
    ctx["info"] = info
    if not info.has_video or info.duration <= 0:
        return _chk("file_opens", "Video dosyası açılıyor", "fail", "Video akışı yok veya süre 0", critical=True)
    err = full_decode_errors(q.video)
    if err:
        return _chk("file_opens", "Video dosyası açılıyor", "fail", f"Çözme hataları: {err[:200]}", critical=True)
    return _chk("file_opens", "Video dosyası açılıyor", "pass", f"{info.vcodec}/{info.acodec or '-'} {info.duration:.1f} sn, tam çözme hatasız")


def check_duration(q: QCInput, ctx: dict) -> dict:
    info = ctx.get("info")
    if not info:
        return _chk("duration", "Süre uygun", "fail", "ölçülemedi")
    d = info.duration
    lo = min(PLATFORM_LIMITS[p]["min"] for p in q.platforms) if q.platforms else 3
    hi = min(PLATFORM_LIMITS[p]["max"] for p in q.platforms) if q.platforms else 180
    if d < lo or d > hi:
        return _chk("duration", "Süre uygun", "fail", f"{d:.1f} sn platform aralığı dışında ({lo}-{hi} sn)", data={"duration": d})
    dev = abs(d - q.duration_target) / max(q.duration_target, 1)
    if dev > 0.5:
        return _chk("duration", "Süre uygun", "warn", f"{d:.1f} sn, hedef {q.duration_target} sn'den %{dev * 100:.0f} sapma", data={"duration": d})
    return _chk("duration", "Süre uygun", "pass", f"{d:.1f} sn (hedef {q.duration_target} sn)", data={"duration": d})


def check_audio(q: QCInput, ctx: dict) -> dict:
    info = ctx.get("info")
    if not info or not info.has_audio:
        return _chk("audio_present", "Ses var", "fail", "Ses akışı yok", critical=True)
    err = _ff_stderr(["-i", str(q.video), "-af", "volumedetect", "-vn", "-f", "null", "-"], 120)
    m = re.search(r"mean_volume: (-?[\d.]+|-inf) dB", err)
    mean = float(m.group(1)) if m and m.group(1) != "-inf" else -99.0
    ctx["mean_volume"] = mean
    if mean < -50:
        return _chk("audio_present", "Ses var", "fail", f"Ses neredeyse sessiz (ort. {mean:.0f} dB)", critical=True)
    return _chk("audio_present", "Ses var", "pass", f"ort. ses {mean:.1f} dB")


def check_loudness(q: QCInput, ctx: dict) -> dict:
    if not ctx.get("info") or not ctx["info"].has_audio:
        return _chk("loudness", "Ses seviyesi uygun", "fail", "ses yok")
    err = _ff_stderr(["-i", str(q.video), "-af", "ebur128=peak=true", "-vn", "-f", "null", "-"], 180)
    summ = err[err.rfind("Summary:"):] if "Summary:" in err else err
    i = re.search(r"I:\s+(-?[\d.]+) LUFS", summ)
    pk = re.search(r"Peak:\s+(-?[\d.]+) dBFS", summ)
    if not i:
        return _chk("loudness", "Ses seviyesi uygun", "warn", "ölçülemedi")
    lufs = float(i.group(1))
    peak = float(pk.group(1)) if pk else 0.0
    ctx["lufs"] = lufs
    data = {"lufs": lufs, "true_peak_dbfs": peak}
    if lufs < -22 or lufs > -9 or peak > 0.0:
        return _chk("loudness", "Ses seviyesi uygun", "fail", f"{lufs:.1f} LUFS, tepe {peak:.1f} dBFS (hedef −16…−12)", data=data)
    if lufs < -18 or lufs > -11 or peak > -0.5:
        return _chk("loudness", "Ses seviyesi uygun", "warn", f"{lufs:.1f} LUFS, tepe {peak:.1f} dBFS", data=data)
    return _chk("loudness", "Ses seviyesi uygun", "pass", f"{lufs:.1f} LUFS, tepe {peak:.1f} dBFS", data=data)


def check_black(q: QCInput, ctx: dict) -> dict:
    err = _ff_stderr(["-i", str(q.video), "-vf", "blackdetect=d=0.3:pic_th=0.98:pix_th=0.10", "-an", "-f", "null", "-"], 300)
    segs = [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", err)]
    tot = sum(b - a for a, b in segs)
    if tot > 0.5:
        return _chk("black_frames", "Siyah kare yok", "fail", f"{len(segs)} siyah bölüm, toplam {tot:.1f} sn", critical=True, data={"segments": segs})
    if segs:
        return _chk("black_frames", "Siyah kare yok", "warn", f"kısa siyah bölüm {tot:.2f} sn", data={"segments": segs})
    return _chk("black_frames", "Siyah kare yok", "pass", "siyah bölüm bulunmadı")


def _frames_for(q: QCInput, ctx: dict) -> tuple[np.ndarray, float]:
    if "frames" in ctx:
        return ctx["frames"], ctx["fps"]
    info = ctx["info"]
    fps = 2.0 if info.duration < 90 else 1.0
    w = 144
    h = max(int(round(w * info.height / max(info.width, 1) / 2)) * 2, 2)
    ctx["frames"] = sample_frames(q.video, fps, w, h)
    ctx["fps"] = fps
    return ctx["frames"], fps


def check_empty_scenes(q: QCInput, ctx: dict) -> dict:
    fr, fps = _frames_for(q, ctx)
    if len(fr) == 0:
        return _chk("empty_scenes", "Boş sahne yok", "fail", "kare örneklenemedi")
    empty = []
    for t in q.timeline:
        a, b = int(t["start"] * fps), max(int(t["end"] * fps), int(t["start"] * fps) + 1)
        seg = fr[a:b]
        if len(seg) == 0:
            continue
        std = float(np.mean([f.std() for f in seg]))
        if std < 6.0:
            empty.append({"scene": t["scene"], "std": round(std, 2)})
    if empty and len(empty) >= max(1, len(q.timeline) // 2):
        return _chk("empty_scenes", "Boş sahne yok", "fail", f"{len(empty)} sahne boş/düz görünüyor", data={"scenes": empty})
    if empty:
        return _chk("empty_scenes", "Boş sahne yok", "warn", f"{len(empty)} sahne neredeyse düz", data={"scenes": empty})
    return _chk("empty_scenes", "Boş sahne yok", "pass", f"{len(q.timeline)} sahnenin hepsinde görsel içerik var")


def check_resolution(q: QCInput, ctx: dict) -> dict:
    info = ctx.get("info")
    if not info:
        return _chk("resolution", "Çözünürlük uygun", "fail", "ölçülemedi", critical=True)
    ew, eh = ff.dims(q.aspect_ratio, q.resolution)
    if (info.width, info.height) != (ew, eh):
        return _chk("resolution", "Çözünürlük uygun", "fail", f"{info.width}x{info.height} ≠ beklenen {ew}x{eh}", critical=True)
    if info.pix_fmt != "yuv420p":
        return _chk("resolution", "Çözünürlük uygun", "warn", f"piksel biçimi {info.pix_fmt}")
    return _chk("resolution", "Çözünürlük uygun", "pass", f"{info.width}x{info.height} @ {info.fps:.0f} fps")


def check_subtitle_sync(q: QCInput, ctx: dict) -> dict:
    if not q.has_subtitles:
        return _chk("subtitle_sync", "Altyazı senkronu", "warn", "altyazı kapalı; senkron ölçülmedi", score=0.7)
    if not q.cues:
        return _chk("subtitle_sync", "Altyazı senkronu", "fail", "altyazı yok")
    speech: list[tuple[float, float]] = []
    for sc, t in zip(q.scenes, q.timeline):
        if sc.get("audio_path"):
            speech += speech_intervals(Path(sc["audio_path"]), offset=t["narration_start"])
    if not speech:
        return _chk("subtitle_sync", "Altyazı senkronu", "warn", "konuşma aralığı hesaplanamadı", score=0.6)
    cue_total = sum(c["end"] - c["start"] for c in q.cues) or 1e-6
    sp_total = sum(b - a for a, b in speech) or 1e-6
    in_speech = sum(_overlap((c["start"], c["end"]), speech) for c in q.cues)
    precision = in_speech / cue_total  # altyazı gösterilirken konuşma var mı
    covered = sum(_overlap((a, b), [(c["start"], c["end"]) for c in q.cues]) for a, b in speech)
    recall = covered / sp_total  # konuşma sırasında altyazı var mı
    data = {"precision": round(precision, 3), "recall": round(recall, 3)}
    sc = min(precision, recall)
    if sc < 0.6:
        return _chk("subtitle_sync", "Altyazı senkronu", "fail", f"senkron zayıf (isabet {precision:.0%}, kapsama {recall:.0%})", data=data)
    if sc < 0.8:
        return _chk("subtitle_sync", "Altyazı senkronu", "warn", f"orta senkron (isabet {precision:.0%}, kapsama {recall:.0%})", data=data)
    return _chk("subtitle_sync", "Altyazı senkronu", "pass", f"isabet {precision:.0%}, kapsama {recall:.0%}", data=data)


def check_av_match(q: QCInput, ctx: dict) -> dict:
    issues = []
    info = ctx.get("info")
    for sc, t in zip(q.scenes, q.timeline):
        ad = sc.get("audio_duration") or 0
        if ad > (t["end"] - t["start"]) - 0.05:
            issues.append(f"sahne {t['scene'] + 1}: anlatım sahneden uzun")
        words = len((sc.get("narration") or "").split())
        if ad > 0.5:
            wps = words / ad
            if wps > 5.0 or wps < 0.8:
                issues.append(f"sahne {t['scene'] + 1}: konuşma hızı {wps:.1f} kelime/sn")
    if len(q.timeline) != len(q.scenes):
        issues.append("sahne sayısı ile zaman çizelgesi uyuşmuyor")
    if info and q.timeline:
        last_end = q.timeline[-1]["narration_end"]
        if last_end - info.duration > 0.2:
            issues.append("son anlatım video bitişinden sonra")
    if issues:
        return _chk("av_match", "Görüntü–ses uyumu", "fail" if len(issues) > 2 else "warn", "; ".join(issues[:4]), data={"issues": issues})
    return _chk("av_match", "Görüntü–ses uyumu", "pass", "anlatım süreleri sahnelere sığıyor, hız normal")


def check_repeated(q: QCInput, ctx: dict) -> dict:
    fr, fps = _frames_for(q, ctx)
    hashes = []
    for t in q.timeline:
        mid = int((t["start"] + (t["end"] - t["start"]) * 0.5) * fps)
        if 0 <= mid < len(fr):
            hashes.append((t["scene"], dhash(fr[mid])))
    dup = [(a, b) for i, (a, ha) in enumerate(hashes) for (b, hb) in hashes[i + 1:] if ham(ha, hb) <= 4]
    if not hashes:
        return _chk("repeated_scenes", "Tekrarlanan sahne yok", "warn", "karşılaştırılamadı")
    if len(dup) >= max(2, len(hashes) // 2):
        return _chk("repeated_scenes", "Tekrarlanan sahne yok", "fail", f"{len(dup)} sahne çifti neredeyse aynı", data={"pairs": dup})
    if dup:
        return _chk("repeated_scenes", "Tekrarlanan sahne yok", "warn", f"{len(dup)} benzer sahne çifti", data={"pairs": dup})
    return _chk("repeated_scenes", "Tekrarlanan sahne yok", "pass", "sahneler birbirinden farklı")


def check_visual_quality(q: QCInput, ctx: dict) -> dict:
    fr, fps = _frames_for(q, ctx)
    if len(fr) == 0:
        return _chk("visual_quality", "Görsel kalite", "fail", "kare örneklenemedi")
    sharp = float(np.mean([laplacian_var(f) for f in fr[:: max(len(fr) // 40, 1)]]))
    bright = float(fr.mean())
    data = {"sharpness": round(sharp, 1), "brightness": round(bright, 1)}
    issues = []
    if sharp < 8:
        issues.append("çok bulanık/düz")
    if bright < 22 or bright > 225:
        issues.append(f"parlaklık uç değerde ({bright:.0f})")
    if issues:
        return _chk("visual_quality", "Görsel kalite", "fail" if sharp < 3 else "warn", "; ".join(issues), data=data)
    return _chk("visual_quality", "Görsel kalite", "pass", f"keskinlik {sharp:.0f}, parlaklık {bright:.0f}", data=data)


def check_safety(q: QCInput, ctx: dict) -> dict:
    s = q.script or {}
    text = " ".join([s.get("title", ""), s.get("hook", ""), s.get("description", ""), s.get("cta", "")] +
                    [sc.get("narration", "") for sc in q.scenes] + [sc.get("on_screen_text", "") for sc in s.get("scenes", []) if isinstance(sc, dict)])
    r = safety.scan_text(text)
    data = {"rules": {k: v for k, v in r.items() if v}}
    flags = ctx.setdefault("risk_flags", [])
    if r["blocked"]:
        return _chk("content_safety", "İçerik güvenli", "fail", f"yasaklı içerik kalıbı: {', '.join(r['blocked'])}", critical=True, data=data)
    notes = []
    status = "pass"
    if r["misleading"]:
        status = "warn"
        notes.append("yanıltıcı/abartılı ifade: " + ", ".join(r["misleading"]))
        flags.append({"id": "misleading_claims", "severity": "high", "detail": notes[-1]})
    if s.get("claims_risk") == "high" or (s.get("facts_to_verify") and len(s["facts_to_verify"]) >= 3):
        status = "warn"
        notes.append("doğrulanması gereken iddialar var")
        flags.append({"id": "unverified_claims", "severity": "high", "detail": "; ".join(map(str, s.get("facts_to_verify", [])[:3]))})
    if r["sensitive"]:
        notes.append("hassas konu: " + ", ".join(r["sensitive"]))
        if "finans" in r["sensitive"] or "sağlık" in r["sensitive"]:
            if not re.search(r"yatırım tavsiyesi değildir|tavsiye değildir|not financial advice|doktora danış|not medical advice",
                             (text + " " + s.get("description", "")).lower()):
                status = "warn"
                flags.append({"id": "missing_disclaimer", "severity": "high", "detail": "finans/sağlık içeriğinde uyarı metni yok"})
        else:
            flags.append({"id": "sensitive_topic", "severity": "high", "detail": ", ".join(r["sensitive"])})
            status = "warn"
    # AI güvenlik incelemesi
    llm = None
    if q.safety_llm:
        try:
            llm = q.safety_llm({"title": s.get("title", ""), "text": text[:6000], "category": q.category})
        except Exception:  # noqa: BLE001
            llm = None
    if llm is None:
        flags.append({"id": "safety_llm_unavailable", "severity": "high", "detail": "AI güvenlik incelemesi yapılamadı (sağlayıcı yok/başarısız)"})
        notes.append("AI güvenlik incelemesi yok")
        status = "warn" if status == "pass" else status
    else:
        data["llm"] = llm
        if llm.get("flagged") and llm.get("severity") in ("high", "critical"):
            return _chk("content_safety", "İçerik güvenli", "fail", "AI incelemesi riskli buldu: " + "; ".join(llm.get("reasons", [])[:3]),
                        critical=True, data=data)
        if llm.get("flagged") or llm.get("misleading"):
            status = "warn"
            notes.append("AI incelemesi dikkat gerektiren nokta buldu: " + "; ".join(llm.get("reasons", [])[:2]))
            flags.append({"id": "llm_concern", "severity": "high", "detail": "; ".join(llm.get("reasons", [])[:2])})
    return _chk("content_safety", "İçerik güvenli", status, "; ".join(notes) or "kural ve AI incelemesi temiz", data=data)


def check_copyright(q: QCInput, ctx: dict) -> dict:
    problems, notes = [], []
    prompts = " ".join(sc.get("visual_prompt", "") for sc in q.scenes) + " " + (q.script or {}).get("title", "")
    r = safety.scan_text(prompts + " " + " ".join(sc.get("narration", "") for sc in q.scenes))
    if r["ip"]:
        problems.append("korumalı karakter/marka adı istemlerde: " + ", ".join(r["ip"]))
    for sc in q.scenes:
        if sc.get("origin") == "stock":
            lic = sc.get("license") or {}
            if not lic.get("type") or not lic.get("commercial_use"):
                problems.append(f"sahne {sc['idx'] + 1}: stok lisansı eksik/ticari kullanım belirsiz")
    m = q.music or {}
    if m.get("kind") == "library":
        lic = m.get("license") or {}
        if not (lic.get("type") and lic.get("source") and lic.get("commercial_use")):
            problems.append("müzik: lisans kaydı eksik veya ticari kullanım onaylı değil")
    elif m.get("kind") == "synth":
        notes.append("müzik bu sistemde sentezlendi (telif yok)")
    ai_used = sorted({sc.get("provider", "") for sc in q.scenes if sc.get("origin") in ("ai_video", "ai_image_motion") and sc.get("provider")})
    if ai_used:
        notes.append("AI içerik sağlayıcıları: " + ", ".join(ai_used) + " (sağlayıcı kullanım şartları geçerli)")
    flags = ctx.setdefault("risk_flags", [])
    if r["brands"]:
        flags.append({"id": "brand_mention", "severity": "low", "detail": "marka/ürün adları: " + ", ".join(r["brands"])})
        notes.append("marka adları geçiyor (haber/yorum niteliği dışında kullanılmamalı)")
    if problems:
        return _chk("copyright", "Telif / kullanım hakkı listesi", "fail", "; ".join(problems), critical=True, data={"problems": problems})
    return _chk("copyright", "Telif / kullanım hakkı listesi", "pass", "; ".join(notes) or "tüm varlıkların lisans kaydı tamam", data={"notes": notes})


def check_platform(q: QCInput, ctx: dict) -> dict:
    info = ctx.get("info")
    if not info:
        return _chk("platform_format", "Platform formatı", "fail", "ölçülemedi", critical=True)
    problems, warns = [], []
    vertical = info.height > info.width
    for p in q.platforms:
        lim = PLATFORM_LIMITS.get(p)
        if not lim:
            continue
        if lim.get("vertical_required") and not vertical:
            problems.append(f"{p}: dikey (9:16) video gerekli")
        if p == "youtube" and not vertical and info.width != info.height:
            warns.append("youtube: dikey olmayan video Shorts olarak sınıflanmaz")
        if info.duration > lim["max"]:
            problems.append(f"{p}: süre {info.duration:.0f} sn > {lim['max']} sn")
        if "fps" in lim and not (lim["fps"][0] <= info.fps <= lim["fps"][1]):
            problems.append(f"{p}: fps {info.fps:.0f} desteklenmiyor")
        if "min_side" in lim and min(info.width, info.height) < lim["min_side"]:
            problems.append(f"{p}: çözünürlük çok düşük")
        if "max_bytes" in lim and info.size > lim["max_bytes"]:
            problems.append(f"{p}: dosya çok büyük")
    if info.vcodec != "h264" or info.acodec not in ("aac", ""):
        problems.append(f"codec {info.vcodec}/{info.acodec} (h264/aac bekleniyor)")
    if problems:
        return _chk("platform_format", "Platform formatı", "fail", "; ".join(problems), critical=True)
    if warns:
        return _chk("platform_format", "Platform formatı", "warn", "; ".join(warns))
    return _chk("platform_format", "Platform formatı", "pass", f"{', '.join(q.platforms) or '-'} için uygun ({info.width}x{info.height}, h264/aac)")


def provenance_flags(q: QCInput) -> list[dict]:
    """Dürüstlük kontrolü: içerik gerçekten istenen türde mi üretildi? (puanı etkilemez; otomatik yayını engeller)"""
    flags = []
    n = max(len(q.scenes), 1)
    origins = [sc.get("origin") for sc in q.scenes]
    ai_video = origins.count("ai_video") / n
    procedural = origins.count("procedural") / n
    if not q.script_is_ai:
        flags.append({"id": "template_script", "severity": "high", "detail": "senaryo AI ile değil yerel şablonla üretildi"})
    if not q.expected_voice_is_ai:
        flags.append({"id": "offline_voice", "severity": "high", "detail": "seslendirme yerel robotik sentez (AI ses değil)"})
    if procedural > 0:
        flags.append({"id": "placeholder_visuals", "severity": "high", "detail": f"sahnelerin %{procedural * 100:.0f}'i yer tutucu gradyan"})
    if q.media_mode == "ai_video" and ai_video < 0.8:
        flags.append({"id": "ai_video_shortfall", "severity": "high",
                      "detail": f"'ai_video' modu seçildi ama sahnelerin yalnızca %{ai_video * 100:.0f}'i gerçek AI video"})
    if q.media_mode == "slideshow":
        flags.append({"id": "slideshow", "severity": "low", "detail": "slayt/hareketli görsel modu (AI video değil)"})
    return flags


CHECKS = [check_file_opens, check_duration, check_audio, check_loudness, check_black, check_empty_scenes, check_resolution,
          check_subtitle_sync, check_av_match, check_repeated, check_visual_quality, check_safety, check_copyright, check_platform]


def run_qc(q: QCInput, progress: Callable[[str], None] | None = None) -> dict:
    ctx: dict = {"risk_flags": []}
    results = []
    for fn in CHECKS:
        if progress:
            progress(fn.__name__.replace("check_", ""))
        try:
            results.append(fn(q, ctx))
        except Exception as e:  # noqa: BLE001
            cid = fn.__name__.replace("check_", "")
            results.append(_chk(cid, cid, "fail", f"kontrol hatası: {type(e).__name__}: {str(e)[:150]}",
                                critical=cid in TECHNICAL))
    wsum = sum(r["weight"] for r in results) or 1
    score = round(100 * sum(r["score"] * r["weight"] for r in results) / wsum)
    flags = ctx["risk_flags"] + provenance_flags(q)
    critical = [r for r in results if r["critical"]]
    th = q.thresholds
    high_flags = [f for f in flags if f["severity"] == "high"]
    safety_clean = all(r["status"] == "pass" for r in results if r["id"] in SAFETY_IDS)
    reasons: list[str] = []
    tech_crit = [r for r in critical if r["id"] in TECHNICAL or r["id"] in ("platform_format",)]
    if tech_crit:
        decision = "rejected"
        reasons.append("kritik teknik hata: " + "; ".join(r["name"] for r in tech_crit))
    elif critical:
        decision = "review"
        reasons.append("kritik güvenlik/telif bulgusu: " + "; ".join(r["name"] for r in critical))
    elif score < th["review_min"]:
        decision = "rejected"
        reasons.append(f"puan {score} < {th['review_min']}")
    elif score < th["low_risk_min"]:
        decision = "review"
        reasons.append(f"puan {score} < {th['low_risk_min']}")
    elif high_flags:
        decision = "review"
        reasons.append("yüksek riskli bayrak: " + "; ".join(f["id"] for f in high_flags))
    elif score >= th["auto_publish_min"]:
        decision = "auto_publish"
    elif safety_clean:
        decision = "auto_publish"
        reasons.append("80–89 bandı: güvenlik/telif kontrolleri tamamen temiz olduğu için düşük riskli otomatik yayın")
    else:
        decision = "review"
        reasons.append("80–89 bandı: güvenlik/telif kontrollerinde uyarı var")
    recs = []
    if decision == "rejected":
        recs.append("Videoyu farklı sağlayıcı/ayarlarla yeniden üretin.")
    for r in results:
        if r["status"] != "pass":
            recs.append(f"{r['name']}: {r['detail']}")
    return {"score": score, "decision": decision, "reasons": reasons, "checks": results, "risk_flags": flags,
            "critical": [r["id"] for r in critical], "recommendations": recs[:10], "thresholds": th,
            "measured": {"lufs": ctx.get("lufs"), "mean_volume_db": ctx.get("mean_volume")}}
