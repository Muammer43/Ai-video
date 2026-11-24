"""Küçük örneklem dostu, bağımlılıksız istatistik yardımcıları (deterministik tohum)."""
from __future__ import annotations

import math
import random
from statistics import mean

MIN_GROUP = 5  # herhangi bir grup için asgari gözlem
MIN_COMPARE = 8  # iki grubu karşılaştırıp 'daha iyi' demek için grup başına asgari gözlem


def confidence_label(n: int) -> str:
    if n < MIN_GROUP:
        return "yetersiz"
    if n < 10:
        return "düşük"
    if n < 20:
        return "orta"
    return "iyi"


def bootstrap_ci(xs: list[float], level: float = 0.9, n_boot: int = 2000, seed: int = 7) -> tuple[float, float]:
    rng = random.Random(seed)
    k = len(xs)
    means = sorted(mean(rng.choices(xs, k=k)) for _ in range(n_boot))
    lo = means[int(((1 - level) / 2) * n_boot)]
    hi = means[min(int((1 - (1 - level) / 2) * n_boot), n_boot - 1)]
    return lo, hi


def perm_test(a: list[float], b: list[float], n_perm: int = 10000, seed: int = 11) -> float:
    """İki yönlü permütasyon testi (ortalama farkı). Küçük örneklemde normal varsayımı gerektirmez."""
    obs = abs(mean(a) - mean(b))
    pool = a + b
    na = len(a)
    rng = random.Random(seed)
    hits = 0
    for _ in range(n_perm):
        rng.shuffle(pool)
        if abs(mean(pool[:na]) - mean(pool[na:])) >= obs - 1e-12:
            hits += 1
    return (hits + 1) / (n_perm + 1)


def describe(xs: list[float]) -> dict:
    n = len(xs)
    if n == 0:
        return {"n": 0, "mean": None, "ci90": None, "confidence": "yetersiz"}
    m = mean(xs)
    ci = bootstrap_ci(xs) if n >= MIN_GROUP else None
    return {"n": n, "mean": round(m, 5), "ci90": [round(ci[0], 5), round(ci[1], 5)] if ci else None, "confidence": confidence_label(n)}


def compare(a: list[float], b: list[float], alpha: float = 0.1) -> dict:
    if len(a) < MIN_COMPARE or len(b) < MIN_COMPARE:
        return {"conclusive": False, "reason": f"karşılaştırma için grup başına en az {MIN_COMPARE} gözlem gerekir (şu an {len(a)} ve {len(b)})"}
    p = perm_test(a, b)
    return {"conclusive": p < alpha, "p_value": round(p, 4), "diff": round(mean(a) - mean(b), 5),
            "reason": "" if p < alpha else f"fark istatistiksel olarak anlamlı değil (p={p:.2f})"}
