"""Kelime hizalama yardımcıları: ASR kelimelerini senaryo metnine eşler (difflib) ve eksikleri enterpole eder."""
from __future__ import annotations

import difflib
import re


def tokenize(text: str) -> list[str]:
    return re.findall(r"\S+", text.strip())


def _norm(w: str) -> str:
    return re.sub(r"[^\wçğıöşüÇĞİÖŞÜ]", "", w.lower().replace("İ", "i").replace("I", "ı"), flags=re.UNICODE)


def align_to_script(script_words: list[str], asr_words: list[dict], start: float, end: float) -> list[dict]:
    """Her senaryo kelimesine zaman ata. Eşleşmeyenler komşu eşleşmeler arasında uzunluk ağırlıklı dağıtılır."""
    n = len(script_words)
    if n == 0:
        return []
    a = [_norm(w) for w in script_words]
    b = [_norm(w["word"]) for w in asr_words]
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    times: list[tuple[float, float] | None] = [None] * n
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            w = asr_words[blk.b + k]
            times[blk.a + k] = (float(w["start"]), float(w["end"]))
    # eşleşmeyen aralıkları doldur
    i = 0
    while i < n:
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < n and times[j] is None:
            j += 1
        left = times[i - 1][1] if i > 0 and times[i - 1] else start
        right = times[j][0] if j < n and times[j] else end
        right = max(right, left + 0.05 * (j - i))
        weights = [max(len(script_words[k]), 1) for k in range(i, j)]
        tot = sum(weights)
        t = left
        for k, wgt in zip(range(i, j), weights):
            d = (right - left) * wgt / tot
            times[k] = (t, t + d)
            t += d
        i = j
    out = []
    prev_end = start
    for w, tm in zip(script_words, times):
        s, e = tm  # type: ignore[misc]
        s = max(s, prev_end - 0.001) if s < prev_end else s
        e = max(e, s + 0.04)
        out.append({"word": w, "start": round(s, 3), "end": round(e, 3)})
        prev_end = e
    return out
