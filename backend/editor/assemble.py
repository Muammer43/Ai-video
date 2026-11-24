"""Sahneleri birleştir: geçişler, ses miksajı (ducking + loudnorm), altyazı, renk, logo, intro/outro, kapak."""
from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..core.config import get_settings
from . import ffmpeg as ff
from . import subtitles as sub

log = logging.getLogger(__name__)

TRANSITIONS = {"fade": "fade", "dissolve": "dissolve", "slide": "slideleft", "slideleft": "slideleft", "slideright": "slideright",
               "wipe": "wipeleft", "wipeleft": "wipeleft", "zoom": "zoomin", "circle": "circleopen", "none": "fade"}
GRADES = {
    "cinematic": "eq=contrast=1.08:saturation=1.08:gamma=0.97,colorbalance=rs=0.04:bs=-0.04,vignette=PI/7",
    "vivid": "eq=contrast=1.05:saturation=1.30",
    "documentary": "eq=contrast=1.04:saturation=0.92",
    "energetic": "eq=contrast=1.10:saturation=1.25:brightness=0.02",
    "minimal": "",
    "none": "",
}
TRANS_DUR = 0.35
LEAD = 0.15  # anlatım, sahne başından bu kadar sonra başlar


def scene_length(narration_s: float) -> float:
    """Sahne süresi = anlatım + baş boşluk + geçiş payı + kuyruk."""
    return round(max(narration_s + LEAD + TRANS_DUR + 0.25, 2.0), 3)


@dataclass
class SceneInput:
    clip: Path  # video (normalize edilecek)
    duration: float
    audio: Path | None = None
    audio_duration: float = 0.0
    words: list[dict] = field(default_factory=list)  # sahne-yerel zamanlar (0'dan)
    transition: str = "fade"


@dataclass
class AssembleOptions:
    aspect_ratio: str = "9:16"
    resolution: str = "720p"
    style: str = "cinematic"
    music: Path | None = None
    music_volume: float = 0.22
    subtitles: bool = True
    logo: Path | None = None
    intro_text: str = ""
    outro_text: str = ""
    title: str = ""
    quality: str = "standard"
    target_lufs: float = -14.0


@dataclass
class AssembleResult:
    video: Path
    srt: Path | None
    ass: Path | None
    cover: Path | None
    duration: float
    timeline: list[dict]  # sahne başlangıç/bitiş zamanları (çıktı zaman çizelgesi)
    loudness: dict
    render_seconds: float
    cues: list[dict] = field(default_factory=list)


def _normalize_clip(src: Path, dst: Path, dur: float, w: int, h: int, cancel: Callable | None, preset: str, crf: int) -> None:
    info = ff.probe(src)
    pre = []
    vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
    if info.duration > 0.05 and info.duration + 0.05 < dur:
        factor = dur / info.duration
        if factor <= 1.6:
            vf = f"setpts={factor:.5f}*PTS," + vf  # yavaşlat
        else:
            pre = ["-stream_loop", "-1"]  # döngü
    vf += f",fps={ff.FPS},format=yuv420p"
    ff.run([*pre, "-i", str(src), "-t", f"{dur:.3f}", "-vf", vf, "-an", "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p", str(dst)], timeout=300, cancel_check=cancel)


def _card(text: str, dst: Path, dur: float, w: int, h: int, work: Path, cancel: Callable | None, preset: str, crf: int) -> None:
    ass = work / f"card_{dst.stem}.ass"
    ass.write_text(sub.build_card_ass(text, w, h, dur), encoding="utf-8")
    s = get_settings()
    vf = f"ass={ass.name}:fontsdir={ff.filter_path(s.font_dir)},format=yuv420p"
    ff.run(["-f", "lavfi", "-i", f"gradients=s={w}x{h}:c0=0x0f172a:c1=0x312e81:x0=0:y0=0:x1={w}:y1={h}:d={dur}:speed=0.02:r={ff.FPS}",
            "-t", f"{dur:.3f}", "-vf", vf, "-an", "-c:v", "libx264", "-preset", preset, "-crf", str(crf), str(dst)],
           timeout=120, cwd=work, cancel_check=cancel)


