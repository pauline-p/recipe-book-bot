"""Как рецепт выглядит в чате."""
from html import escape


def n(v: float) -> str:
    v = round(v or 0, 1)
    return str(int(v)) if v == int(v) else str(v).replace(".", ",")


def kbju_line(p: dict) -> str:
    return f"{n(round(p['kcal']))} ккал · Б {n(p['protein'])} · Ж {n(p['fat'])} · У {n(p['carbs'])}"


def card(r: dict, limit: int = 3900) -> str:
    nu = r["nutrition"]
    w = f"{nu['weight']} г" + (" готового" if nu["cooked"] else "")
    lines = [f"<b>{escape(r['title'])}</b>", "",
             f"<b>На 100 г:</b> {kbju_line(nu['per100'])}",
             f"Всё блюдо ({w}): {kbju_line(nu['total'])}"]
    if r.get("servings"):
        lines.append(f"Порций: {r['servings']}")
    lines += ["", "<b>Ингредиенты</b>"]
    for i in r["ingredients"]:
        amount = i.get("amount") or ""
        grams = f"{n(i['grams'])} г" if i.get("grams") else ""
        if amount and grams and amount.replace(" ", "") != grams.replace(" ", ""):
            q = f"{amount} ({grams})"
        else:
            q = amount or grams
        lines.append(f"— {escape(i['name'])}" + (f" — {escape(q)}" if q else ""))
    if r["steps"]:
        lines += ["", "<b>Приготовление</b>"]
        lines += [f"{k}. {escape(s)}" for k, s in enumerate(r["steps"], 1)]
    if r.get("tips"):
        lines += ["", "<b>Лайфхаки</b>"]
        lines += [f"— {escape(t)}" for t in r["tips"]]
    if r.get("notes"):
        lines += ["", f"<i>{escape(r['notes'])}</i>"]
    text = "\n".join(lines)
    if len(text) > limit:
        text = text[:limit].rsplit("\n", 1)[0] + "\n…\n\nПолностью — в приложении."
    return text
