"""İstatistik/öğrenme motoru testleri. Girdi SENTETİK veridir (fonksiyonların doğruluğunu sınar; gerçek performans verisi değildir)."""
import random

from backend.analytics import learning, stats


def _rows(cat_means: dict, n: int, seed=1):
    rng = random.Random(seed)
    rows = []
    for cat, m in cat_means.items():
        for _ in range(n):
            rows.append({"category": cat, "platform": "youtube", "duration": 30.0, "hook_type": "soru", "hour": 12, "dow": 1,
                         "metric": "view_through", "score": max(rng.gauss(m, 0.04), 0), "views": 1000, "settled": True, "variant": "",
                         "experiment_id": None, "follow_rate": None})
    return rows


def test_no_claims_with_insufficient_data():
    res = learning.compute_insights(_rows({"Bilim": 0.5, "Oyun": 0.3}, n=3))
    assert res["sufficient"] is False
    assert all("anlamlı şekilde yüksek" not in i for i in res["insights"])
    assert res["category_factor"] == {}  # n<5: faktör üretilmez


def test_detects_real_difference_with_enough_data():
    res = learning.compute_insights(_rows({"Bilim": 0.55, "Oyun": 0.30}, n=15))
    assert res["sufficient"]
    assert res["category"][0]["group"] == "Bilim" and res["category"][0]["vs_next"]["conclusive"]
    assert any("Bilim" in i and "anlamlı" in i for i in res["insights"])
    assert res["category_factor"]["Bilim"] > 1 > res["category_factor"]["Oyun"]


def test_no_false_positive_on_identical_groups():
    flags = 0
    for seed in range(20):
        res = learning.compute_insights(_rows({"A": 0.4, "B": 0.4}, n=12, seed=seed))
        flags += bool(res["category"][0].get("vs_next", {}).get("conclusive"))
    assert flags <= 4  # alpha=0.1 civarı yanlış pozitif beklenir; sistematik sahte iddia yok


def test_permutation_and_ci():
    a, b = [0.5] * 10, [0.2] * 10
    assert stats.perm_test(a, b) < 0.01
    lo, hi = stats.bootstrap_ci([0.4, 0.5, 0.6, 0.5, 0.45, 0.55])
    assert lo < 0.5 < hi
    assert stats.confidence_label(3) == "yetersiz" and stats.confidence_label(25) == "iyi"


def test_hook_classifier():
    assert learning.hook_type("Biliyor muydun?") == "soru"
    assert learning.hook_type("5 gerçek var") == "sayı/liste"
    assert learning.hook_type("Güneş aslında bir yıldızdır") == "iddia/ifade"


def test_experiment_needs_views_and_samples(user, env):
    from backend.database.session import session_scope
    from backend.models import Experiment
    with session_scope() as db:
        ex = learning.create_experiment(db, user, "hook", None, min_views=500)
        r = learning.evaluate_experiment(db, ex)
        assert r["conclusive"] is False and "izlenme" in r["reason"]