def loudnorm_measure(path: Path, target: float) -> dict:
    s = get_settings()
    import subprocess
    p = subprocess.run([s.ffmpeg_bin, "-hide_banner", "-nostdin", "-i", str(path), "-af",
                        f"loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=180)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr, re.S)
    if not m:
        raise ff.FFmpegError("loudnorm ölçümü başarısız")
    return json.loads(m.group(0))


def build_audio(scenes: list[SceneInput], starts: list[float], total: float, music: Path | None, music_volume: float,
                work: Path, target: float, cancel: Callable | None) -> tuple[Path, dict]:
    """Anlatım zaman çizelgesine yerleştirilir, müzik konuşma altında kısılır, sonra loudnorm (iki geçiş)."""
    inputs: list[str] = []
    chains: list[str] = []
    idx = 0
    labels = []
    for sc, st in zip(scenes, starts):
        if sc.audio:
            inputs += ["-i", str(sc.audio)]
            ms = int((st + LEAD) * 1000)
            chains.append(f"[{idx}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,adelay={ms}|{ms}[a{idx}]")
            labels.append(f"[a{idx}]")
            idx += 1
    if not labels:
        raise ff.FFmpegError("Hiç anlatım sesi yok")
    chains.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0,apad=whole_dur={total:.3f},atrim=0:{total:.3f}[voice]")
    mixed = work / "mix_raw.wav"
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        chains[-1] = chains[-1].replace("[voice]", "[voice0]")
        chains.append("[voice0]asplit=2[voice][vsc]")
        chains.append(f"[{idx}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=0:{total:.3f},"
                      f"afade=t=in:st=0:d=1.2,afade=t=out:st={max(total - 1.8, 0):.3f}:d=1.8,volume={music_volume}[mus]")
        chains.append("[mus][vsc]sidechaincompress=threshold=0.03:ratio=10:attack=15:release=450:makeup=1[duck]")
        chains.append("[voice][duck]amix=inputs=2:normalize=0:duration=first[out]")
        out_label = "[out]"
    else:
        chains[-1] = chains[-1].replace("[voice]", "[out]")
        out_label = "[out]"
    ff.run([*inputs, "-filter_complex", ";".join(chains), "-map", out_label, "-ar", "44100", "-c:a", "pcm_s16le", str(mixed)],
           timeout=300, cancel_check=cancel)
    m = loudnorm_measure(mixed, target)
    final = work / "mix.wav"
    af = (f"loudnorm=I={target}:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    ff.run(["-i", str(mixed), "-af", af, "-ar", "44100", "-c:a", "pcm_s16le", str(final)], timeout=180, cancel_check=cancel)
    return final, m


def assemble(scenes: list[SceneInput], opt: AssembleOptions, work: Path, out_path: Path,
             cancel: Callable[[], None] | None = None) -> AssembleResult:
    import time
    t0 = time.monotonic()
    s = get_settings()
    work.mkdir(parents=True, exist_ok=True)
    w, h = ff.dims(opt.aspect_ratio, opt.resolution)
    preset, crf = {"draft": ("ultrafast", 26), "standard": ("veryfast", 21), "premium": ("medium", 18)}.get(opt.quality, ("veryfast", 21))

    # 1) sahne klipleri normalize + intro/outro kartları
    items: list[tuple[Path, float, str]] = []  # (dosya, süre, geçiş)
    timeline_meta: list[dict] = []
    extra_before = 0
    if opt.intro_text:
        p = work / "intro.mp4"
        _card(opt.intro_text, p, 2.0, w, h, work, cancel, preset, crf)
        items.append((p, 2.0, "fade"))
        extra_before = 1
    for i, sc in enumerate(scenes):
        p = work / f"norm_{i}.mp4"
        _normalize_clip(sc.clip, p, sc.duration, w, h, cancel, preset, crf)
        items.append((p, sc.duration, TRANSITIONS.get(sc.transition, "fade")))
    if opt.outro_text:
        p = work / "outro.mp4"
        _card(opt.outro_text, p, 2.4, w, h, work, cancel, preset, crf)
        items.append((p, 2.4, "fade"))

    # 2) zaman çizelgesi (xfade örtüşmesi dikkate alınır)
    starts_all: list[float] = []
    t = 0.0
    for k, (_, d, _tr) in enumerate(items):
        starts_all.append(t)
        t += d - TRANS_DUR
    total = sum(d for _, d, _ in items) - TRANS_DUR * (len(items) - 1)
    scene_starts = starts_all[extra_before:extra_before + len(scenes)]
    for i, (sc, st) in enumerate(zip(scenes, scene_starts)):
        timeline_meta.append({"scene": i, "start": round(st, 3), "end": round(st + sc.duration, 3),
                              "narration_start": round(st + LEAD, 3), "narration_end": round(st + LEAD + sc.audio_duration, 3)})

    # 3) ses
    mix, loud = build_audio(scenes, scene_starts, total, opt.music, opt.music_volume, work, opt.target_lufs, cancel)

    # 4) altyazı
    ass_path = srt_path = None
    cue_list: list[dict] = []
    if opt.subtitles:
        words: list[dict] = []
        for sc, st in zip(scenes, scene_starts):
            for wd in sc.words:
                words.append({"word": wd["word"], "start": round(st + LEAD + wd["start"], 3), "end": round(st + LEAD + wd["end"], 3)})
        if words:
            cues = sub.group_cues(words)
            cue_list = [{"start": c.start, "end": c.end, "text": c.text} for c in cues]
            ass_path = work / "subs.ass"
            srt_path = work / "subs.srt"
            ass_path.write_text(sub.build_ass(cues, w, h), encoding="utf-8")
            srt_path.write_text(sub.build_srt(cues), encoding="utf-8")

    # 5) tek geçişte birleştirme
    inputs: list[str] = []
    for p, _, _ in items:
        inputs += ["-i", str(p)]
    n = len(items)
    fc = []
    if n == 1:
        fc.append("[0:v]null[vx]")
    else:
        prev = "[0:v]"
        acc = items[0][1]
        for k in range(1, n):
            off = acc - TRANS_DUR
            lab = f"[vx{k}]" if k < n - 1 else "[vx]"
            fc.append(f"{prev}[{k}:v]xfade=transition={items[k][2]}:duration={TRANS_DUR}:offset={off:.3f}{lab}")
            prev = lab
            acc = off + items[k][1]
    cur = "[vx]"
    grade = GRADES.get(opt.style, "")
    if grade:
        fc.append(f"{cur}{grade}[vg]")
        cur = "[vg]"
    if ass_path:
        fc.append(f"{cur}ass={ass_path.name}:fontsdir={ff.filter_path(s.font_dir)}[vs]")
        cur = "[vs]"
    idx_next = n
    if opt.logo and opt.logo.exists():
        inputs += ["-i", str(opt.logo)]
        fc.append(f"[{idx_next}:v]scale={int(w * 0.14)}:-1,format=rgba,colorchannelmixer=aa=0.8[lg]")
        fc.append(f"{cur}[lg]overlay=W-w-{int(w * 0.04)}:{int(h * 0.04)}[vl]")
        cur = "[vl]"
        idx_next += 1
    fc.append(f"{cur}format=yuv420p[vf]")
    inputs += ["-i", str(mix)]
    ff.run([*inputs, "-filter_complex", ";".join(fc), "-map", "[vf]", "-map", f"{idx_next}:a", "-t", f"{total:.3f}", "-r", str(ff.FPS),
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
            "-ar", "44100", "-movflags", "+faststart", str(out_path)], timeout=1200, cwd=work, cancel_check=cancel)

    # 6) kapak
    cover = None
    try:
        # kapak: altyazısız ilk sahne klibinden
        cover = make_cover(items[extra_before][0], work / "cover.jpg", opt.title, w, h, at=min(0.9, max(items[extra_before][1] - 0.3, 0)), cancel=cancel)
    except Exception:  # noqa: BLE001
        log.exception("kapak üretilemedi")
    return AssembleResult(video=out_path, srt=srt_path, ass=ass_path, cover=cover, duration=total, timeline=timeline_meta,
                          loudness=loud, render_seconds=time.monotonic() - t0, cues=cue_list)


def make_cover(video: Path, dst: Path, title: str, w: int, h: int, at: float = 1.0, cancel=None) -> Path:  # noqa: ANN001
    s = get_settings()
    work = dst.parent
    raw = work / "cover_raw.png"
    ff.run(["-ss", f"{max(at, 0):.2f}", "-i", str(video), "-frames:v", "1", str(raw)], timeout=60, cancel_check=cancel)
    if title:
        ass = work / "cover.ass"
        ass.write_text(sub.build_card_ass(title[:90], w, h, 1.0, max_chars=16 if w < h else 28).replace("\\fad(250,250)", ""),
                       encoding="utf-8")
        vf = f"eq=brightness=-0.12,ass={ass.name}:fontsdir={ff.filter_path(s.font_dir)}"
        ff.run(["-i", raw.name, "-vf", vf, "-frames:v", "1", "-q:v", "3", dst.name], timeout=60, cwd=work, cancel_check=cancel)
    else:
        ff.run(["-i", str(raw), "-frames:v", "1", "-q:v", "3", str(dst)], timeout=60)
    return dst


def cleanup(work: Path, keep: set[str] | None = None) -> None:
    """Geçici dosyaları temizle (nihai çıktılar önce depolamaya yüklenmiş olmalıdır)."""
    shutil.rmtree(work, ignore_errors=True)
