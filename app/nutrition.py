"""Подсчёт КБЖУ. ИИ даёт значения на 100 г каждого продукта, а итог считаем сами."""

KEYS = ("kcal", "protein", "fat", "carbs")


def _num(v) -> float:
    try:
        return max(float(v), 0.0)
    except (TypeError, ValueError):
        return 0.0


def compute(recipe: dict) -> dict:
    """Возвращает {'total': {...}, 'per100': {...}, 'weight': г, 'raw_weight': г}."""
    total = dict.fromkeys(KEYS, 0.0)
    raw_weight = 0.0
    for ing in recipe.get("ingredients", []):
        g = _num(ing.get("grams"))
        raw_weight += g
        for k in KEYS:
            total[k] += _num(ing.get(k)) * g / 100
    cooked = _num(recipe.get("cooked_weight"))
    weight = cooked or raw_weight
    per100 = {k: (total[k] * 100 / weight if weight else 0.0) for k in KEYS}
    return {
        "total": {k: round(v, 1) for k, v in total.items()},
        "per100": {k: round(v, 1) for k, v in per100.items()},
        "weight": round(weight),
        "raw_weight": round(raw_weight),
        "cooked": bool(cooked),
    }
