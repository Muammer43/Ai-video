"""Ana üretim hattı: SCRIPT → STORYBOARD → VOICE → ASSETS → EDIT → QC → (PUBLISH).

Not: spesifikasyondaki sıra ASSETS → VOICE'tur; sahne süreleri seslendirmeden geldiği için burada VOICE, ASSETS'ten ÖNCE çalışır.
Her aşama idempotenttir (çıktısı varsa atlanır) — 'yeniden dene' kaldığı yerden devam eder."""
from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from sqlalchemy import select, update

from ..core.config import get_settings
from ..core.errors import BudgetExceeded, Cancelled, DeadlineExceeded
from ..core.logging import redact
from ..database.session import session_scope
from ..editor import assemble as A
from ..editor import ffmpeg as ff
from ..editor import music as M
from ..models import Asset, MusicTrack, Project, Scene, Status, utcnow
from ..providers import router
from ..providers.base import ImageRequest, STTRequest, TTSRequest, VideoRequest
from ..providers.stt.align import align_to_script, tokenize
from ..quality import QCInput, run_qc
from ..services import assets as assets_svc
from ..services import content, costs
from ..services.estimator import plan_for_scene
from ..services.events import emit, set_fields
from ..services.notifications import notify
from ..services.runtime import budget_guard, make_ctx

log = logging.getLogger(__name__)


