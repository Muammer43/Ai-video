"""Kelime zamanlı altyazı: ASS (karaoke vurgulu) ve SRT çıktısı, otomatik satır kırma, Türkçe karakter desteği."""
from __future__ import annotations

from dataclasses import dataclass

from ..core.config import get_settings
from .ffmpeg import ass_escape


@dataclass
class Cue:
    start: float
    end: float
    words: list[dict]  # {"word","start","end"}

    @property
    def text(self) -> str:
        return " ".join(w["word"] for w in self.words)


def group_cues(words: list[dict], max_chars_line: int = 24, max_lines: int = 2, max_words: int = 7,
               max_dur: float = 3.2) -> list[Cue]:
    """Kelimeleri okunabilir altyazı gruplarına böl (cümle sonu, uzunluk, süre ve duraklamaya göre)."""
    cues: list[Cue] = []
    cur: list[dict] = []
    for w in words:
        if cur:
            chars = sum(len(x["word"]) + 1 for x in cur) + len(w["word"])
            gap = w["start"] - cur[-1]["end"]
            if (chars > max_chars_line * max_lines or len(cur) >= max_words or w["end"] - cur[0]["start"] > max_dur or gap > 0.6
                    or cur[-1]["word"][-1:] in ".!?"):
                cues.append(Cue(cur[0]["start"], cur[-1]["end"], cur))
                cur = []
        cur.append(w)
    if cur:
        cues.append(Cue(cur[0]["start"], cur[-1]["end"], cur))
    # kısa hayaletleri sonrakiyle sabitle: bir sonraki cue başlamadan önce kaybolmasın
    for a, b in zip(cues, cues[1:]):
        a.end = min(max(a.end, a.start + 0.3), b.start) if b.start > a.start else a.end
    return cues


def wrap_lines(text_words: list[str], max_chars: int) -> list[list[int]]:
    """Kelime indekslerini satırlara böl (greedy)."""
    lines: list[list[int]] = [[]]
    n = 0
    for i, w in enumerate(text_words):
        add = len(w) + (1 if lines[-1] else 0)
        if lines[-1] and n + add > max_chars:
            lines.append([])
            n = 0
            add = len(w)
        lines[-1].append(i)
        n += add
    return lines


def ts_ass(t: float) -> str:
    t = max(t, 0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def ts_srt(t: float) -> str:
    t = max(t, 0)
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(cues: list[Cue], max_chars: int = 24) -> str:
    out = []
    for i, c in enumerate(cues, 1):
        words = [w["word"] for w in c.words]
        lines = wrap_lines(words, max_chars)
        txt = "\n".join(" ".join(words[j] for j in ln) for ln in lines)
        out.append(f"{i}\n{ts_srt(c.start)} --> {ts_srt(c.end)}\n{txt}\n")
    return "\n".join(out)


def ass_header(w: int, h: int, *, font: str | None = None, size: int | None = None, margin_v: int | None = None,
               highlight: str = "&H0000E5FF", base: str = "&H00FFFFFF") -> str:
    s = get_settings()
    font = font or s.font_name
    size = size or int(h / 24 if w < h else h / 17)
    margin_v = margin_v if margin_v is not None else int(h * 0.17)
    return (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 2\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {w}\nPlayResY: {h}\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
        "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},{size},{highlight},{base},&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{max(size // 12, 2)},1,2,"
        f"{int(w * 0.07)},{int(w * 0.07)},{margin_v},1\n"
        f"Style: Title,{font},{int(size * 1.5)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,{max(size // 8, 3)},2,5,"
        f"{int(w * 0.08)},{int(w * 0.08)},0,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def build_ass(cues: list[Cue], w: int, h: int, max_chars: int = 24, **style) -> str:
    out = [ass_header(w, h, **style)]
    for c in cues:
        words = [ass_escape(x["word"]) for x in c.words]
        lines = wrap_lines(words, max_chars)
        parts = []
        for li, ln in enumerate(lines):
            seg = []
            for j in ln:
                wd = c.words[j]
                cs = max(int(round((wd["end"] - wd["start"]) * 100)), 1)
                seg.append(f"{{\\k{cs}}}{words[j]}")
            parts.append(" ".join(seg))
        text = "\\N".join(parts)
        out.append(f"Dialogue: 0,{ts_ass(c.start)},{ts_ass(c.end)},Default,,0,0,0,,{text}\n")
    return "".join(out)


def build_card_ass(text: str, w: int, h: int, duration: float, max_chars: int = 18) -> str:
    import textwrap
    lines = textwrap.wrap(ass_escape(text), width=max_chars) or [""]
    body = "\\N".join(lines)
    return ass_header(w, h) + f"Dialogue: 0,{ts_ass(0)},{ts_ass(duration)},Title,,0,0,0,,{{\\fad(250,250)}}{body}\n"
