import subprocess, textwrap
from pathlib import Path

def _run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout)[-1800:])

def render_video(script: dict, out: Path, work: Path, duration: int):
    """Render a vertical MP4. Uses AI-generated stills when enabled; otherwise branded motion cards."""
    work.mkdir(parents=True, exist_ok=True)
    scenes = script.get("scenes") or []
    if not scenes:
        raise ValueError("Senaryoda sahne bulunamadı.")
    per_scene = max(3, duration // len(scenes))
    clips = []
    for i, scene in enumerate(scenes):
        img = work / f"scene_{i}.png"
        clip = work / f"clip_{i}.mp4"
        # Fallback scene card is deliberately labeled as a preview, not misrepresented as AI footage.
        if not img.exists():
            title = (scene.get("narration") or script.get("title") or "AI Video Factory").replace("'", "").replace(":", " ")
            title = title[:95]
            _run(["ffmpeg","-y","-f","lavfi","-i",f"color=c=0x101827:s=720x1280:d={per_scene}:r=25",
                  "-vf",f"drawtext=text='{title}':fontcolor=white:fontsize=38:x=(w-text_w)/2:y=(h-text_h)/2:line_spacing=14:box=1:boxcolor=0x26364dcc:boxborderw=28,format=yuv420p",
                  "-an","-c:v","libx264","-preset","veryfast","-t",str(per_scene),str(clip)])
        else:
            _run(["ffmpeg","-y","-loop","1","-i",str(img),"-t",str(per_scene),
                  "-vf","scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,zoompan=z='min(zoom+0.0008,1.12)':d=75:s=720x1280:fps=25,format=yuv420p",
                  "-an","-c:v","libx264","-preset","veryfast",str(clip)])
        clips.append(clip)
    concat = work / "concat.txt"
    concat.write_text("".join(f"file '{p.as_posix()}'\n" for p in clips))
    _run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(concat),"-c","copy","-movflags","+faststart",str(out)])
    return out
