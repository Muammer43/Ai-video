"""Fiyat tablosu. Her kayıt kaynak ve tarih taşır; `verified=True` yalnızca resmî dokümandan o tarihte okunanlar içindir.
PRICING_OVERRIDES_JSON ile ezilebilir (ör. {"video:fal:default":{"per_second":0.2}}). Hesaplanan maliyet her zaman 'tahmin'dir
(sağlayıcı gerçek maliyeti bildirmedikçe)."""
from __future__ import annotations

from ..core.config import get_settings

AS_OF = "2026-11-24"

# (anahtar) -> {alanlar..., verified, source}
TABLE: dict[str, dict] = {
    # LLM (USD / 1M token) — doğrulanamadı: sağlayıcı fiyat sayfaları okunamadı; güncel değerleri OVERRIDES ile girin.
    "llm:openai:default": {"in_per_m": 0.40, "out_per_m": 1.60, "verified": False, "source": "varsayılan tahmin"},
    "llm:anthropic:default": {"in_per_m": 3.00, "out_per_m": 15.00, "verified": False, "source": "varsayılan tahmin"},
    # Görsel
    "image:openai:default": {"per_image": 0.04, "verified": False, "source": "varsayılan tahmin (gpt-image kalite=medium civarı)"},
    "image:fal:fal-ai/flux/schnell": {"per_megapixel": 0.003, "verified": True, "source": "fal.ai fiyat sayfası " + AS_OF},
    "image:fal:fal-ai/flux/dev": {"per_megapixel": 0.025, "verified": True, "source": "fal.ai fiyat sayfası " + AS_OF},
    "image:fal:default": {"per_megapixel": 0.025, "verified": False, "source": "varsayılan tahmin"},
    "image:replicate:default": {"per_image": 0.04, "verified": False, "source": "varsayılan tahmin"},
    # Video (USD / saniye)
    "video:fal:fal-ai/kling-video/v3/pro/text-to-video": {"per_second": 0.14, "verified": True, "source": "fal.ai fiyat sayfası " + AS_OF},
    "video:fal:fal-ai/kling-video/v3/pro/image-to-video": {"per_second": 0.14, "verified": False, "source": "t2v fiyatından varsayım"},
    "video:fal:fal-ai/veo3.1/fast": {"per_second": 0.15, "verified": True, "source": "fal.ai fiyat sayfası " + AS_OF},
    "video:fal:fal-ai/veo3.1/fast/image-to-video": {"per_second": 0.15, "verified": True, "source": "fal.ai fiyat sayfası " + AS_OF},
    "video:fal:alibaba/wan-3.0/image-to-video": {"per_second": 0.05, "verified": True, "source": "fal.ai fiyat sayfası " + AS_OF},
    "video:fal:default": {"per_second": 0.15, "verified": False, "source": "varsayılan tahmin"},
    # Runway: 1 kredi = 0.01 USD, saniye başına kredi
    "video:runway:gen4_turbo": {"per_second": 0.05, "verified": True, "source": "Runway fiyat sayfası " + AS_OF + " (5 kredi/sn)"},
    "video:runway:gen4.5": {"per_second": 0.12, "verified": True, "source": "Runway fiyat sayfası " + AS_OF + " (12 kredi/sn)"},
    "video:runway:default": {"per_second": 0.12, "verified": False, "source": "varsayılan tahmin"},
    "video:replicate:default": {"per_second": 0.10, "verified": False, "source": "varsayılan tahmin (modele göre değişir)"},
    # TTS
    "tts:openai:default": {"per_1k_chars": 0.015, "verified": False, "source": "varsayılan tahmin"},
    "tts:elevenlabs:eleven_multilingual_v2": {"per_1k_chars": 0.08, "verified": True, "source": "ElevenLabs API fiyatı " + AS_OF},
    "tts:elevenlabs:default": {"per_1k_chars": 0.08, "verified": False, "source": "varsayılan tahmin"},
    # STT
    "stt:openai:default": {"per_minute": 0.006, "verified": False, "source": "varsayılan tahmin (whisper-1)"},
}

# sağlayıcı fiyat kademesi (pahalı yedeğe geçişi engellemek için)
TIERS = {"template": 0, "procedural": 0, "ken_burns": 0, "espeak": 0, "aligner": 0, "stock": 0, "pexels": 0, "pixabay": 0,
         "openai": 1, "anthropic": 2, "fal": 2, "runway": 3, "replicate": 2, "elevenlabs": 2}


def _lookup(kind: str, provider: str, model: str) -> dict:
    t = dict(TABLE.get(f"{kind}:{provider}:{model}") or TABLE.get(f"{kind}:{provider}:default") or {})
    ov = get_settings().pricing_overrides()
    for key in (f"{kind}:{provider}:{model}", f"{kind}:{provider}:default"):
        if key in ov:
            t.update(ov[key])
            t["verified"] = False
            t["source"] = "kullanıcı geçersiz kılması"
            break
    return t


def _meta(t: dict) -> dict:
    return {"price_verified": bool(t.get("verified")), "price_source": t.get("source", "bilinmiyor")}


def llm_cost(provider: str, model: str, in_tok: int, out_tok: int) -> tuple[float, dict]:
    t = _lookup("llm", provider, model)
    return (in_tok * t.get("in_per_m", 0) + out_tok * t.get("out_per_m", 0)) / 1e6, _meta(t)


def image_cost(provider: str, model: str, megapixels: float = 1.0) -> tuple[float, dict]:
    t = _lookup("image", provider, model)
    if "per_megapixel" in t:
        return t["per_megapixel"] * megapixels, _meta(t)
    return t.get("per_image", 0.0), _meta(t)


def video_cost(provider: str, model: str, seconds: float) -> tuple[float, dict]:
    t = _lookup("video", provider, model)
    return t.get("per_second", 0.0) * seconds, _meta(t)


def tts_cost(provider: str, model: str, chars: int) -> tuple[float, dict]:
    t = _lookup("tts", provider, model)
    return t.get("per_1k_chars", 0.0) * chars / 1000, _meta(t)


def stt_cost(provider: str, model: str, seconds: float) -> tuple[float, dict]:
    t = _lookup("stt", provider, model)
    return t.get("per_minute", 0.0) * seconds / 60, _meta(t)