class StageFailure(Exception):
    def __init__(self, message: str, code: str = "STAGE_FAILED", retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def claim(project_id: str) -> bool:
    """QUEUED → PROCESSING compare-and-swap. False ise iş başka işçide/bitmiş (aynı işin iki kez koşmasını engeller)."""
    with session_scope() as db:
        r = db.execute(update(Project).where(Project.id == project_id, Project.status == Status.QUEUED, Project.cancel_requested.is_(False))
                       .values(status=Status.PROCESSING, started_at=utcnow(), heartbeat_at=utcnow(), error="", error_code="",
                               attempts=Project.attempts + 1, updated_at=utcnow()))
        return r.rowcount == 1


def _load(project_id: str) -> dict:
    with session_scope() as db:
        p = db.get(Project, project_id)
        return {c.name: getattr(p, c.name) for c in Project.__table__.columns}


def _progress(project_id: str, pct: int, stage: str, msg: str, status: str | None = None, **data) -> None:
    f: dict = {"progress": pct}
    if status:
        f["status"] = status
    emit(project_id, msg, stage=stage, data=data or None, **f)


def run_project(project_id: str) -> dict:
    """Celery görevinin gövdesi. Dönüş: {'status':..., 'retry_in': saniye|None}"""
    if not claim(project_id):
        return {"status": "skipped", "reason": "claim_failed"}
    p = _load(project_id)
    user_id = p["user_id"]
    work = Path(get_settings().work_dir) / project_id
    work.mkdir(parents=True, exist_ok=True)
    t_start = time.monotonic()
    try:
        emit(project_id, f"Üretim başladı (deneme {p['attempts']}/{p['max_attempts']})", stage="TOPIC", progress=2)
        ctx = make_ctx(user_id, project_id, work)
        with session_scope() as db:
            costs.check_budget(db, user_id, 0.0, None, notify_fn=notify)
        ctx.cancel_check()
        stage_script(project_id, ctx)
        stage_storyboard(project_id)
        stage_voice(project_id, ctx)
        stage_assets(project_id, ctx)
        result = stage_edit(project_id, ctx, work)
        outcome = stage_qc(project_id, ctx, result)
        return {"status": outcome, "seconds": round(time.monotonic() - t_start, 1)}
    except Cancelled:
        set_fields(project_id, status=Status.CANCELLED, finished_at=utcnow())
        emit(project_id, "Üretim iptal edildi", level="warning", stage="CANCELLED", status=Status.CANCELLED)
        return {"status": "CANCELLED"}
    except BudgetExceeded as e:
        _fail(project_id, user_id, f"Bütçe sınırı: {e.message}", "BUDGET_EXCEEDED")
        return {"status": "FAILED", "code": "BUDGET_EXCEEDED"}
    except DeadlineExceeded:
        return _fail_or_retry(project_id, user_id, "Proje zaman aşımına uğradı", "TIMEOUT", True)
    except router.ProviderExhausted as e:
        transient = any("geçici" in a["outcome"] or "rate" in a["outcome"] or "zaman aşımı" in a["outcome"] for a in e.attempts)
        return _fail_or_retry(project_id, user_id, str(e), "PROVIDER_EXHAUSTED", transient)
    except StageFailure as e:
        return _fail_or_retry(project_id, user_id, str(e), e.code, e.retryable)
    except ff.FFmpegError as e:
        return _fail_or_retry(project_id, user_id, f"Render hatası: {e}", "RENDER_FAILED", True)
    except Exception as e:  # noqa: BLE001
        log.exception("beklenmeyen pipeline hatası proje=%s", project_id)
        return _fail_or_retry(project_id, user_id, f"{type(e).__name__}: {e}", "INTERNAL", False)
    finally:
        shutil.rmtree(work, ignore_errors=True)  # geçici dosyalar her durumda temizlenir (çıktılar depolamaya yüklendi)


def _fail(project_id: str, user_id: str, msg: str, code: str) -> None:
    emit(project_id, msg, level="error", stage="FAILED", status=Status.FAILED, error=redact(msg)[:2000], error_code=code,
         finished_at=utcnow())
    with session_scope() as db:
        p = db.get(Project, project_id)
        notify(db, user_id, "job_failed", "Video üretimi başarısız", f"{p.topic[:80]}: {redact(msg)[:200]}", level="error",
               data={"project_id": project_id, "code": code})


def _fail_or_retry(project_id: str, user_id: str, msg: str, code: str, retryable: bool) -> dict:
    p = _load(project_id)
    if retryable and p["attempts"] < p["max_attempts"] and not p["cancel_requested"]:
        delay = min(30 * p["attempts"] ** 2, 600)
        emit(project_id, f"Hata: {redact(msg)[:300]} — {delay} sn sonra yeniden denenecek ({p['attempts']}/{p['max_attempts']})",
             level="warning", status=Status.QUEUED, error=redact(msg)[:2000], error_code=code)
        return {"status": "retry", "retry_in": delay}
    _fail(project_id, user_id, msg, code)
    return {"status": "FAILED", "code": code}


# ---------------- aşamalar ----------------
def stage_script(project_id: str, ctx) -> None:
    p = _load(project_id)
    if p["script"]:
        return
    _progress(project_id, 6, "SCRIPT", "Senaryo yazılıyor…")
    opts = p["options"] or {}
    with session_scope() as db:
        from ..services.trends import recent_trends
        trends = [{"title": t.title, "source": t.source, "metrics": t.metrics} for t in recent_trends(db, p["user_id"], p["category"], limit=6)]
    script, provider, is_ai = content.generate_script(ctx, p["user_id"], project_id, topic=p["topic"], category=p["category"],
                                                      language=p["language"], style=p["style"], duration=p["duration_target"],
                                                      options=opts, trends=trends)
    script["_meta"] = {"provider": provider, "is_ai": is_ai}
    set_fields(project_id, script=script)
    _progress(project_id, 15, "SCRIPT", f"Senaryo hazır ({provider})")


def stage_storyboard(project_id: str) -> None:
    p = _load(project_id)
    if not p["storyboard"]:
        sb = content.build_storyboard(p["script"], style=p["style"], aspect_ratio=p["aspect_ratio"], project_id=project_id, language=p["language"])
        set_fields(project_id, storyboard=sb)
        p["storyboard"] = sb
    with session_scope() as db:
        have = {s.idx for s in db.execute(select(Scene).where(Scene.project_id == project_id)).scalars()}
        for i, sc in enumerate(p["script"]["scenes"]):
            if i not in have:
                shot = p["storyboard"]["shots"][i]
                db.add(Scene(project_id=project_id, user_id=p["user_id"], idx=i, narration=sc["narration"],
                             visual_prompt=shot["image_prompt"], shot=shot, status="pending", meta={}))
    _progress(project_id, 18, "STORYBOARD", f"Storyboard hazır ({len(p['script']['scenes'])} sahne)")


def _scenes(project_id: str) -> list[dict]:
    with session_scope() as db:
        rows = db.execute(select(Scene).where(Scene.project_id == project_id).order_by(Scene.idx)).scalars().all()
        return [{c.name: getattr(s, c.name) for c in Scene.__table__.columns} for s in rows]


def _update_scene(scene_id: str, **fields) -> None:
    with session_scope() as db:
        s = db.get(Scene, scene_id)
        for k, v in fields.items():
            setattr(s, k, v)


def stage_voice(project_id: str, ctx) -> None:
    p = _load(project_id)
    scenes = _scenes(project_id)
    prefs = ctx.settings["providers"]
    n = len(scenes)
    for sc in scenes:
        ctx.cancel_check()
        if sc["audio_asset_id"] and sc["meta"].get("words"):
            continue
        _progress(project_id, 18 + int(17 * sc["idx"] / n), "VOICE", f"Sahne {sc['idx'] + 1}/{n} seslendiriliyor…")
        out = router.run("tts", ctx, TTSRequest(text=sc["narration"], language=p["language"], voice=p["voice"] or {}), preferred=prefs["tts"],
                         db_factory=session_scope, guard=budget_guard(p["user_id"], project_id))
        dur = float(out.result.meta.get("duration") or ff.audio_duration(out.result.path))
        with session_scope() as db:
            a = assets_svc.store_asset(db, p["user_id"], project_id, "audio", out.result.path, duration=dur,
                                       meta={"provider": out.provider, "scene": sc["idx"], "ai": router.get("tts", out.provider).is_ai})
            aid = a.id
        words = tokenize(sc["narration"])
        stt = router.run("stt", ctx, STTRequest(audio_path=out.result.path, language=p["language"], text_hint=sc["narration"], duration=dur),
                         preferred=prefs["stt"], db_factory=session_scope, guard=budget_guard(p["user_id"], project_id))
        asr = stt.result.data["words"]
        timed = asr if stt.result.data.get("estimated") else align_to_script(words, asr, 0.0, dur)
        meta = dict(sc["meta"])
        meta.update(words=timed, audio_duration=dur, tts_provider=out.provider, tts_is_ai=router.get("tts", out.provider).is_ai,
                    stt_provider=stt.provider, stt_estimated=bool(stt.result.data.get("estimated")), audio_path_hint=str(out.result.path))
        _update_scene(sc["id"], audio_asset_id=aid, duration=A.scene_length(dur), meta=meta)
    _progress(project_id, 35, "VOICE", "Seslendirme ve kelime zamanlaması hazır")


def _remaining_video_budget(project_id: str, user_id: str) -> float:
    with session_scope() as db:
        st = costs.budget_status(db, user_id)
        p = db.get(Project, project_id)
        return max(st["per_video_usd"] - (p.cost_actual or 0.0), 0.0)


def stage_assets(project_id: str, ctx) -> None:
    p = _load(project_id)
    scenes = _scenes(project_id)
    prefs = ctx.settings["providers"]
    n = len(scenes)
    guard = budget_guard(p["user_id"], project_id)
    ctx.settings["_used_stock_ids"] = []
    report = {"scenes": [], "counts": {}, "providers": {}, "fallbacks": []}
    for sc in scenes:
        ctx.cancel_check()
        pct = 35 + int(35 * sc["idx"] / n)
        if sc["video_asset_id"] and sc["origin"]:
            report["scenes"].append({"idx": sc["idx"], "origin": sc["origin"], "provider": sc["meta"].get("media_provider")})
            continue
        shot = sc["shot"]
        plan = plan_for_scene(p["media_mode"], p["quality_tier"], sc["idx"])
        _progress(project_id, pct, "ASSETS", f"Sahne {sc['idx'] + 1}/{n} görsel üretiliyor ({'/'.join(plan)})…", status=Status.WAITING_PROVIDER)
        sd = ctx.work_dir / f"scene_{sc['idx']}"
        sctx = _sub_ctx(ctx, sd)
        origin, clip, prov, lic, extra, img_path = None, None, "", {}, {}, None
        dur = max(sc["duration"], 2.0)
        attempts_log = []
        for step in plan:
            try:
                if step == "ai_video":
                    img_out = None
                    try:
                        img_out = router.run("image", sctx, ImageRequest(prompt=shot["image_prompt"], aspect_ratio=p["aspect_ratio"],
                                                                        quality=p["quality_tier"], seed=shot["seed"]),
                                             preferred=prefs["image"], only_ai=True, db_factory=session_scope, guard=guard,
                                             max_cost=_remaining_video_budget(project_id, p["user_id"]))
                        img_path = img_out.result.path
                    except router.ProviderExhausted as e:
                        attempts_log += e.attempts
                    vout = router.run("video", sctx, VideoRequest(prompt=shot["video_prompt"], duration=dur, aspect_ratio=p["aspect_ratio"],
                                                                 resolution=p["resolution"], image_path=img_path, quality=p["quality_tier"],
                                                                 seed=shot["seed"], scene_idx=sc["idx"]),
                                      preferred=[x for x in prefs["video"] if x not in ("stock", "ken_burns")], only_ai=True,
                                      db_factory=session_scope, guard=guard, max_cost=_remaining_video_budget(project_id, p["user_id"]))
                    origin, clip, prov, extra = "ai_video", vout.result.path, vout.provider, vout.result.meta
                    break
                if step == "stock":
                    vout = router.run("video", sctx, VideoRequest(prompt=shot["video_prompt"], duration=dur, aspect_ratio=p["aspect_ratio"],
                                                                 resolution=p["resolution"], scene_idx=sc["idx"], stock_query=shot.get("stock_query", ""), category=p["category"]),
                                      preferred=["stock"], db_factory=session_scope, guard=guard)
                    origin, clip, prov, extra = "stock", vout.result.path, "stock", vout.result.meta
                    lic = extra.get("license", {})
                    ctx.settings["_used_stock_ids"].append(extra.get("stock_id"))
                    break
                if step == "image_motion":
                    if img_path is None:
                        img_out = router.run("image", sctx, ImageRequest(prompt=shot["image_prompt"], aspect_ratio=p["aspect_ratio"],
                                                                        quality=p["quality_tier"], seed=shot["seed"]),
                                             preferred=prefs["image"], db_factory=session_scope, guard=guard,
                                             max_cost=_remaining_video_budget(project_id, p["user_id"]))
                        img_path, img_prov = img_out.result.path, img_out.provider
                    else:
                        img_prov = "ai-keyframe"
                    img_is_ai = (router.get("image", img_prov).is_ai if router.get("image", img_prov) else True)
                    vout = router.run("video", sctx, VideoRequest(prompt=shot["video_prompt"], duration=dur, aspect_ratio=p["aspect_ratio"],
                                                                 resolution=p["resolution"], image_path=img_path, scene_idx=sc["idx"]),
                                      preferred=["ken_burns"], db_factory=session_scope)
                    origin = "ai_image_motion" if img_is_ai else "procedural"
                    clip, prov, extra = vout.result.path, img_prov, vout.result.meta
                    break
            except router.ProviderExhausted as e:
                attempts_log += e.attempts
                report["fallbacks"].append({"scene": sc["idx"], "step": step, "reason": [a["outcome"] for a in e.attempts][-3:]})
        if clip is None:
            raise StageFailure(f"Sahne {sc['idx'] + 1} için hiçbir medya üretilemedi: " + "; ".join(a["outcome"] for a in attempts_log[-4:]),
                               "NO_MEDIA", retryable=True)
        with session_scope() as db:
            va = assets_svc.store_asset(db, p["user_id"], project_id, "video", clip, duration=extra.get("duration"),
                                        license=lic, meta={"origin": origin, "provider": prov, "scene": sc["idx"]})
            ia = assets_svc.store_asset(db, p["user_id"], project_id, "image", img_path, meta={"scene": sc["idx"], "provider": prov}) if img_path else None
            vid, iid = va.id, (ia.id if ia else None)
        meta = dict(sc["meta"])
        meta.update(media_provider=prov, media_meta={k: v for k, v in extra.items() if k in ("model", "resolution", "duration", "stock_id", "motion")},
                    clip_path_hint=str(clip))
        _update_scene(sc["id"], video_asset_id=vid, image_asset_id=iid, origin=origin, status="ready", meta=meta)
        report["scenes"].append({"idx": sc["idx"], "origin": origin, "provider": prov})
        set_fields(project_id, status=Status.PROCESSING)
    origins = [s["origin"] for s in report["scenes"]]
    report["counts"] = {o: origins.count(o) for o in set(origins)}
    report["ai_video_ratio"] = round(origins.count("ai_video") / max(len(origins), 1), 3)
    report["providers"] = {s["provider"]: 0 for s in report["scenes"] if s.get("provider")}
    set_fields(project_id, media_report=report)
    _progress(project_id, 70, "ASSETS", "Sahne medyaları hazır: " + ", ".join(f"{k}×{v}" for k, v in report["counts"].items()))


def _sub_ctx(ctx, sub: Path):
    from copy import copy
    c = copy(ctx)
    c.work_dir = sub
    sub.mkdir(parents=True, exist_ok=True)
    return c


def _pick_music(project_id: str, user_id: str, opts: dict, total: float, work: Path, mood: str):
    """Kullanıcı kütüphanesinde ticari kullanım onaylı müzik varsa onu, yoksa sentezlenmiş ambiyansı kullan."""
    if opts.get("music") is False:
        return None, {"kind": "none"}
    with session_scope() as db:
        tr = db.execute(select(MusicTrack).where(MusicTrack.user_id == user_id, MusicTrack.commercial_use.is_(True))
                        .order_by(MusicTrack.created_at.desc())).scalars().all()
        sel = next((t for t in tr if t.mood == mood), None) or (tr[0] if tr else None)
        if sel:
            path = assets_svc.local_copy(db, sel.asset_id, work)
            return path, {"kind": "library", "license": {"type": sel.license_type, "source": sel.license_source,
                                                         "attribution": sel.attribution, "commercial_use": sel.commercial_use}}
    path = M.synth_music(work / "music_synth.wav", total + 2, mood)
    return path, {"kind": "synth", "license": {"type": "generated", "source": "AI Video Factory (FFmpeg sentezi)", "commercial_use": True}}


def stage_edit(project_id: str, ctx, work: Path) -> dict:
    p = _load(project_id)
    scenes = _scenes(project_id)
    _progress(project_id, 72, "EDIT", "Kurgu ve render başlıyor…", status=Status.RENDERING)
    opts = p["options"] or {}
    inputs = []
    with session_scope() as db:
        for sc in scenes:
            clip = assets_svc.local_copy(db, sc["video_asset_id"], work)
            audio = assets_svc.local_copy(db, sc["audio_asset_id"], work)
            inputs.append(A.SceneInput(clip=clip, duration=sc["duration"], audio=audio, audio_duration=sc["meta"]["audio_duration"],
                                       words=sc["meta"]["words"], transition=sc["shot"].get("transition", "fade")))
    total_est = sum(i.duration for i in inputs)
    mood = opts.get("music_mood") or {"cinematic": "epic", "documentary": "calm", "energetic": "upbeat", "minimal": "calm"}.get(p["style"], "calm")
    music_path, music_meta = _pick_music(project_id, p["user_id"], opts, total_est, work, mood)
    brand = {}
    if p["channel_id"]:
        from ..models import Channel
        with session_scope() as db:
            ch = db.get(Channel, p["channel_id"])
            brand = (ch.brand or {}) if ch else {}
    logo = None
    if brand.get("logo_asset_id") and opts.get("watermark", True):
        with session_scope() as db:
            try:
                logo = assets_svc.local_copy(db, brand["logo_asset_id"], work)
            except FileNotFoundError:
                logo = None
    ao = A.AssembleOptions(aspect_ratio=p["aspect_ratio"], resolution=p["resolution"], style=p["style"], music=music_path,
                           subtitles=opts.get("subtitles", True), logo=logo, intro_text=brand.get("intro_text", "") if opts.get("intro", True) else "",
                           outro_text=brand.get("outro_text", "") if opts.get("outro", True) else "", title=p["script"].get("title", p["topic"]) if opts.get("cover_style", "title") != "none" else "",
                           quality=p["quality_tier"])
    out = work / "final.mp4"
    res = A.assemble(inputs, ao, work / "asm", out, cancel=ctx.cancel_check)
    info = ff.probe(out)
    with session_scope() as db:
        fa = assets_svc.store_asset(db, p["user_id"], project_id, "final", out, duration=info.duration,
                                    meta={"loudness": res.loudness, "width": info.width, "height": info.height, "render_seconds": round(res.render_seconds, 1)})
        ta = assets_svc.store_asset(db, p["user_id"], project_id, "thumbnail", res.cover) if res.cover else None
        if res.srt:
            assets_svc.store_asset(db, p["user_id"], project_id, "subtitle", res.srt)
        if res.ass:
            assets_svc.store_asset(db, p["user_id"], project_id, "subtitle", res.ass)
        costs.server_cost_entries(db, p["user_id"], project_id, res.render_seconds, info.size)
        fid, tid = fa.id, (ta.id if ta else None)
    set_fields(project_id, final_asset_id=fid, thumbnail_asset_id=tid)
    _progress(project_id, 88, "EDIT", f"Render tamam ({info.duration:.1f} sn, {info.width}x{info.height})", status=Status.RENDERING)
    return {"video": out, "result": res, "music": music_meta, "work": work}


def stage_qc(project_id: str, ctx, edit: dict) -> str:
    p = _load(project_id)
    scenes = _scenes(project_id)
    _progress(project_id, 90, "QC", "Kalite kontrolü çalışıyor…", status=Status.QUALITY_CHECK)
    res = edit["result"]
    with session_scope() as db:
        st = costs.budget_status(db, p["user_id"])  # noqa: F841
        from ..services.usersettings import get_user_settings
        th = get_user_settings(db, p["user_id"])["quality"]
        lic, audio_local = {}, {}
        for s in scenes:
            a = db.get(Asset, s["video_asset_id"])
            lic[s["idx"]] = a.license if a else {}
            audio_local[s["idx"]] = str(assets_svc.local_copy(db, s["audio_asset_id"], edit["work"]))
    qscenes = []
    for s in scenes:
        qscenes.append({"idx": s["idx"], "narration": s["narration"], "visual_prompt": s["visual_prompt"], "origin": s["origin"],
                        "audio_path": audio_local.get(s["idx"]),
                        "audio_duration": s["meta"]["audio_duration"], "license": lic.get(s["idx"], {}), "provider": s["meta"].get("media_provider")})
    # ses dosyaları iş dizininde duruyor (temizlenmeden önce)
    script_meta = p["script"].get("_meta", {})
    tts_is_ai = all(s["meta"].get("tts_is_ai", True) for s in scenes)
    qi = QCInput(video=edit["video"], work=edit["work"], aspect_ratio=p["aspect_ratio"], resolution=p["resolution"],
                 duration_target=p["duration_target"], platforms=p["platforms"] or ["youtube"], scenes=qscenes, timeline=res.timeline, cues=res.cues,
                 script=p["script"], media_mode=p["media_mode"], media_report=p["media_report"], music=edit["music"], category=p["category"],
                 expected_voice_is_ai=tts_is_ai, script_is_ai=script_meta.get("is_ai", True),
                 has_subtitles=bool((p["options"] or {}).get("subtitles", True)),
                 safety_llm=content.safety_review_fn(ctx, p["user_id"], project_id), thresholds=th)
    report = run_qc(qi, progress=lambda name: ctx.cancel_check())
    decision, score = report["decision"], report["score"]
    set_fields(project_id, quality_score=score, qc_decision=decision, quality_report=report)
    emit(project_id, f"Kalite puanı {score}/100 — karar: {decision}", stage="QC", data={"score": score, "decision": decision})
    return _finalize(project_id, p, decision, score, report)


def _finalize(project_id: str, p: dict, decision: str, score: int, report: dict) -> str:
    user_id = p["user_id"]
    if decision == "rejected":
        set_fields(project_id, status=Status.FAILED, error="Kalite kontrolü reddetti: " + "; ".join(report["reasons"]),
                   error_code="QC_REJECTED", finished_at=utcnow(), progress=100)
        emit(project_id, "Kalite kontrolü videoyu reddetti — yeniden üretim önerilir", level="error", stage="QC", status=Status.FAILED)
        with session_scope() as db:
            notify(db, user_id, "job_failed", "Video kalite kontrolünü geçemedi", f"{p['topic'][:80]} — puan {score}", level="error",
                   data={"project_id": project_id})
        return Status.FAILED
    if decision == "review" or p["publish_mode"] == "manual":
        set_fields(project_id, status=Status.NEEDS_REVIEW, finished_at=utcnow(), progress=100)
        emit(project_id, "Kullanıcı incelemesi bekleniyor: " + ("; ".join(report["reasons"]) or "manuel yayın modu"), level="warning",
             stage="QC", status=Status.NEEDS_REVIEW)
        with session_scope() as db:
            notify(db, user_id, "needs_review", "Video incelemenizi bekliyor", f"{p['topic'][:80]} — puan {score}", level="warning",
                   data={"project_id": project_id})
        return Status.NEEDS_REVIEW
    # otomatik yayın kararı
    set_fields(project_id, status=Status.APPROVED, finished_at=utcnow(), progress=96)
    emit(project_id, "Kalite eşiği geçildi — yayın kuyruğuna alınıyor", stage="PUBLISH", status=Status.APPROVED)
    from ..services.publishing import enqueue_publications
    n = enqueue_publications(project_id)
    if n == 0:
        emit(project_id, "Yayın için bağlı hesap yok: video onaylandı fakat yayınlanmadı. Entegrasyonlar'dan hesap bağlayın.", level="warning",
             stage="PUBLISH", status=Status.APPROVED, progress=100)
        with session_scope() as db:
            notify(db, user_id, "job_done", "Video hazır (yayın hesabı bağlı değil)", p["topic"][:100], data={"project_id": project_id})
    return Status.APPROVED if n == 0 else Status.PUBLISHING
