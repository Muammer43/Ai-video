"""Firebase Cloud Messaging (HTTP v1). Yapılandırılmamışsa 'not_configured' döner — sahte başarı yok."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx
import jwt

from ..core.config import get_settings

log = logging.getLogger(__name__)
_token_cache: dict = {"token": "", "exp": 0}


def _load_sa() -> dict | None:
    raw = get_settings().fcm_service_account_json.strip()
    if not raw:
        return None
    try:
        if raw.startswith("{"):
            return json.loads(raw)
        return json.loads(Path(raw).read_text())
    except Exception:  # noqa: BLE001
        log.warning("FCM servis hesabı okunamadı")
        return None


def _access_token(sa: dict, client: httpx.Client) -> str:
    now = int(time.time())
    if _token_cache["token"] and _token_cache["exp"] - 60 > now:
        return _token_cache["token"]
    assertion = jwt.encode({"iss": sa["client_email"], "scope": "https://www.googleapis.com/auth/firebase.messaging",
                            "aud": sa.get("token_uri", "https://oauth2.googleapis.com/token"),
                            "iat": now, "exp": now + 3000}, sa["private_key"], algorithm="RS256")
    r = client.post(sa.get("token_uri", "https://oauth2.googleapis.com/token"),
                    data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion})
    r.raise_for_status()
    d = r.json()
    _token_cache.update(token=d["access_token"], exp=now + int(d.get("expires_in", 3000)))
    return d["access_token"]


def send_push(tokens: list[str], title: str, body: str, data: dict | None = None) -> str:
    sa = _load_sa()
    if not sa:
        return "not_configured"
    if not tokens:
        return "no_devices"
    project_id = get_settings().fcm_project_id or sa.get("project_id", "")
    ok = 0
    try:
        with httpx.Client(timeout=15) as c:
            at = _access_token(sa, c)
            for t in tokens:
                msg = {"message": {"token": t, "notification": {"title": title, "body": body},
                                   "data": {k: str(v) for k, v in (data or {}).items()}}}
                r = c.post(f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send",
                           headers={"Authorization": f"Bearer {at}"}, json=msg)
                ok += r.status_code == 200
        return f"sent:{ok}/{len(tokens)}"
    except Exception as e:  # noqa: BLE001
        return f"failed:{type(e).__name__}"
