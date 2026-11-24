"""Kural tabanlı içerik güvenliği / yanıltıcılık / telif sezgileri. Bunlar SEZGİSELDİR; insan incelemesinin yerini tutmaz."""
from __future__ import annotations

import re

BLOCKED = {
    "terör/silah talimatı": r"bomba\s*yap|patlayıcı\s*yap|how\s+to\s+make\s+a\s+bomb|build\s+a\s+bomb",
    "kendine zarar": r"intihar\s*(yöntem|nasıl)|how\s+to\s+(commit\s+)?suicide|suicide\s+methods",
    "çocuk istismarı": r"çocuk\s*(istismar|porno)|child\s+(porn|sexual)",
}
MISLEADING = {
    "garanti kazanç": r"garanti\s*kazan|kesin\s*kazan|%\s*100\s*(garanti|etkili)|guaranteed\s+(profit|returns?)",
    "mucize/gizleme iddiası": r"mucize\s*tedavi|doktorlar\s*(bunu\s*)?gizliyor|doctors\s+hate|miracle\s+cure",
    "doğrulanmamış sızıntı": r"kesin\s*doğrulandı|sızdırıldı|leaked\s+(footage|trailer)|%\s*100\s*gerçek",
    "aldatıcı başlık": r"inanamayacaks|şok\s*(edici|oldu)?\s*gerçek|you\s+won'?t\s+believe",
}
SENSITIVE = {
    "finans": r"yatırım|hisse|borsa|kripto|bitcoin|forex|investment|stock\s+market|crypto",
    "sağlık": r"tedavi|kanser|ilaç|hastalık|diyet|treatment|cancer|medicine|disease",
    "siyaset": r"seçim|siyasi|parti\s|cumhurbaşkan|election|political",
    "çocuklar": r"çocuklar için|kids|minors|çocuk\s*(video|içerik)",
}
PROTECTED_IP = [
    "mickey mouse", "disney", "marvel", "spider-man", "spiderman", "batman", "superman", "harry potter", "star wars", "pokemon",
    "pokémon", "nintendo", "super mario", "pikachu", "hello kitty", "frozen elsa", "minecraft steve", "fortnite skin",
    "naruto", "dragon ball", "one piece luffy", "lord of the rings", "hobbit",
]
BRAND_TERMS = ["rockstar", "gta", "playstation", "xbox", "apple", "tesla", "samsung", "google", "nvidia", "bmw", "mercedes", "ferrari"]


def scan_text(text: str) -> dict:
    t = text.lower()
    out = {"blocked": [], "misleading": [], "sensitive": [], "ip": [], "brands": []}
    for name, pat in BLOCKED.items():
        if re.search(pat, t):
            out["blocked"].append(name)
    for name, pat in MISLEADING.items():
        if re.search(pat, t):
            out["misleading"].append(name)
    for name, pat in SENSITIVE.items():
        if re.search(pat, t):
            out["sensitive"].append(name)
    out["ip"] = [n for n in PROTECTED_IP if n in t]
    out["brands"] = [b for b in BRAND_TERMS if re.search(rf"\b{re.escape(b)}\b", t)]
    return out
