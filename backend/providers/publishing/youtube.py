"""YouTube Data API v3: OAuth 2.0 + resumable upload (videos.insert) + doğrulama (videos.list)."""
from __future__ import annotations

import time
from urllib.parse import urlencode

from ...core.config import get_settings
from .. import http as H
from ..base import ProviderError
from .base import PublishProvider, PublishRequest, TokenSet, VerifyResult, hashtag_text

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"  # not: yetkilendirme URL'si YouTube sayfalarında açıkça yazmıyor; Google OAuth standardı
TOKEN = "https://oauth2.googleapis.com/token"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
API = "https://www.googleapis.com/youtube/v3"
ANALYTICS = "https://youtubeanalytics.googleapis.com/v2/reports"
CHUNK = 8 * 1024 * 1024  # 256 KB'ın katı


def _norm(v: str) -> str:
    v = (v or "").lower()
    for pre in ("status_", "privacy_"):
        if v.startswith(pre):
            v = v[len(pre):]
    return v


class YouTubePublisher(PublishProvider):
    platform = "youtube"
    label = "YouTube Shorts"
    scopes = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly",
              "https://www.googleapis.com/auth/yt-analytics.readonly"]
    requirements = ("Google Cloud projesinde YouTube Data API v3 etkin olmalı; varsayılan kota günde 100 yükleme. Denetimden geçmemiş API "
                    "projelerinde videoların görünürlüğü platform tarafından kısıtlanabilir — sistem gerçek görünürlüğü okur ve farklıysa bildirir.")

    def configured(self) -> bool:
        s = get_settings()
        return bool(s.google_client_id and s.google_client_secret)

    def config_hint(self) -> str:
        return "GOOGLE_CLIENT_ID ve GOOGLE_CLIENT_SECRET gerekli (Google Cloud Console → OAuth 2.0 Web uygulaması)"

    def authorize_url(self, redirect_uri: str, state: str, challenge: str) -> str:
        s = get_settings()
        q = {"client_id": s.google_client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": " ".join(self.scopes),
             "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "state": state,
             "code_challenge": challenge, "code_challenge_method": "S256"}
        return f"{AUTH}?{urlencode(q)}"

    def _token(self, data: dict) -> dict:
        s = get_settings()
        with H.client(30) as c:
            r = H.request(c, "POST", TOKEN, "youtube", data={**data, "client_id": s.google_client_id, "client_secret": s.google_client_secret})
        return r.json()

    def exchange_code(self, code: str, redirect_uri: str, verifier: str) -> TokenSet:
        d = self._token({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "code_verifier": verifier})
        if not d.get("refresh_token"):
            raise ProviderError("youtube: refresh_token alınamadı (hesabı yeniden bağlayın; 'prompt=consent' gerekli)", "permanent")
        ts = TokenSet(access_token=d["access_token"], refresh_token=d["refresh_token"], expires_in=int(d.get("expires_in", 3600)),
                      scopes=(d.get("scope") or "").split())
        with H.client(30) as c:
            r = H.request(c, "GET", f"{API}/channels", "youtube", params={"part": "snippet", "mine": "true"},
                          headers={"Authorization": f"Bearer {ts.access_token}"}).json()
        items = r.get("items") or []
        if not items:
            raise ProviderError("youtube: bu Google hesabında YouTube kanalı yok", "permanent")
        ts.external_id, ts.display_name, ts.account_type = items[0]["id"], items[0]["snippet"]["title"], "channel"
        return ts

    def refresh(self, refresh_token: str, access_token: str = "") -> TokenSet:
        d = self._token({"grant_type": "refresh_token", "refresh_token": refresh_token})
        return TokenSet(access_token=d["access_token"], refresh_token=d.get("refresh_token", refresh_token), expires_in=int(d.get("expires_in", 3600)))

    # ---- yükleme ----
    def publish(self, req: PublishRequest) -> dict:
        st = dict(req.state)
        if st.get("video_id"):
            return st
        size = req.video_path.stat().st_size
        desc = (req.description + "\n\n" + hashtag_text(req.hashtags) + ("\n#Shorts" if req.vertical and req.duration <= 180 else "")).strip()
        body = {"snippet": {"title": req.title[:100], "description": desc[:4900], "tags": [t.lstrip("#") for t in req.hashtags][:15], "categoryId": "22"},
                "status": {"privacyStatus": req.privacy, "selfDeclaredMadeForKids": False, "containsSyntheticMedia": bool(req.synthetic)}}
        headers = {"Authorization": f"Bearer {req.access_token}", "Content-Type": "application/json; charset=UTF-8",
                   "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"}
        with H.client(120) as c:
            if not st.get("session_uri"):
                r = H.request(c, "POST", UPLOAD, "youtube", params={"uploadType": "resumable", "part": "snippet,status"}, headers=headers, json=body)
                st["session_uri"] = r.headers.get("location")
                if not st["session_uri"]:
                    raise ProviderError("youtube: yükleme oturumu (Location) alınamadı", "permanent")
            sent = int(st.get("sent", 0))
            with open(req.video_path, "rb") as f:
                while True:
                    f.seek(sent)
                    chunk = f.read(CHUNK)
                    end = sent + len(chunk) - 1
                    try:
                        r = c.put(st["session_uri"], content=chunk, headers={"Content-Length": str(len(chunk)), "Content-Type": "video/mp4",
                                                                            "Content-Range": f"bytes {sent}-{end}/{size}"})
                    except Exception as e:  # noqa: BLE001
                        raise ProviderError(f"youtube: yükleme ağ hatası {type(e).__name__}", "transient") from e
                    if r.status_code in (200, 201):
                        vid = r.json().get("id")
                        if not vid:
                            raise ProviderError("youtube: yanıtta video kimliği yok", "permanent")
                        st.update(video_id=vid, sent=size)
                        return st
                    if r.status_code == 308:
                        rng = r.headers.get("range", "")
                        sent = int(rng.split("-")[-1]) + 1 if "-" in rng else sent + len(chunk)
                        st["sent"] = sent
                        continue
                    if r.status_code == 404:
                        st.pop("session_uri", None)
                        st["sent"] = 0
                        raise ProviderError("youtube: yükleme oturumu süresi doldu, yeniden başlatılacak", "transient")
                    H.raise_for_provider(r, "youtube")
                    raise ProviderError(f"youtube: beklenmeyen yükleme yanıtı {r.status_code}", "transient")

    def verify(self, req: PublishRequest, state: dict) -> VerifyResult:
        vid = state.get("video_id")
        if not vid:
            return VerifyResult("failed", detail="video kimliği yok")
        with H.client(30) as c:
            r = H.request(c, "GET", f"{API}/videos", "youtube", params={"part": "status,processingDetails", "id": vid},
                          headers={"Authorization": f"Bearer {req.access_token}"}).json()
        items = r.get("items") or []
        if not items:
            return VerifyResult("processing", external_id=vid, detail="video henüz listelenmiyor", state=state)
        st = items[0].get("status", {})
        up, priv = _norm(st.get("uploadStatus")), _norm(st.get("privacyStatus"))
        if up in ("failed", "rejected", "deleted"):
            return VerifyResult("failed", external_id=vid, detail=f"YouTube: {up} ({st.get('failureReason') or st.get('rejectionReason') or ''})")
        if up != "processed":
            return VerifyResult("processing", external_id=vid, effective_privacy=priv, detail=f"YouTube işleme durumu: {up}", state=state)
        url = f"https://www.youtube.com/shorts/{vid}" if req.vertical else f"https://www.youtube.com/watch?v={vid}"
        if priv != req.privacy:
            return VerifyResult("needs_action", external_id=vid, url=url, effective_privacy=priv,
                                detail=f"Video yüklendi ve işlendi ancak görünürlük '{priv}' (istenen '{req.privacy}'). "
                                       "API projesi denetimden geçmemiş olabilir; YouTube Studio'dan kontrol edin.")
        return VerifyResult("published", external_id=vid, url=url, effective_privacy=priv, detail="YouTube videoyu işledi", state=state)

    def metrics(self, access_token: str, external_id: str, duration: float, account: dict) -> dict:
        h = {"Authorization": f"Bearer {access_token}"}
        out: dict = {}
        with H.client(30) as c:
            r = H.request(c, "GET", f"{API}/videos", "youtube", params={"part": "statistics", "id": external_id}, headers=h).json()
            items = r.get("items") or []
            if items:
                s = items[0].get("statistics", {})
                out.update(views=int(s.get("viewCount", 0)), likes=int(s.get("likeCount", 0)), comments=int(s.get("commentCount", 0)))
            try:
                a = H.request(c, "GET", ANALYTICS, "youtube", headers=h, params={
                    "ids": "channel==MINE", "startDate": "2020-01-01", "endDate": time.strftime("%Y-%m-%d"),
                    "metrics": "views,averageViewDuration,averageViewPercentage,likes,comments,shares,subscribersGained",
                    "filters": f"video=={external_id}"}).json()
                rows = a.get("rows") or []
                if rows:
                    cols = [x["name"] for x in a.get("columnHeaders", [])]
                    row = dict(zip(cols, rows[0]))
                    out.update(avg_watch_seconds=float(row.get("averageViewDuration", 0)),
                               completion_rate=float(row.get("averageViewPercentage", 0)) / 100.0, shares=int(row.get("shares", 0)),
                               followers_gained=int(row.get("subscribersGained", 0)))
                    out["views"] = int(row.get("views", out.get("views", 0)))
            except ProviderError as e:  # analitik kapsamı yoksa temel istatistikle devam
                out["analytics_error"] = str(e)[:120]
        return out
