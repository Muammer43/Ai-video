"""Müzik: (1) kullanıcının lisans bilgisiyle yüklediği kütüphane, (2) FFmpeg ile sentezlenen telifsiz ambiyans."""
from __future__ import annotations

from pathlib import Path

from . import ffmpeg as ff

MOODS = {
    "calm": [(220.0, 0.5), (277.18, 0.35), (329.63, 0.3)],  # A minör pad
    "epic": [(110.0, 0.5), (164.81, 0.35), (220.0, 0.3), (329.63, 0.2)],
    "upbeat": [(261.63, 0.4), (329.63, 0.35), (392.0, 0.3), (523.25, 0.15)],  # C majör
    "dark": [(98.0, 0.5), (146.83, 0.3), (174.61, 0.3)],
}


def synth_music(dst: Path, duration: float, mood: str = "calm", cancel=None) -> Path:  # noqa: ANN001
    """Telif sorunu olmayan, bu sistemde sentezlenmiş ambiyans (sinüs pad + tremolo + eko). Basit ama gerçek ses dosyasıdır."""
    freqs = MOODS.get(mood, MOODS["calm"])
    d = f"{duration + 2:.2f}"
    inputs, labels = [], []
    for i, (f, a) in enumerate(freqs):
        inputs += ["-f", "lavfi", "-i", f"sine=frequency={f}:sample_rate=44100:duration={d}"]
        labels.append(f"[{i}:a]volume={a}[s{i}]")
    mix = "".join(f"[s{i}]" for i in range(len(freqs))) + f"amix=inputs={len(freqs)}:normalize=0,tremolo=f=0.18:d=0.45," \
        "lowpass=f=1800,aecho=0.8:0.6:700|1100:0.35|0.25,aformat=channel_layouts=stereo[m]"
    ff.run([*inputs, "-filter_complex", ";".join(labels) + ";" + mix, "-map", "[m]", "-c:a", "pcm_s16le", str(dst)],
           timeout=120, cancel_check=cancel)
    return dst
