from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..models import UserSetting


def defaults() -> dict:
    s = get_settings()
    return {
        "budget": {
            "daily_usd": s.default_daily_budget_usd,
            "monthly_usd": s.default_monthly_budget_usd,
            "per_video_usd": s.default_per_video_budget_usd,
            "alert_pct": 80,
            "block_expensive_fallback": True,
            "paused": False,
            "paused_reason": "",
        },
        "quality": {"auto_publish_min": 90, "low_risk_min": 80, "review_min": 60},
        "providers": {
            "llm": ["openai", "anthropic", "template"],
            "image": ["openai", "fal", "procedural"],
            "video": ["fal", "runway", "replicate", "stock", "ken_burns"],
            "tts": ["openai", "elevenlabs", "espeak"],
            "stt": ["openai", "aligner"],
            "stock": ["pexels", "pixabay"],
        },
        "automation": {"paused": False},
        "preferences": {"language": "tr", "watermark": False},
    }


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def get_user_settings(db: Session, user_id: str) -> dict:
    row = db.get(UserSetting, user_id)
    return _merge(defaults(), row.data if row else {})


def update_user_settings(db: Session, user_id: str, patch: dict[str, Any]) -> dict:
    row = db.get(UserSetting, user_id)
    if row is None:
        row = UserSetting(user_id=user_id, data={})
        db.add(row)
    row.data = _merge(row.data or {}, patch)
    db.commit()
    return _merge(defaults(), row.data)
