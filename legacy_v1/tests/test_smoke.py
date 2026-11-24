from backend.services.ai import make_script

def test_fallback_script_has_scenes(monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "openai_api_key", "")
    result = make_script("GTA 6 detayları", "Oyun", 30, "cinematic")
    assert result["title"]
    assert len(result["scenes"]) >= 3
    assert all("narration" in s and "visual" in s for s in result["scenes"])
