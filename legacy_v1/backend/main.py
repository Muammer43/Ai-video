import json, asyncio
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from .db import init_db, connect
from .schemas import CreateJob, AppSettings
from .services.pipeline import run_job, output_file
from .services.publisher import publish_job

app = FastAPI(title=settings.app_name, version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins.split(","),
                   allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def startup():
    Path(settings.output_dir).mkdir(parents=True, exist_ok=True)
    init_db()

def serialize(row):
    d = dict(row)
    try: d["platforms"] = json.loads(d["platforms"])
    except: d["platforms"] = []
    try: d["script"] = json.loads(d["script"]) if d["script"] else {}
    except: d["script"] = {}
    return d

@app.get("/api/health")
def health():
    return {"ok": True, "app": settings.app_name, "demo_mode": settings.demo_mode,
            "ai_configured": bool(settings.openai_api_key)}

@app.post("/api/jobs")
async def create_job(payload: CreateJob, background: BackgroundTasks):
    now = datetime.now(timezone.utc).isoformat()
    with connect() as c:
        cur = c.execute("""INSERT INTO jobs(topic,category,style,duration,platforms,status,stage,progress,created_at,updated_at)
        VALUES(?,?,?,?,?,'queued','Kuyrukta',0,?,?)""",
        (payload.topic, payload.category, payload.style, payload.duration,
         json.dumps(payload.platforms), now, now))
        job_id = cur.lastrowid
    background.add_task(run_job, job_id)
    return {"id": job_id, "status": "queued"}

@app.get("/api/jobs")
def list_jobs():
    with connect() as c:
        rows = c.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 100").fetchall()
    return [serialize(r) for r in rows]

@app.get("/api/jobs/{job_id}")
def get_job(job_id: int):
    with connect() as c:
        row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row: raise HTTPException(404, "İş bulunamadı")
    return serialize(row)

@app.get("/api/jobs/{job_id}/video")
def get_video(job_id: int):
    with connect() as c:
        row = c.execute("SELECT output_path FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row: raise HTTPException(404, "İş bulunamadı")
    p = output_file(row["output_path"])
    if not p: raise HTTPException(404, "Video henüz hazır değil")
    return FileResponse(p, media_type="video/mp4", filename=f"ai_video_{job_id}.mp4")

@app.post("/api/jobs/{job_id}/publish")
def request_publish(job_id: int):
    with connect() as c:
        row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row: raise HTTPException(404, "İş bulunamadı")
    job = serialize(row)
    if job["quality_score"] < 80: raise HTTPException(400, "Kalite eşiği geçilmedi")
    result = publish_job(job)
    with connect() as c:
        c.execute("UPDATE jobs SET publish_status=?, updated_at=? WHERE id=?",
                  (result["status"], datetime.now(timezone.utc).isoformat(), job_id))
    return result

@app.get("/api/config")
def get_config():
    return {"auto_publish": settings.auto_publish, "quality_threshold": 80,
            "ai_images": settings.use_ai_images, "ai_voice": settings.use_ai_voice,
            "demo_mode": settings.demo_mode}

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
