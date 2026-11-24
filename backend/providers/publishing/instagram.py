"""Instagram API (Instagram Login) ile Reels yayını: konteyner → durum sorgusu → media_publish → medya doğrulaması."""
from __future__ import annotations

from urllib.parse import urlencode

from ...core.config import get_settings
from .. import http as H
from ..base import ProviderError
from .base import PublishProvider, PublishRequest, TokenSet, VerifyResult, hashtag_text

AUTH = "https://www.instagram.com/oauth/authorize"
SHORT = "https://api.instagram.com/oauth/access_token"
GRAPH = "https://graph.instagram.com"


class InstagramPublisher(PublishProvider):
    platform = "instagram"
    label = "Instagram Reels"
    needs_public_url = True
    scopes = ["instagram_business_basic", "instagram_business_content_publish", "instagram_business_manage_insights"]
    requirements = ("Instagram Business veya Creator (profesyonel) hesap gerekir; kişisel hesaplarla API yayını yapılamaz. Meta uygulaması için "
                    "gelişmiş/standart erişim gerekir. Video, Meta'nın indirebilmesi için herkese açık HTTPS adresinden erişilebilir olmalıdır "
                    "(PUBLIC_BASE_URL veya S3 imzalı URL). API ile 24 saatte en fazla 100 paylaşım (dokümanlarda 50/100 çelişkisi var).")

    @property
    def v(self) -> str:
        return get_settings().graph_api_version

    def configured(self) -> bool:
        s = get_settings()
        return bool(s.instagram_app_id and s.instagram_app_secret)

    def config_hint(self) -> str:
        return "INSTAGRAM_APP_ID ve INSTAGRAM_APP_SECRET gerekli (Meta for Developers → Instagram API with Instagram Login)"

    def authorize_url(self, redirect_uri: str, state: str, challenge: str) -> str:
        q = {"client_id": get_settings().instagram_app_id, "redirect_uri": redirect_uri, "response_type": "code",
             "scope": ",".join(self.scopes), "state": state}
        return f"{AUTH}?{urlencode(q)}"

    def exchange_code(self, code: str, redirect_uri: str, verifier: str) -> TokenSet:
        s = get_settings()
        with H.client(30) as c:
            r = H.request(c, "POST", SHORT, "instagram", data={"client_id": s.instagram_app_id, "client_secret": s.instagram_app_secret,
                                                               "grant_type": "authorization_code", "redirect_uri": redirect_uri, "code": code}).json()
            short = r.get("access_token") or (r.get("data") or [{}])[0].get("access_token")
            if not short:
                raise ProviderError("instagram: kısa ömürlü token alınamadı", "auth")
            ll = H.request(c, "GET", f"{GRAPH}/access_token", "instagram",
                           params={"grant_type": "ig_exchange_token", "client_secret": s.instagram_app_secret, "access_token": short}).json()
            tok = ll["access_token"]
            me = H.request(c, "GET", f"{GRAPH}/{self.v}/me", "instagram", params={"fields": "user_id,username,account_type", "access_token": tok}).json()
        atype = me.get("account_type", "")
        if atype not in ("BUSINESS", "MEDIA_CREATOR", "CREATOR"):
            raise ProviderError(f"instagram: hesap türü '{atype}' API yayınını desteklemiyor — Business/Creator hesaba geçin", "permanent")
        return TokenSet(access_token=tok, refresh_token="", expires_in=int(ll.get("expires_in", 5183944)), scopes=list(self.scopes),
                        external_id=str(me.get("user_id") or me.get("id")), display_name="@" + me.get("username", ""), account_type=atype)

    def refresh(self, refresh_token: str, access_token: str = "") -> TokenSet:
        with H.client(30) as c:
            d = H.request(c, "GET", f"{GRAPH}/refresh_access_token", "instagram",
                          params={"grant_type": "ig_refresh_token", "access_token": access_token}).json()
        return TokenSet(access_token=d["access_token"], expires_in=int(d.get("expires_in", 5183944)))

    def publish(self, req: PublishRequest) -> dict:
        st = dict(req.state)
        if st.get("container_id") or st.get("media_id"):
            return st
        if not req.public_video_url or not req.public_video_url.startswith("https://"):
            raise ProviderError("instagram: video için herkese açık HTTPS URL gerekli (PUBLIC_BASE_URL https olmalı veya S3 kullanın)", "needs_action")
        caption = (req.description or req.title) + "\n\n" + hashtag_text(req.hashtags)
        body = {"media_type": "REELS", "video_url": req.public_video_url, "caption": caption[:2200], "share_to_feed": "true",
                "is_ai_generated": "true" if req.synthetic else "false", "access_token": req.access_token}
        if req.cover_url:
            body["cover_url"] = req.cover_url
        with H.client(60) as c:
            r = H.request(c, "POST", f"{GRAPH}/{self.v}/{req.account['external_id']}/media", "instagram", data=body).json()
        if not r.get("id"):
            raise ProviderError("instagram: konteyner oluşturulamadı", "permanent")
        st["container_id"] = r["id"]
        return st

    def verify(self, req: PublishRequest, state: dict) -> VerifyResult:
        with H.client(60) as c:
            if state.get("media_id"):
                return self._check_media(c, req, state)
            cid = state.get("container_id")
            if not cid:
                return VerifyResult("failed", detail="konteyner yok")
            s = H.request(c, "GET", f"{GRAPH}/{self.v}/{cid}", "instagram", params={"fields": "status_code", "access_token": req.access_token}).json()
            sc = s.get("status_code")
            if sc in ("ERROR", "EXPIRED"):
                return VerifyResult("failed", external_id=cid, detail=f"Instagram konteyner durumu: {sc}")
            if sc != "FINISHED":
                return VerifyResult("processing", external_id=cid, detail=f"Instagram işleme: {sc}", state=state)
            pub = H.request(c, "POST", f"{GRAPH}/{self.v}/{req.account['external_id']}/media_publish", "instagram",
                            data={"creation_id": cid, "access_token": req.access_token}).json()
            if not pub.get("id"):
                return VerifyResult("failed", external_id=cid, detail="media_publish kimlik döndürmedi")
            state = {**state, "media_id": pub["id"]}
            return self._check_media(c, req, state)

    def _check_media(self, c, req: PublishRequest, state: dict) -> VerifyResult:  # noqa: ANN001
        mid = state["media_id"]
        m = H.request(c, "GET", f"{GRAPH}/{self.v}/{mid}", "instagram", params={"fields": "id,permalink,media_product_type", "access_token": req.access_token}).json()
        if m.get("id") == mid and m.get("permalink"):
            return VerifyResult("published", external_id=mid, url=m["permalink"], effective_privacy="public", detail="Instagram medyayı doğruladı", state=state)
        return VerifyResult("processing", external_id=mid, detail="medya henüz doğrulanamadı", state=state)

    def metrics(self, access_token: str, external_id: str, duration: float, account: dict) -> dict:
        with H.client(30) as c:
            r = H.request(c, "GET", f"{GRAPH}/{self.v}/{external_id}/insights", "instagram",
                          params={"metric": "views,reach,likes,comments,shares,saved,ig_reels_avg_watch_time", "access_token": access_token}).json()
        vals = {x["name"]: (x.get("values") or [{}])[0].get("value") for x in r.get("data", [])}
        if not vals:
            return {}  # boş veri = mevcut değil (sıfır değil)
        avg = vals.get("ig_reels_avg_watch_time")
        avg_s = float(avg) / 1000.0 if avg is not None else None  # Meta bu metriği milisaniye cinsinden verir
        out = {"views": vals.get("views"), "likes": vals.get("likes"), "comments": vals.get("comments"), "shares": vals.get("shares"),
               "saves": vals.get("saved"), "avg_watch_seconds": avg_s}
        if avg_s is not None and duration:
            out["completion_rate"] = min(avg_s / duration, 1.0)
        return out
