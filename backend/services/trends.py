"""Gerçek trend kaynakları (resmî/açık API'ler). Veri uydurulmaz: kaynak ulaşılamazsa boş döner ve nedeni bildirilir.
 - YouTube Data API v3 videos.list?chart=mostPopular (kullanıcının YouTube Data API anahtarı gerekir)
 - Hacker News Firebase API (anahtarsız, teknoloji/yapay zekâ/bilim)
 - Wikimedia Pageviews (anahtarsız, en çok okunan maddeler)"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import TrendItem, utcnow
from ..providers import http as H
from ..providers.base import ProviderError
from .credentials import CredentialResolver

log = logging.getLogger(__name__)
YT_CATEGORY = {"Oyun": "20", "GTA 6": "20", "Teknoloji": "28", "Yapay Zekâ": "28", "Bilim": "28", "Otomobil": "2", "Eğitim": "27",
               "Eğlence": "24", "Seyahat": "19"}
HN_CATS = {"Teknoloji", "Yapay Zekâ", "Bilim", "Finans"}
AI_WORDS = ("ai", "gpt", "llm", "openai", "anthropic", "claude", "gemini", "model", "neural", "diffusion", "agent")
WIKI_SKIP = ("Main_Page", "Special:", "Ana_Sayfa", "Özel:", "Wikipedia:", "Vikipedi:", "-")


def fetch_youtube(category: str, creds: CredentialResolver, region: str = "TR") -> list[dict]:
    key = creds.get("youtube_data")
    if not key or category not in YT_CATEGORY:
        return []
    with H.client(30) as c:
        r = H.request(c, "GET", "https://www.googleapis.com/youtube/v3/videos", "youtube",
                      params={"part": "snippet,statistics", "chart": "mostPopular", "regionCode": region, "maxResults": 20,
                              "videoCategoryId": YT_CATEGORY[category], "key": key})
    out = []
    for i, v in enumerate(r.json().get("items", [])):
        st = v.get("statistics", {})
        out.append({"source": "youtube_trending", "external_id": v["id"], "title": v["snippet"]["title"],
                    "url": f"https://www.youtube.com/watch?v={v['id']}", "category": category,
                    "metrics": {"rank": i + 1, "views": int(st.get("viewCount", 0) or 0), "likes": int(st.get("likeCount", 0) or 0),
                                "channel": v["snippet"].get("channelTitle", "")}})
    return out


def fetch_hackernews(category: str, limit: int = 15) -> list[dict]:
    if category not in HN_CATS:
        return []
    out = []
    with H.client(20) as c:
        ids = H.request(c, "GET", "https://hacker-news.firebaseio.com/v0/topstories.json", "hackernews").json()[:60]
        for rank, i in enumerate(ids):
            if len(out) >= limit:
                break
            it = H.request(c, "GET", f"https://hacker-news.firebaseio.com/v0/item/{i}.json", "hackernews").json() or {}
            title = it.get("title", "")
            if not title or it.get("type") != "story":
                continue
            low = title.lower()
            is_ai = any(w in low.split() or w in low for w in AI_WORDS)
            if category == "Yapay Zekâ" and not is_ai:
                continue
            out.append({"source": "hackernews", "external_id": str(i), "title": title,
                        "url": it.get("url") or f"https://news.ycombinator.com/item?id={i}", "category": category,
                        "metrics": {"rank": rank + 1, "points": it.get("score", 0), "comments": it.get("descendants", 0)}})
    return out


def fetch_wikipedia(lang: str = "tr", limit: int = 15) -> list[dict]:
    d = datetime.now(timezone.utc) - timedelta(days=2)
    url = f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/{lang}.wikipedia/all-access/{d:%Y/%m/%d}"
    with H.client(20) as c:
        r = H.request(c, "GET", url, "wikimedia")
    arts = r.json()["items"][0]["articles"]
    out = []
    for a in arts:
        t = a["article"]
        if any(s in t for s in WIKI_SKIP[:5]) or t == "Main_Page":
            continue
        out.append({"source": f"wikipedia_{lang}", "external_id": t, "title": t.replace("_", " "),
                    "url": f"https://{lang}.wikipedia.org/wiki/{t}", "category": "Bilgi",
                    "metrics": {"rank": a["rank"], "views": a["views"], "date": f"{d:%Y-%m-%d}"}})
        if len(out) >= limit:
            break
    return out


def refresh_trends(db: Session, user_id: str, categories: list[str], creds: CredentialResolver) -> dict:
    """Kaynakları çek, kaydet. Dönüş: {'added': n, 'sources': {kaynak: 'ok'|hata}}"""
    status: dict[str, str] = {}
    items: list[dict] = []
    for cat in categories:
        for name, fn in (("youtube_trending", lambda c=cat: fetch_youtube(c, creds)), ("hackernews", lambda c=cat: fetch_hackernews(c))):
            try:
                got = fn()
                items += got
                status[f"{name}:{cat}"] = f"ok ({len(got)})" if got else "bu kategori için kaynak yok/anahtar yok"
            except ProviderError as e:
                status[f"{name}:{cat}"] = f"hata: {e}"
    for lang in ("tr",):
        try:
            got = fetch_wikipedia(lang)
            items += got
            status[f"wikipedia_{lang}"] = f"ok ({len(got)})"
        except ProviderError as e:
            status[f"wikipedia_{lang}"] = f"hata: {e}"
    added = 0
    for it in items:
        exists = db.execute(select(TrendItem).where(TrendItem.user_id == user_id, TrendItem.source == it["source"],
                                                    TrendItem.external_id == it["external_id"])).scalar_one_or_none()
        if exists:
            exists.metrics = it["metrics"]
            exists.fetched_at = utcnow()
            continue
        db.add(TrendItem(user_id=user_id, **it))
        added += 1
    db.commit()
    return {"added": added, "fetched": len(items), "sources": status}


def recent_trends(db: Session, user_id: str, category: str | None = None, hours: int = 72, limit: int = 20) -> list[TrendItem]:
    q = select(TrendItem).where(TrendItem.user_id == user_id, TrendItem.fetched_at >= utcnow() - timedelta(hours=hours))
    if category:
        q = q.where(TrendItem.category.in_([category, "Bilgi"]))
    q = q.order_by(TrendItem.fetched_at.desc()).limit(limit * 3)
    rows = list(db.execute(q).scalars())
    rows.sort(key=lambda t: (t.category != category, t.metrics.get("rank", 99)))
    return rows[:limit]
