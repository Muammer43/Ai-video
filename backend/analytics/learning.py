"""Öğrenme motoru: yalnızca ölçülmüş platform verisiyle çalışır; yeterli veri yoksa kesin sonuç iddia etmez."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Experiment, MetricSnapshot, Project, Publication, utcnow
from . import stats

SETTLE_HOURS = 48  # metrikler bu yaştan sonra 'oturmuş' sayılır


def hook_type(hook: str) -> str:
    h = (hook or "").strip().lower()
    if "?" in h:
        return "soru"
    if re.match(r"^\d", h) or re.search(r"\b\d+\s+(şey|gerçek|detay|neden|yol|ipucu|facts?|things?)", h):
        return "sayı/liste"
    if re.search(r"\b(sen|siz|you|senin|sizin)\b", h):
        return "doğrudan hitap"
    return "iddia/ifade"


def duration_bucket(d: float) -> str:
    return "<20 sn" if d < 20 else "20–35 sn" if d < 35 else "35–60 sn" if d < 60 else "60+ sn"


def hour_bucket(h: int) -> str:
    a = (h // 4) * 4
    return f"{a:02d}–{a + 4:02d} UTC"


def _score(s: MetricSnapshot) -> tuple[str, float] | None:
    """Videonun birincil performans değeri: izlenme-geçişi (varsa) aksi halde etkileşim oranı. (metrik adı, değer)"""
    if s.completion_rate is not None:
        return "view_through", float(s.completion_rate)
    if s.views and s.views >= 50:
        inter = sum(x or 0 for x in (s.likes, s.comments, s.shares, s.saves))
        return "engagement", inter / s.views
    return None


def performance_rows(db: Session, user_id: str) -> list[dict]:
    rows = []
    pubs = db.execute(select(Publication).where(Publication.user_id == user_id, Publication.status == "PUBLISHED")).scalars().all()
    for pub in pubs:
        snaps = db.execute(select(MetricSnapshot).where(MetricSnapshot.publication_id == pub.id).order_by(MetricSnapshot.taken_at)).scalars().all()
        if not snaps:
            continue
        settled = [s for s in snaps if s.age_hours >= SETTLE_HOURS]
        snap = settled[0] if settled else snaps[-1]
        sc = _score(snap)
        p = db.get(Project, pub.project_id)
        if sc is None or p is None:
            continue
        pub_at = pub.published_at or pub.created_at
        rows.append({"publication_id": pub.id, "project_id": p.id, "platform": pub.platform, "category": p.category,
                     "duration": float(p.duration_target), "hook_type": hook_type((p.script or {}).get("hook", "")),
                     "hour": pub_at.hour, "dow": pub_at.weekday(), "metric": sc[0], "score": sc[1], "views": snap.views or 0,
                     "settled": bool(settled), "variant": p.variant, "experiment_id": p.experiment_id,
                     "follow_rate": (snap.followers_gained / snap.views) if snap.views and snap.followers_gained is not None else None})
    return rows


def _group(rows: list[dict], key: str) -> dict[str, list[float]]:
    g: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        g[str(r[key])].append(r["score"])
    return g


def _ranked(rows: list[dict], key: str) -> list[dict]:
    g = _group(rows, key)
    out = [{"group": k, **stats.describe(v)} for k, v in g.items()]
    out.sort(key=lambda x: (x["mean"] is None, -(x["mean"] or 0)))
    # 1. ile 2. grup arasında anlamlı fark var mı?
    if len(out) >= 2:
        top, second = out[0]["group"], out[1]["group"]
        out[0]["vs_next"] = stats.compare(g[top], g[second])
    return out


def compute_insights(rows: list[dict]) -> dict:
    """Saf fonksiyon: satırlardan içgörü üretir. Yeterli veri yoksa 'insufficient' açıkça belirtilir."""
    n = len(rows)
    metrics = sorted({r["metric"] for r in rows})
    # Metrikler karışıksa kıyaslama anlamsız: baskın metrikle sınırla
    if len(metrics) > 1:
        dom = max(metrics, key=lambda m: sum(r["metric"] == m for r in rows))
        rows = [r for r in rows if r["metric"] == dom]
        metrics = [dom]
    res: dict = {"n_videos": n, "metric": metrics[0] if metrics else None, "sufficient": n >= stats.MIN_COMPARE,
                 "min_required": stats.MIN_COMPARE, "insights": [], "category": [], "duration": [], "posting_time": [], "hook": [], "platform": []}
    if not rows:
        res["insights"].append("Henüz ölçülmüş performans verisi yok; öğrenme için yayınlanmış videolar ve platform metrikleri gerekir.")
        return res
    for r in rows:
        r["dur_bucket"] = duration_bucket(r["duration"])
        r["hour_bucket"] = hour_bucket(r["hour"])
    res["category"] = _ranked(rows, "category")
    res["duration"] = _ranked(rows, "dur_bucket")
    res["posting_time"] = _ranked(rows, "hour_bucket")
    res["hook"] = _ranked(rows, "hook_type")
    res["platform"] = _ranked(rows, "platform")
    label = {"view_through": "ortalama izlenme-geçişi", "engagement": "etkileşim oranı"}[metrics[0]]
    for title, key in (("Kategori", "category"), ("Video uzunluğu", "duration"), ("Yayın saati", "posting_time"), ("Hook türü", "hook")):
        g = res[key]
        if len(g) >= 2 and g[0].get("vs_next", {}).get("conclusive"):
            res["insights"].append(f"{title}: '{g[0]['group']}' grubu ({label}), '{g[1]['group']}' grubundan anlamlı şekilde yüksek "
                                   f"(p={g[0]['vs_next']['p_value']}, n={g[0]['n']}/{g[1]['n']}).")
        elif g:
            res["insights"].append(f"{title}: kesin sonuç yok — {g[0].get('vs_next', {}).get('reason', 'yetersiz veri')}.")
    # ürün tarafı için faktörler (büzülme tahmini: az veri → 1.0'a yakın)
    overall = stats.mean([r["score"] for r in rows]) if rows else 0
    factors = {}
    if overall > 0:
        for g in res["category"]:
            if g["n"] >= stats.MIN_GROUP and g["mean"] is not None:
                raw = (g["mean"] - overall) / overall
                factors[g["group"]] = round(1 + max(min(raw, 0.3), -0.3) * g["n"] / (g["n"] + 10), 3)
    res["category_factor"] = factors
    return res


def learning_insights(db: Session, user_id: str) -> dict:
    rows = performance_rows(db, user_id)
    out = compute_insights(rows)
    out["note"] = ("Yalnızca platformlardan alınan ölçülmüş metriklerle hesaplanır. Küçük örneklemde sonuçlar gürültülüdür; "
                   "'yetersiz/düşük' güven etiketli gruplar karar için kullanılmamalıdır. TikTok resmî API'si izlenme süresi vermez.")
    return out


def learning_priors(db: Session, user_id: str) -> dict:
    """Fikir üretimine girdi: yalnızca anlamlı bulunan içgörüler ve kategori faktörleri."""
    ins = learning_insights(db, user_id)
    return {"insights": [i for i in ins["insights"] if "kesin sonuç yok" not in i] if ins["sufficient"] else [],
            "category_factor": ins.get("category_factor", {}) if ins["sufficient"] else {}}


# ---------------- A/B deneyleri ----------------
PRESETS = {
    "hook": {"A": {"label": "Soru ile hook", "params": {"hook_style": "ilk cümle merak uyandıran bir soru"}},
             "B": {"label": "Cesur iddia ile hook", "params": {"hook_style": "ilk cümle kısa ve cesur ama doğrulanabilir bir ifade"}}},
    "title": {"A": {"label": "Merak başlığı", "params": {"title_style": "merak uyandıran ama dürüst"}},
              "B": {"label": "Açıklayıcı başlık", "params": {"title_style": "açık ve açıklayıcı"}}},
    "cover": {"A": {"label": "Başlıklı kapak", "params": {"cover_style": "title"}}, "B": {"label": "Başlıksız kapak", "params": {"cover_style": "none"}}},
    "format": {"A": {"label": "30 sn", "params": {"duration": 30}}, "B": {"label": "45 sn", "params": {"duration": 45}}},
}


def create_experiment(db: Session, user_id: str, kind: str, channel_id: str | None, min_views: int = 500, variants: dict | None = None) -> Experiment:
    if kind not in PRESETS:
        raise ValueError("Geçersiz deney türü")
    ex = Experiment(user_id=user_id, channel_id=channel_id, kind=kind, variants=variants or PRESETS[kind], min_views_per_variant=min_views,
                    metric="view_through")
    db.add(ex)
    db.commit()
    return ex


def evaluate_experiment(db: Session, ex: Experiment) -> dict:
    rows = [r for r in performance_rows(db, ex.user_id) if r["experiment_id"] == ex.id]
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by[r["variant"]].append(r)
    names = sorted(ex.variants)
    summary = {}
    for v in names:
        rs = by.get(v, [])
        summary[v] = {**stats.describe([x["score"] for x in rs]), "views": sum(x["views"] for x in rs), "label": ex.variants[v].get("label", v)}
    res: dict = {"variants": summary, "metric": rows[0]["metric"] if rows else None}
    if len(names) != 2:
        res.update(conclusive=False, reason="yalnızca iki varyantlı deneyler değerlendirilir")
        return res
    a, b = names
    for v in names:
        if summary[v]["views"] < ex.min_views_per_variant:
            res.update(conclusive=False, reason=f"varyant {v}: toplam izlenme {summary[v]['views']} < {ex.min_views_per_variant}")
            return res
    cmpres = stats.compare([x["score"] for x in by[a]], [x["score"] for x in by[b]], alpha=0.05)
    res.update(cmpres)
    if cmpres["conclusive"]:
        res["winner"] = a if cmpres["diff"] > 0 else b
    res["caveat"] = "Varyant videoları farklı konular içerir; konu etkisi gürültü olarak kalır. Örneklem arttıkça güvenilirlik artar."
    return res


def conclude_ready_experiments(db: Session, user_id: str | None = None) -> int:
    q = select(Experiment).where(Experiment.status == "running")
    if user_id:
        q = q.where(Experiment.user_id == user_id)
    n = 0
    for ex in db.execute(q).scalars().all():
        r = evaluate_experiment(db, ex)
        ex.result = r
        if r.get("conclusive"):
            ex.status, ex.concluded_at = "concluded", utcnow()
            n += 1
    db.commit()
    return n
