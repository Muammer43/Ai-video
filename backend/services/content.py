"""İçerik üretimi: fikir, senaryo, storyboard ve AI güvenlik incelemesi (LLM sağlayıcı yönlendirmesiyle)."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.errors import AppError
from ..database.session import session_scope
from ..models import Idea, Project
from ..providers import router
from ..providers.base import CallContext, LLMRequest
from .runtime import budget_guard

STYLE_TOKENS = {
    "cinematic": "cinematic lighting, shallow depth of field, film grain, high detail, dramatic color grading",
    "documentary": "documentary photography, natural light, realistic, candid, sharp focus",
    "energetic": "vibrant saturated colors, dynamic composition, high contrast, bold",
    "minimal": "minimalist composition, clean background, soft light, lots of negative space",
    "anime": "anime illustration style, clean line art, vivid colors",
    "3d": "3D render, soft global illumination, high detail, stylized",
}
LANG_NAME = {"tr": "Türkçe", "en": "English"}


# ---------- JSON ayrıştırma ----------
def parse_json(text: str) -> dict:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


class SceneModel(BaseModel):
    narration: str = Field(min_length=3, max_length=600)
    visual_prompt: str = Field(min_length=3, max_length=900)
    camera: str = "slow push-in"
    lighting: str = "soft cinematic light"
    composition: str = "subject centered, vertical framing"
    transition: str = "fade"
    on_screen_text: str = ""
    stock_query: str = ""


class ScriptModel(BaseModel):
    title: str = Field(min_length=3, max_length=150)
    hook: str = ""
    scenes: list[SceneModel] = Field(min_length=2, max_length=14)
    cta: str = ""
    description: str = ""
    hashtags: list[str] = []
    style_bible: str = ""
    facts_to_verify: list[str] = []
    claims_risk: str = "low"
    sources: list[str] = []

    @field_validator("hashtags", mode="before")
    @classmethod
    def _h(cls, v: Any) -> Any:
        if isinstance(v, list):
            return [("#" + str(x).lstrip("#")).replace(" ", "") for x in v][:12]
        return []


def _llm(ctx: CallContext, req: LLMRequest, preferred: list[str], user_id: str, project_id: str | None):
    return router.run("llm", ctx, req, preferred=preferred, db_factory=session_scope, guard=budget_guard(user_id, project_id))


# ---------- fikir ----------
def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-zçğıöşü0-9]{4,}", s.lower())}


def fingerprint(title: str) -> str:
    return hashlib.sha1(" ".join(sorted(_tokens(title))[:8]).encode()).hexdigest()


def is_duplicate(title: str, existing: list[str], threshold: float = 0.6) -> bool:
    a = _tokens(title)
    if not a:
        return False
    for e in existing:
        b = _tokens(e)
        if b and len(a & b) / len(a | b) >= threshold:
            return True
    return False


def generate_ideas(db: Session, ctx: CallContext, user_id: str, *, category: str, count: int = 5, channel_id: str | None = None,
                   trends: list[dict] | None = None, language: str = "tr", priors: dict | None = None) -> list[Idea]:
    existing = [t for (t,) in db.execute(select(Idea.title).where(Idea.user_id == user_id).order_by(Idea.created_at.desc()).limit(300))]
    existing += [t for (t,) in db.execute(select(Project.topic).where(Project.user_id == user_id).order_by(Project.created_at.desc()).limit(300))]
    trend_txt = "\n".join(f"- {t['title']} (kaynak: {t['source']}, metrik: {json.dumps(t['metrics'], ensure_ascii=False)})"
                          for t in (trends or [])[:15]) or "(gerçek trend verisi yok — genel bilgiye dayan, trend uydurma)"
    prior_txt = ""
    if priors and priors.get("insights"):
        prior_txt = "\nGeçmiş performanstan ölçülmüş içgörüler (yeterli veri varsa):\n" + "\n".join(f"- {x}" for x in priors["insights"][:6])
    system = ("Sen kısa dikey video (Shorts/Reels/TikTok) için içerik stratejistisin. Özgün, doğrulanabilir, yanıltıcı olmayan fikirler üret. "
              "Telifli karakter/marka içeriği, gerçek kişilerin taklidi, uydurma bilgi, yanıltıcı başlık ÖNERME. Yalnızca JSON döndür.")
    user = (f"Kategori: {category}\nDil: {LANG_NAME.get(language, language)}\nİstenen fikir sayısı: {count + 3}\n"
            f"Gerçek trend girdileri (yalnızca bunlardan ilham al, yoksa uydurma):\n{trend_txt}{prior_txt}\n\n"
            "Daha önce kullanılan başlıklar (tekrar etme):\n" + "\n".join(f"- {t}" for t in existing[:25]) +
            '\n\nŞema: {"ideas":[{"title":"","angle":"","audience":"","format":"listicle|explainer|story|comparison|myth-busting",'
            '"score":0-100,"reason":"puanın gerekçesi"}]}')
    out = _llm(ctx, LLMRequest(system=system, user=user, max_tokens=2500, task="ideas",
                               params={"category": category, "count": count + 3, "trends": trends or []}),
               ctx.settings.get("providers", {}).get("llm", ["openai", "anthropic", "compat", "template"]), user_id, None)
    try:
        raw = parse_json(out.result.data).get("ideas", [])
    except (json.JSONDecodeError, AttributeError) as e:
        raise AppError("Fikir yanıtı ayrıştırılamadı", code="llm_parse") from e
    is_ai = router.get("llm", out.provider).is_ai  # type: ignore[union-attr]
    ideas: list[Idea] = []
    for r in raw:
        title = str(r.get("title", "")).strip()
        if len(title) < 5 or is_duplicate(title, existing + [i.title for i in ideas]):
            continue
        base = float(min(max(r.get("score", 50), 0), 100))
        prior = (priors or {}).get("category_factor", {}).get(category, 1.0)
        score = round(min(base * prior, 100), 1)
        idea = Idea(user_id=user_id, channel_id=channel_id, category=category, title=title[:300], angle=str(r.get("angle", ""))[:1000],
                    audience=str(r.get("audience", ""))[:300], format=str(r.get("format", ""))[:60], score=score,
                    score_detail={"llm_score": base, "performance_prior": prior, "reason": r.get("reason", "")},
                    fingerprint=fingerprint(title), status="new",
                    source={"provider": out.provider, "is_ai": is_ai, "trends": [t["title"] for t in (trends or [])[:5]]})
        db.add(idea)
        ideas.append(idea)
        if len(ideas) >= count:
            break
    db.commit()
    return ideas


# ---------- senaryo ----------
def scene_count(duration: int) -> int:
    return int(min(max(round(duration / 5.5), 3), 12))


def generate_script(ctx: CallContext, user_id: str, project_id: str, *, topic: str, category: str, language: str, style: str,
                    duration: int, options: dict, trends: list[dict] | None = None) -> tuple[dict, str, bool]:
    n = scene_count(duration)
    words = int(duration * (2.3 if language == "tr" else 2.7))
    hook_style = options.get("hook_style")
    title_style = options.get("title_style")
    system = ("Sen kısa dikey sosyal medya videoları için deneyimli bir senarist ve araştırmacısın. KURALLAR: özgün içerik yaz; uydurma bilgi, "
              "yanıltıcı/clickbait başlık, telifli karakter-marka-müzik-ünlü taklidi yok; belirsiz/doğrulanmamış bilgiyi açıkça 'söylentidir' diye "
              "belirt ve facts_to_verify listesine yaz; finans/sağlık konularında yatırım/tıbbi tavsiye verme ve uyarı ekle. "
              "Anlatım metni seslendirilecek: kısa cümleler, noktalama doğru, sayı ve kısaltmaları okunacak biçimde yaz. "
              "visual_prompt HER ZAMAN İngilizce, sahneyi somut anlatan (özne, ortam, kamera, ışık), görsel içinde yazı/logo/filigran OLMAYAN istemdir. "
              "Yalnızca geçerli JSON döndür.")
    ctx_txt = ""
    if trends:
        ctx_txt = "\nGerçek trend bağlamı (varsa kullan, uydurma):\n" + "\n".join(f"- {t['title']}" for t in trends[:6])
    user = (f"Konu: {topic}\nKategori: {category}\nDil (anlatım/başlık/açıklama): {LANG_NAME.get(language, language)}\nGörsel stil: {style}\n"
            f"Hedef süre: {duration} sn → {n} sahne, toplam ~{words} kelime anlatım.\n"
            + (f"Hook stili: {hook_style}\n" if hook_style else "") + (f"Başlık stili: {title_style}\n" if title_style else "")
            + ctx_txt +
            "\nİlk sahne güçlü bir hook ile başlasın (ilk 2 saniyede merak/değer). Son sahne CTA içersin.\n"
            'Şema: {"title":"≤80 karakter, dürüst","hook":"","scenes":[{"narration":"","visual_prompt":"(EN)","camera":"","lighting":"",'
            '"composition":"","transition":"fade|dissolve|slide|wipe|zoom|circle","on_screen_text":"","stock_query":"2-4 İngilizce anahtar kelime"}],'
            '"cta":"","description":"","hashtags":["#"],"style_bible":"tüm sahnelerde tutarlı karakter/mekân/renk tarifi (EN)",'
            '"facts_to_verify":[""],"claims_risk":"low|medium|high","sources":[""]}')
    prefs = ctx.settings.get("providers", {}).get("llm", ["openai", "anthropic", "compat", "template"])
    last_err = ""
    for attempt in range(2):
        out = _llm(ctx, LLMRequest(system=system, user=user + (f"\n\nÖnceki yanıt geçersizdi: {last_err}. Şemaya tam uy." if last_err else ""),
                                   max_tokens=4000, task="script",
                                   params={"topic": topic, "style": style, "duration": duration}), prefs, user_id, project_id)
        try:
            data = ScriptModel.model_validate(parse_json(out.result.data)).model_dump()
            is_ai = router.get("llm", out.provider).is_ai  # type: ignore[union-attr]
            return data, out.provider, is_ai
        except (json.JSONDecodeError, ValidationError, AttributeError) as e:
            last_err = str(e)[:300]
    raise AppError(f"Senaryo geçerli biçimde üretilemedi: {last_err}", code="script_invalid")


# ---------- storyboard ----------
def build_storyboard(script: dict, *, style: str, aspect_ratio: str, project_id: str, language: str) -> dict:
    """Sahne başına tam görsel istemi + çekim bilgisi. Karakter tutarlılığı: stil kılavuzu + sabit seed."""
    seed = int(hashlib.sha256(project_id.encode()).hexdigest()[:8], 16)
    bible = script.get("style_bible", "")
    shots = []
    for i, sc in enumerate(script["scenes"]):
        prompt = (f"{sc['visual_prompt'].strip().rstrip('.')}. {bible} Camera: {sc.get('camera', '')}. Lighting: {sc.get('lighting', '')}. "
                  f"Composition: {sc.get('composition', '')}. {STYLE_TOKENS.get(style, STYLE_TOKENS['cinematic'])}. "
                  f"{'Vertical 9:16' if aspect_ratio == '9:16' else 'Horizontal 16:9' if aspect_ratio == '16:9' else 'Square 1:1'} frame, "
                  "no text, no watermark, no logos, no real people likeness").strip()
        cam = (sc.get("camera") or "").lower()
        motion = ("zoom_out" if "pull" in cam or "out" in cam else "pan_right" if "pan" in cam or "track" in cam else "zoom_in")
        shots.append({"idx": i, "image_prompt": prompt[:3800], "video_prompt": (sc["visual_prompt"] + ". Camera: " + sc.get("camera", ""))[:900],
                      "camera": sc.get("camera", ""), "lighting": sc.get("lighting", ""), "composition": sc.get("composition", ""),
                      "motion": motion, "transition": sc.get("transition", "fade"), "aspect_ratio": aspect_ratio, "seed": seed,
                      "stock_query": sc.get("stock_query", "")})
    return {"seed": seed, "style": style, "style_bible": bible, "shots": shots, "language": language}


# ---------- AI güvenlik incelemesi ----------
def safety_review_fn(ctx: CallContext, user_id: str, project_id: str):
    """QC için: yalnızca GERÇEK bir AI sağlayıcı varsa inceleme yapar; yoksa None (QC bunu risk bayrağı yapar)."""
    def fn(payload: dict) -> dict | None:
        system = ("Sen bir içerik güvenliği ve doğruluk denetçisisin. Verilen kısa video metnini; nefret, şiddet, cinsel içerik, kendine zarar, tehlikeli "
                  "talimat, yanıltıcı/doğrulanmamış iddia, telif/marka ihlali ve çocuklar için uygunsuzluk açısından değerlendir. Yalnızca JSON döndür.")
        user = (f"Kategori: {payload.get('category')}\nBaşlık: {payload.get('title')}\nMetin:\n{payload.get('text')}\n\n"
                'Şema: {"flagged":bool,"severity":"none|low|medium|high|critical","misleading":bool,"reasons":["..."]}')
        out = router.run("llm", ctx, LLMRequest(system=system, user=user, max_tokens=500, task="moderation", json_mode=True),
                         preferred=ctx.settings.get("providers", {}).get("llm", ["openai", "anthropic", "compat"]), only_ai=True,
                         db_factory=session_scope, guard=budget_guard(user_id, project_id))
        d = parse_json(out.result.data)
        d["provider"] = out.provider
        return d
    def safe(payload: dict) -> dict | None:
        try:
            return fn(payload)
        except router.ProviderExhausted:
            return None
    return safe
