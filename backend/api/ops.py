from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..analytics import learning
from ..analytics.collector import collect_all
from ..core.config import get_settings
from ..core.deps import audit, current_user
from ..core.errors import AppError, NotFound
from ..database.session import get_db
from ..editor import ffmpeg as ff
from ..models import (Asset, CostEntry, DeviceToken, Experiment, MusicTrack, Notification, ProviderCredential, ProviderStat, SocialAccount, User)
from ..providers import http as H
from ..providers import pricing, router as prouter
from ..providers.base import CallContext, ProviderError
from ..providers.publishing.base import get_publisher
from ..schemas.api import BudgetIn, CredentialIn, DeviceIn, ExperimentIn, PreferencesIn, QualityIn
from ..services import assets as assets_svc
from ..services import costs, dashboard, oauth, system
from ..services.credentials import KNOWN_PROVIDERS, CredentialResolver, delete_credential, set_credential
from ..services.usersettings import get_user_settings, update_user_settings

router = APIRouter(tags=["ops"])
public_router = APIRouter(tags=["public"])


@router.get("/dashboard")
def dashboard_get(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return dashboard.build(db, user.id)


@router.get("/system/status")
def system_status(user: User = Depends(current_user)):
    return system.status()


# ---------- analiz ----------
@router.get("/analytics/insights")
def analytics_insights(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return learning.learning_insights(db, user.id)


@router.get("/analytics/overview")
def analytics_overview(db: Session = Depends(get_db), user: User = Depends(current_user)):
    d = dashboard.build(db, user.id)
    rows = learning.performance_rows(db, user.id)
    top = sorted(rows, key=lambda r: -r["score"])[:5]
    return {"published_videos": d["published_videos"], "total_views": d["total_views"], "engagement_rate": d["engagement_rate"], "series": d["series"],
            "measured_videos": len(rows), "top_videos": [{"project_id": r["project_id"], "platform": r["platform"], "category": r["category"], "metric": r["metric"],
                                                         "score": round(r["score"], 4), "views": r["views"]} for r in top], "note": d["metrics_note"]}


@router.post("/analytics/collect", status_code=202)
def analytics_collect(user: User = Depends(current_user)):
    return collect_all()


@router.get("/analytics/experiments")
def experiments(db: Session = Depends(get_db), user: User = Depends(current_user)):
    out = []
    for ex in db.execute(select(Experiment).where(Experiment.user_id == user.id).order_by(desc(Experiment.created_at))).scalars():
        res = ex.result if ex.status != "running" else learning.evaluate_experiment(db, ex)
        out.append({"id": ex.id, "kind": ex.kind, "status": ex.status, "variants": ex.variants, "metric": ex.metric, "min_views_per_variant": ex.min_views_per_variant,
                    "result": res, "created_at": ex.created_at.isoformat()})
    return out


@router.post("/analytics/experiments", status_code=201)
def experiment_create(body: ExperimentIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ex = learning.create_experiment(db, user.id, body.kind, body.channel_id, body.min_views_per_variant)
    audit(db, request, user.id, "experiment.create", "experiment", ex.id)
    return {"id": ex.id, "kind": ex.kind, "variants": ex.variants}


@router.delete("/analytics/experiments/{eid}")
def experiment_stop(eid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ex = db.get(Experiment, eid)
    if ex is None or ex.user_id != user.id:
        raise NotFound("Deney bulunamadı")
    ex.status = "inconclusive" if ex.status == "running" else ex.status
    db.commit()
    return {"ok": True}


# ---------- sağlayıcılar ----------
def _prov_stats(db: Session, user_id: str) -> dict:
    return {(s.provider, s.kind): s for s in db.execute(select(ProviderStat).where(ProviderStat.user_id == user_id)).scalars()}


@router.get("/providers")
def providers(db: Session = Depends(get_db), user: User = Depends(current_user)):
    cr = CredentialResolver(db, user.id)
    ctx = CallContext(user_id=user.id, project_id=None, creds=cr, work_dir=Path("."))
    stats = _prov_stats(db, user.id)
    creds = {c.provider: c for c in db.execute(select(ProviderCredential).where(ProviderCredential.user_id == user.id)).scalars()}
    st = get_user_settings(db, user.id)
    out = []
    for p in prouter.all_providers():
        s = stats.get((p.name, p.kind))
        c = creds.get(p.cred_name or "")
        out.append({**p.info(), "configured": p.is_configured(ctx), "credential_hint": c.hint if c else None, "key_source": "kullanıcı" if c else ("sunucu" if cr.has(p.cred_name or "") else None),
                    "needs_key": p.cred_name, "calls": s.calls if s else 0, "success_rate": round(s.successes / s.calls, 3) if s and s.calls else None,
                    "avg_latency_s": round(s.total_latency_s / s.calls, 2) if s and s.calls else None, "total_cost_usd": round(s.total_cost_usd, 4) if s else 0,
                    "avg_cost_usd": round(s.total_cost_usd / s.successes, 4) if s and s.successes else None, "rate_limited": s.rate_limited if s else 0,
                    "last_error": s.last_error if s else "", "last_meta": s.last_meta if s else {},
                    "last_success_at": s.last_success_at.isoformat() if s and s.last_success_at else None})
    return {"providers": out, "preferences": st["providers"], "offline_allowed": get_settings().allow_offline_providers,
            "pricing_as_of": pricing.AS_OF, "pricing_note": "Fiyat tablosu tahmindir; 'price_verified=false' kalemler doğrulanmamıştır (PRICING_OVERRIDES_JSON ile ezilebilir)."}


@router.put("/providers/preferences")
def provider_prefs(body: PreferencesIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    patch = {}
    for kind, names in body.model_dump(exclude_none=True).items():
        valid = {p.name for p in prouter.all_providers() if p.kind == kind}
        bad = [n for n in names if n not in valid]
        if bad:
            raise AppError(f"{kind} için bilinmeyen sağlayıcı: {bad}", code="bad_provider", status_code=422)
        patch[kind] = names
    res = update_user_settings(db, user.id, {"providers": patch})
    audit(db, request, user.id, "providers.preferences")
    return res["providers"]


@router.put("/providers/{name}/credential")
def provider_cred_set(name: str, body: CredentialIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if name not in KNOWN_PROVIDERS and name != "youtube_data":
        raise AppError("Bilinmeyen sağlayıcı", code="bad_provider", status_code=422)
    row = set_credential(db, user.id, name, body.secret.strip())
    audit(db, request, user.id, "provider.credential_set", "provider", name)  # değer loglanmaz
    return {"provider": name, "hint": row.hint}


@router.delete("/providers/{name}/credential")
def provider_cred_del(name: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ok = delete_credential(db, user.id, name)
    audit(db, request, user.id, "provider.credential_delete", "provider", name)
    return {"deleted": ok}


TESTS = {
    "openai": ("GET", "https://api.openai.com/v1/models", lambda k: {"Authorization": f"Bearer {k}"}),
    "anthropic": ("GET", "https://api.anthropic.com/v1/models", lambda k: {"x-api-key": k, "anthropic-version": "2023-06-01"}),
    "elevenlabs": ("GET", "https://api.elevenlabs.io/v1/user", lambda k: {"xi-api-key": k}),
    "pexels": ("GET", "https://api.pexels.com/v1/videos/search?query=sea&per_page=1", lambda k: {"Authorization": k}),
}


@router.post("/providers/{name}/test")
def provider_test(name: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    cr = CredentialResolver(db, user.id)
    if not cr.has(name):
        return {"ok": False, "detail": "Anahtar tanımlı değil"}
    if name not in TESTS:
        return {"ok": None, "detail": "Bu sağlayıcı için ücretsiz/zararsız doğrulama uç noktası yok; anahtar yalnızca ilk gerçek üretimde sınanır."}
    method, url, hdr = TESTS[name]
    try:
        with H.client(15) as c:
            H.request(c, method, url, name, headers=hdr(cr.get(name)))
        return {"ok": True, "detail": "Anahtar kabul edildi"}
    except ProviderError as e:
        return {"ok": False, "detail": str(e)[:200]}


# ---------- entegrasyonlar ----------
@router.get("/integrations")
def integrations(db: Session = Depends(get_db), user: User = Depends(current_user)):
    accts = db.execute(select(SocialAccount).where(SocialAccount.user_id == user.id, SocialAccount.status != "disconnected")).scalars().all()
    out = []
    for plat in ("youtube", "tiktok", "instagram"):
        p = get_publisher(plat)
        out.append({"platform": plat, "label": p.label, "oauth_configured": p.configured(), "config_hint": "" if p.configured() else p.config_hint(),
                    "requirements": p.requirements,
                    "accounts": [{"id": a.id, "display_name": a.display_name, "account_type": a.account_type, "status": a.status, "capabilities": a.capabilities,
                                  "token_expires_at": a.token_expires_at.isoformat() if a.token_expires_at else None, "last_error": a.last_error}
                                 for a in accts if a.platform == plat]})
    s = get_settings()
    return {"platforms": out, "public_base_url": s.public_base_url, "https": s.public_base_url.startswith("https://")}


@router.post("/integrations/{platform}/authorize")
def integration_authorize(platform: str, request: Request, channel_id: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    audit(db, request, user.id, "integration.authorize", "platform", platform)
    return oauth.start_authorize(user.id, platform, channel_id)


@router.delete("/integrations/accounts/{aid}")
def integration_disconnect(aid: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    oauth.disconnect(db, user.id, aid)
    audit(db, request, user.id, "integration.disconnect", "account", aid)
    return {"ok": True}


@public_router.get("/oauth/{platform}/callback", response_class=HTMLResponse, include_in_schema=False)
def oauth_callback(platform: str, request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
                   error_description: str | None = None, db: Session = Depends(get_db)):
    deep = get_settings().android_deep_link
    if error or not code or not state:
        msg = (error_description or error or "yetki verilmedi")[:200]
        return HTMLResponse(_oauth_page(False, platform, msg, f"{deep}?ok=0&platform={platform}"), status_code=400)
    try:
        acc = oauth.handle_callback(db, platform, code, state)
    except (AppError, ProviderError) as e:
        return HTMLResponse(_oauth_page(False, platform, str(e)[:200], f"{deep}?ok=0&platform={platform}"), status_code=400)
    audit(db, request, acc.user_id, "integration.connected", "account", acc.id, platform=platform)
    return HTMLResponse(_oauth_page(True, platform, acc.display_name, f"{deep}?ok=1&platform={platform}"))


def _oauth_page(ok: bool, platform: str, detail: str, deep: str) -> str:
    import html
    return (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Hesap bağlama</title>"
            f"<body style='font-family:system-ui;background:#0b1120;color:#eef;padding:32px;text-align:center'>"
            f"<h2>{'✅ Hesap bağlandı' if ok else '❌ Bağlanamadı'}</h2><p>{html.escape(platform)} — {html.escape(detail)}</p>"
            f"<p><a style='color:#8fb0ff' href='{html.escape(deep)}'>Uygulamaya dön</a></p></body>")


# ---------- maliyet ----------
@router.get("/costs/summary")
def cost_summary(days: int = Query(default=30, ge=1, le=365), db: Session = Depends(get_db), user: User = Depends(current_user)):
    return {**costs.summary(db, user.id, days), "budget": costs.budget_status(db, user.id)}


@router.get("/costs/ledger")
def cost_ledger(limit: int = Query(default=50, ge=1, le=200), project_id: str | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = select(CostEntry).where(CostEntry.user_id == user.id)
    if project_id:
        q = q.where(CostEntry.project_id == project_id)
    return [{"id": e.id, "project_id": e.project_id, "provider": e.provider, "kind": e.kind, "units": e.units, "unit_name": e.unit_name, "cost_usd": e.cost_usd,
             "estimated": e.estimated, "note": e.note, "created_at": e.created_at.isoformat()} for e in db.execute(q.order_by(desc(CostEntry.id)).limit(limit)).scalars()]


@router.get("/costs/budget")
def budget_get(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return costs.budget_status(db, user.id)


@router.put("/costs/budget")
def budget_put(body: BudgetIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    update_user_settings(db, user.id, {"budget": body.model_dump(exclude_none=True)})
    audit(db, request, user.id, "budget.update", **body.model_dump(exclude_none=True))
    return costs.budget_status(db, user.id)


@router.post("/costs/resume")
def budget_resume(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    st = costs.budget_status(db, user.id)
    if st["spent_today_usd"] >= st["daily_usd"] or st["spent_month_usd"] >= st["monthly_usd"]:
        raise AppError("Bütçe hâlâ aşılmış durumda; önce günlük/aylık sınırı artırın.", code="budget_still_exceeded", status_code=409)
    update_user_settings(db, user.id, {"budget": {"paused": False, "paused_reason": ""}})
    audit(db, request, user.id, "budget.resume")
    return costs.budget_status(db, user.id)


# ---------- bildirimler ----------
@router.get("/notifications")
def notifications(unread: bool = False, limit: int = Query(default=50, ge=1, le=200), after: str | None = None, db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    q = select(Notification).where(Notification.user_id == user.id)
    if unread:
        q = q.where(Notification.read_at.is_(None))
    rows = db.execute(q.order_by(desc(Notification.created_at)).limit(limit)).scalars().all()
    n_unread = db.execute(select(Notification.id).where(Notification.user_id == user.id, Notification.read_at.is_(None))).all()
    return {"unread": len(n_unread), "items": [{"id": n.id, "kind": n.kind, "level": n.level, "title": n.title, "body": n.body, "data": n.data,
                                                "read": bool(n.read_at), "push_status": n.push_status, "created_at": n.created_at.isoformat()} for n in rows]}


@router.post("/notifications/read")
def notifications_read(db: Session = Depends(get_db), user: User = Depends(current_user)):
    from ..models import utcnow
    for n in db.execute(select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))).scalars():
        n.read_at = utcnow()
    db.commit()
    return {"ok": True}


@router.post("/devices", status_code=201)
def device_register(body: DeviceIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ex = db.execute(select(DeviceToken).where(DeviceToken.token == body.token)).scalar_one_or_none()
    if ex:
        ex.user_id = user.id
    else:
        db.add(DeviceToken(user_id=user.id, token=body.token, platform=body.platform))
    db.commit()
    return {"ok": True}


# ---------- ayarlar / müzik ----------
@router.get("/settings")
def settings_get(db: Session = Depends(get_db), user: User = Depends(current_user)):
    s = get_user_settings(db, user.id)
    cfg = get_settings()
    return {"quality": s["quality"], "preferences": s["preferences"], "automation": s["automation"], "budget": s["budget"],
            "server": {"offline_providers_allowed": cfg.allow_offline_providers, "registration_open": cfg.allow_registration, "https": cfg.public_base_url.startswith("https://")}}


@router.put("/settings/quality")
def settings_quality(body: QualityIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    update_user_settings(db, user.id, {"quality": body.model_dump()})
    audit(db, request, user.id, "settings.quality")
    return body.model_dump()


ALLOWED_AUDIO = {b"ID3", b"RIFF", b"fLaC", b"OggS"}


@router.get("/music")
def music_list(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [{"id": t.id, "title": t.title, "mood": t.mood, "license_type": t.license_type, "license_source": t.license_source, "attribution": t.attribution,
             "commercial_use": t.commercial_use, "created_at": t.created_at.isoformat()}
            for t in db.execute(select(MusicTrack).where(MusicTrack.user_id == user.id).order_by(desc(MusicTrack.created_at))).scalars()]


@router.post("/music", status_code=201)
async def music_upload(request: Request, file: UploadFile = File(...), title: str = Form(max_length=200), mood: str = Form(default="calm", max_length=40),
                       license_type: str = Form(max_length=60), license_source: str = Form(max_length=300), attribution: str = Form(default="", max_length=300),
                       commercial_use: bool = Form(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Kullanıcı kütüphanesine müzik: lisans türü/kaynağı ve ticari kullanım beyanı ZORUNLU (telif kontrol listesi bunu kullanır)."""
    if not commercial_use:
        raise AppError("Ticari kullanıma uygun olduğunu beyan edemediğiniz müzik yüklenemez", code="license_required", status_code=422)
    data = await file.read(25 * 1024 * 1024 + 1)
    if len(data) > 25 * 1024 * 1024:
        raise AppError("Dosya en fazla 25 MB olabilir", code="file_too_large", status_code=413)
    head = data[:4]
    if not (head[:3] == b"ID3" or head[:4] in (b"RIFF", b"fLaC", b"OggS") or (len(data) > 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0) or data[4:8] == b"ftyp"):
        raise AppError("Desteklenmeyen dosya türü (mp3/wav/flac/ogg/m4a)", code="bad_file_type", status_code=415)
    with tempfile.TemporaryDirectory() as td:
        ext = {b"RIFF": ".wav", b"fLaC": ".flac", b"OggS": ".ogg"}.get(head[:4], ".m4a" if data[4:8] == b"ftyp" else ".mp3")
        p = Path(td) / f"track{ext}"
        p.write_bytes(data)
        try:
            info = ff.probe(p)
        except Exception as e:  # noqa: BLE001
            raise AppError("Ses dosyası okunamadı", code="bad_file", status_code=415) from e
        if info.has_video or not info.has_audio or not (10 <= info.duration <= 900):
            raise AppError("Dosya yalnızca ses içermeli ve 10-900 sn olmalı", code="bad_file", status_code=415)
        a = assets_svc.store_asset(db, user.id, None, "music", p, duration=info.duration,
                                   license={"type": license_type, "source": license_source, "attribution": attribution, "commercial_use": True})
    t = MusicTrack(user_id=user.id, asset_id=a.id, title=title, mood=mood, license_type=license_type, license_source=license_source,
                   attribution=attribution, commercial_use=True)
    db.add(t)
    db.commit()
    audit(db, request, user.id, "music.upload", "music", t.id, license=license_type)
    return {"id": t.id, "title": t.title, "duration": info.duration}


@router.delete("/music/{tid}")
def music_delete(tid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = db.get(MusicTrack, tid)
    if t is None or t.user_id != user.id:
        raise NotFound("Müzik bulunamadı")
    a = db.get(Asset, t.asset_id)
    db.delete(t)
    if a:
        assets_svc.delete_asset(db, a)
    db.commit()
    return {"ok": True}
