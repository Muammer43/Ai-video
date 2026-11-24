"""TikTok Content Posting API (Direct Post, FILE_UPLOAD) + OAuth (PKCE). Denetimsiz istemciler yalnızca özel (SELF_ONLY) paylaşabilir."""
from __future__ import annotations

from urllib.parse import urlencode

from ...core.config import get_settings
from .. import http as H
from ..base import ProviderError
from .base import PublishProvider, PublishRequest, TokenSet, VerifyResult

AUTH = "https://www.tiktok.com/v2/auth/authorize/"  # Login Kit; bu sayfa içerik gönderme dokümanında açıkça yazmıyor
API = "https://open.tiktokapis.com"
PRIV = {"public": "PUBLIC_TO_EVERYONE", "unlisted": "MUTUAL_FOLLOW_FRIENDS", "private": "SELF_ONLY"}
MB = 1024 * 1024


class TikTokPublisher(PublishProvider):
    platform = "tiktok"
    label = "TikTok"
    scopes = ["user.info.basic", "video.publish", "video.list"]
    requirements = ("TikTok geliştirici uygulaması + 'Content Posting API' ürünü ve video.publish izni gerekir. Denetimden geçmemiş istemciler "
                    "yalnızca özel (SELF_ONLY) paylaşım yapabilir; herkese açık otomatik yayın için TikTok denetimi tamamlanmalıdır.")

    def configured(self) -> bool:
        s = get_settings()
        return bool(s.tiktok_client_key and s.tiktok_client_secret)

    def config_hint(self) -> str:
        return "TIKTOK_CLIENT_KEY ve TIKTOK_CLIENT_SECRET gerekli (developers.tiktok.com)"

    def authorize_url(self, redirect_uri: str, state: str, challenge: str) -> str:
        q = {"client_key": get_settings().tiktok_client_key, "scope": ",".join(self.scopes), "response_type": "code", "redirect_uri": redirect_uri,
             "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
        return f"{AUTH}?{urlencode(q)}"

    def _tok(self, data: dict) -> dict:
        s = get_settings()
        with H.client(30) as c:
            r = H.request(c, "POST", f"{API}/v2/oauth/token/", "tiktok", data={**data, "client_key": s.tiktok_client_key, "client_secret": s.tiktok_client_secret},
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
        d = r.json()
        if d.get("error"):
            raise ProviderError(f"tiktok: {d.get('error')}: {d.get('error_description', '')[:150]}", "auth")
        return d

    def exchange_code(self, code: str, redirect_uri: str, verifier: str) -> TokenSet:
        d = self._tok({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "code_verifier": verifier})
        ts = TokenSet(access_token=d["access_token"], refresh_token=d.get("refresh_token", ""), expires_in=int(d.get("expires_in", 7200)),
                      refresh_expires_in=int(d.get("refresh_expires_in", 0)) or None, scopes=(d.get("scope") or "").split(","), external_id=d.get("open_id", ""))
        h = {"Authorization": f"Bearer {ts.access_token}"}
        with H.client(30) as c:
            try:
                u = H.request(c, "GET", f"{API}/v2/user/info/", "tiktok", params={"fields": "open_id,display_name"}, headers=h).json()
                ts.display_name = (u.get("data", {}).get("user") or {}).get("display_name", "")
            except ProviderError:
                pass
            ts.account_type = "creator"
            ts.capabilities = self.creator_info(ts.access_token)
        return ts

    def creator_info(self, access_token: str) -> dict:
        with H.client(30) as c:
            r = H.request(c, "POST", f"{API}/v2/post/publish/creator_info/query/", "tiktok",
                          headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"}).json()
        err = r.get("error", {})
        if err.get("code") not in (None, "ok"):
            raise ProviderError(f"tiktok creator_info: {err.get('code')}: {err.get('message', '')[:120]}", "auth")
        d = r.get("data", {})
        opts = d.get("privacy_level_options", [])
        return {"privacy_level_options": opts, "max_video_post_duration_sec": d.get("max_video_post_duration_sec"),
                "private_only": opts == ["SELF_ONLY"], "comment_disabled": d.get("comment_disabled")}

    def refresh(self, refresh_token: str, access_token: str = "") -> TokenSet:
        d = self._tok({"grant_type": "refresh_token", "refresh_token": refresh_token})
        # Refresh token döner (rotasyon): eskisi geçersiz olabilir → yenisi saklanmalı
        return TokenSet(access_token=d["access_token"], refresh_token=d.get("refresh_token", refresh_token), expires_in=int(d.get("expires_in", 7200)),
                        refresh_expires_in=int(d.get("refresh_expires_in", 0)) or None)

    def publish(self, req: PublishRequest) -> dict:
        st = dict(req.state)
        if st.get("publish_id"):
            return st
        h = {"Authorization": f"Bearer {req.access_token}", "Content-Type": "application/json; charset=UTF-8"}
        info = self.creator_info(req.access_token)
        want = PRIV.get(req.privacy, "SELF_ONLY")
        if want not in info["privacy_level_options"]:
            raise ProviderError(f"tiktok: '{want}' bu hesapta kullanılamıyor (izinli: {info['privacy_level_options']}). "
                                "Uygulamanız TikTok denetiminden geçmemiş olabilir.", "needs_action")
        max_dur = info.get("max_video_post_duration_sec")
        if max_dur and req.duration > max_dur:
            raise ProviderError(f"tiktok: video {req.duration:.0f} sn > hesap sınırı {max_dur} sn", "needs_action")
        size = req.video_path.stat().st_size
        chunk = size if size < 5 * MB else 10 * MB
        total = max(size // chunk, 1)
        caption = (req.title + " " + " ".join(t if t.startswith("#") else "#" + t for t in req.hashtags))[:2200]
        body = {"post_info": {"title": caption, "privacy_level": want, "disable_duet": False, "disable_comment": False, "disable_stitch": False,
                              "is_aigc": bool(req.synthetic)},
                "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": total}}
        with H.client(120) as c:
            r = c.post(f"{API}/v2/post/publish/video/init/", headers=h, json=body)
            if r.status_code >= 400:
                try:
                    code = r.json().get("error", {}).get("code", "")
                except Exception:  # noqa: BLE001
                    code = ""
                if code == "unaudited_client_can_only_post_to_private_accounts":
                    raise ProviderError("tiktok: uygulama denetlenmemiş — yalnızca özel hesaplara/SELF_ONLY paylaşılabilir", "needs_action")
                if code in ("spam_risk_too_many_posts", "reached_active_user_cap"):
                    raise ProviderError(f"tiktok: günlük paylaşım sınırı/kota ({code})", "needs_action")
                H.raise_for_provider(r, "tiktok")
            d = r.json()
            if d.get("error", {}).get("code") not in (None, "ok"):
                raise ProviderError(f"tiktok init: {d['error'].get('code')}: {d['error'].get('message', '')[:120]}", "permanent")
            pid, up = d["data"]["publish_id"], d["data"].get("upload_url")
            st["publish_id"] = pid
            if not up:
                raise ProviderError("tiktok: upload_url alınamadı", "permanent")
            with open(req.video_path, "rb") as f:
                for i in range(total):
                    start = i * chunk
                    n = chunk if i < total - 1 else size - start  # son parça kalanı alır
                    data = f.read(n)
                    pr = c.put(up, content=data, headers={"Content-Type": "video/mp4", "Content-Length": str(len(data)),
                                                           "Content-Range": f"bytes {start}-{start + len(data) - 1}/{size}"})
                    if pr.status_code not in (200, 201, 206):
                        H.raise_for_provider(pr, "tiktok upload")
                        raise ProviderError(f"tiktok: parça yükleme {pr.status_code}", "transient")
        return st

    def verify(self, req: PublishRequest, state: dict) -> VerifyResult:
        pid = state.get("publish_id")
        if not pid:
            return VerifyResult("failed", detail="publish_id yok")
        with H.client(30) as c:
            r = H.request(c, "POST", f"{API}/v2/post/publish/status/fetch/", "tiktok", json={"publish_id": pid},
                          headers={"Authorization": f"Bearer {req.access_token}", "Content-Type": "application/json; charset=UTF-8"}).json()
        d = r.get("data", {})
        status = d.get("status", "")
        if status == "PUBLISH_COMPLETE":
            ids = d.get("publicaly_available_post_id") or d.get("publicly_available_post_id") or []
            ext = str(ids[0]) if ids else pid
            return VerifyResult("published", external_id=ext, url="", effective_privacy=req.privacy, detail="TikTok yayını tamamladı",
                                state={**state, "post_id": str(ids[0]) if ids else ""})
        if status == "FAILED":
            return VerifyResult("failed", external_id=pid, detail=f"TikTok: {d.get('fail_reason', 'başarısız')}")
        return VerifyResult("processing", external_id=pid, detail=f"TikTok durumu: {status or 'bilinmiyor'}", state=state)

    def metrics(self, access_token: str, external_id: str, duration: float, account: dict) -> dict:
        with H.client(30) as c:
            r = H.request(c, "POST", f"{API}/v2/video/query/", "tiktok", params={"fields": "id,like_count,comment_count,share_count,view_count"},
                          headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"},
                          json={"filters": {"video_ids": [external_id]}}).json()
        vids = (r.get("data") or {}).get("videos") or []
        if not vids:
            return {}
        v = vids[0]
        # Not: izlenme süresi/tamamlanma oranı resmî Display API'de yok → None (uydurulmaz)
        return {"views": v.get("view_count"), "likes": v.get("like_count"), "comments": v.get("comment_count"), "shares": v.get("share_count")}
