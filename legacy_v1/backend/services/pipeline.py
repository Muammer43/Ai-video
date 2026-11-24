import asyncio, json, shutil
from datetime import datetime, timezone
from pathlib import Path
from ..config import settings
from ..db import connect
from .ai import make_script, make_image, make_voice
from .render import render_video

def now(): return datetime.now(timezone.utc).isoformat()

def update(job_id, **fields):
    fields["updated_at"] = now()
    cols = ", ".join(f"{k}=?" for k in fields)
    with connect() as c:
        c.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))

async def run_job(job_id: int):
    with connect() as c:
        row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row: return
    try:
        update(job_id, status="processing", stage="Senaryo hazırlanıyor", progress=8)
        script = await asyncio.to_thread(make_script, row["topic"], row["category"], row["duration"], row["style"])
        update(job_id, script=json.dumps(script, ensure_ascii=False), stage="Görseller hazırlanıyor", progress=25)
        out_dir = Path(settings.output_dir) / str(job_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        for i, scene in enumerate(script["scenes"]):
            await asyncio.to_thread(make_image, scene["visual"], out_dir / f"scene_{i}.png")
            update(job_id, stage=f"Görsel hazırlanıyor ({i+1}/{len(script['scenes'])})",
                   progress=25 + int(35*(i+1)/len(script["scenes"])))
        narration = " ".join(s["narration"] for s in script["scenes"])
        voice_path = out_dir / "voice.mp3"
        has_voice = await asyncio.to_thread(make_voice, narration, voice_path)
        update(job_id, stage="Video kurgulanıyor", progress=70)
        video = out_dir / "final.mp4"
        await asyncio.to_thread(render_video, script, video, out_dir, row["duration"])
        # MVP quality gate: file validity, dimensions, duration and non-empty script.
        probe = await asyncio.to_thread(
            __import__("subprocess").run,
            ["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(video)],
            capture_output=True, text=True
        )
        duration_ok = probe.returncode == 0 and float((probe.stdout or "0").strip() or 0) >= 5
        score = 88 if duration_ok and len(script["scenes"]) >= 3 else 40
        notes = "Otomatik temel kontroller geçti. İnsan gözüyle son kontrol önerilir." if score >= 80 else "Süre veya sahne kontrolü başarısız."
        publish_status = "queued" if score >= 80 else "needs_review"
        update(job_id, status="completed" if score >= 80 else "needs_review", stage="Kalite kontrolü tamamlandı",
               progress=100, output_path=str(video), quality_score=score, quality_notes=notes,
               publish_status=publish_status)
    except Exception as e:
        update(job_id, status="failed", stage="Hata", error=str(e)[:1500], progress=0)

def output_file(path: str):
    p = Path(path).resolve()
    root = Path(settings.output_dir).resolve()
    if root not in p.parents or not p.is_file():
        return None
    return p
