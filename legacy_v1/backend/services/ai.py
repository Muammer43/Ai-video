import json, base64, urllib.request, urllib.error
from pathlib import Path
from ..config import settings

def _post_json(url, payload, headers):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:1000]
        raise RuntimeError(f"AI provider HTTP {e.code}: {detail}") from e

def make_script(topic: str, category: str, duration: int, style: str) -> dict:
    if not settings.openai_api_key:
        # A deterministic fallback makes the full pipeline testable without paid credentials.
        return {
            "title": f"{topic[:65]} | Kısa video",
            "hook": f"{topic} hakkında çoğu kişinin gözden kaçırdığı nokta ne?",
            "scenes": [
                {"narration": f"Bugün {topic} konusuna hızlıca bakıyoruz.", "visual": f"{topic}, {style} style cinematic establishing shot"},
                {"narration": f"Önce en önemli ayrıntıyı anlayalım. Bu konu {category} açısından dikkat çekici.", "visual": f"Detailed cinematic close-up illustrating {topic}"},
                {"narration": "Şimdi bunun neden önemli olduğuna bakalım.", "visual": f"Dynamic visual metaphor for {topic}, dramatic lighting"},
                {"narration": "Özetle, ayrıntıları kaçırmamak gerekiyor. Sen bu konuda ne düşünüyorsun?", "visual": f"Strong cinematic closing image about {topic}"}
            ],
            "caption": f"{topic} hakkında kısa bir video. Sen ne düşünüyorsun?",
            "hashtags": ["#keşfet", "#shorts", "#video"]
        }
    prompt = f"""Türkçe dikey sosyal medya videosu için JSON senaryo üret.
Konu: {topic}; kategori: {category}; stil: {style}; hedef süre: {duration} saniye.
İzleyiciyi ilk 2 saniyede yakalayan güçlü ama yanıltıcı olmayan bir hook kullan.
4-7 sahne üret. Her sahnede kısa narration ve İngilizce visual prompt olsun.
Çıktı yalnızca şu JSON şemasına uysun:
{{"title":"", "hook":"", "scenes":[{{"narration":"","visual":""}}], "caption":"", "hashtags":["#"]}}
Telifli karakterleri, markalara ait korunan görsel stilleri veya gerçek kişilerin izinsiz taklidini isteme."""
    result = _post_json(
        "https://api.openai.com/v1/chat/completions",
        {"model": settings.openai_text_model, "response_format": {"type":"json_object"},
         "messages":[{"role":"system","content":"You are a careful short-form video scriptwriter."},
                    {"role":"user","content":prompt}], "temperature":0.7},
        {"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type":"application/json"}
    )
    return json.loads(result["choices"][0]["message"]["content"])

def make_image(prompt: str, path: Path) -> bool:
    if not settings.openai_api_key or not settings.use_ai_images:
        return False
    result = _post_json(
        "https://api.openai.com/v1/images/generations",
        {"model":settings.openai_image_model, "prompt":prompt + ", vertical 9:16 composition, no text, no watermark",
         "size":"1024x1536", "quality":"low", "n":1},
        {"Authorization":f"Bearer {settings.openai_api_key}", "Content-Type":"application/json"}
    )
    path.write_bytes(base64.b64decode(result["data"][0]["b64_json"]))
    return True

def make_voice(text: str, path: Path) -> bool:
    if not settings.openai_api_key or not settings.use_ai_voice:
        return False
    data = json.dumps({"model":settings.openai_tts_model, "voice":settings.openai_tts_voice,
                       "input":text, "response_format":"mp3"}).encode()
    req = urllib.request.Request("https://api.openai.com/v1/audio/speech", data=data,
        headers={"Authorization":f"Bearer {settings.openai_api_key}", "Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        path.write_bytes(r.read())
    return True
