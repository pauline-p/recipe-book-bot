"""Хранилище рецептов: один файл SQLite в папке DATA_DIR."""
import json
import sqlite3
import time

from . import config
from . import icons
from .nutrition import compute

FIELDS = ("title", "description", "servings", "ingredients", "steps", "notes", "tips", "tags",
          "cooked_weight", "source", "image", "image_status")
# Поля наклейки ставит только сервер; при правке рецепта их переносим из старой версии
IMAGE_FIELDS = ("image", "image_status")


def conn() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.DATA_DIR / "recipes.db")
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS recipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            created REAL NOT NULL,
            updated REAL NOT NULL)""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_user ON recipes(user_id)")
        # Друзья, которых пустили по приглашению (у каждого своя книга)
        c.execute("""CREATE TABLE IF NOT EXISTS members (
            user_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            invited_by INTEGER,
            joined REAL NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS invites (
            code TEXT PRIMARY KEY,
            created_by INTEGER NOT NULL,
            created REAL NOT NULL,
            used_by INTEGER)""")
        # Сколько раз за день человек просил ИИ разобрать рецепт
        c.execute("""CREATE TABLE IF NOT EXISTS ai_usage (
            user_id INTEGER NOT NULL,
            day TEXT NOT NULL,
            count INTEGER NOT NULL,
            PRIMARY KEY (user_id, day))""")


def clean(data: dict) -> dict:
    """Оставляет только известные поля и приводит их к нужному виду."""
    out = {
        "title": str(data.get("title") or "Без названия").strip()[:200],
        "description": str(data.get("description") or "").strip()[:500],
        "servings": data.get("servings") or None,
        "ingredients": [],
        "steps": [str(s).strip() for s in (data.get("steps") or []) if str(s).strip()],
        "notes": str(data.get("notes") or "").strip(),
        "tips": [str(t).strip() for t in (data.get("tips") or []) if str(t).strip()][:8],
        "tags": [str(t).strip().lower() for t in (data.get("tags") or []) if str(t).strip()][:8],
        "cooked_weight": data.get("cooked_weight") or None,
        "source": str(data.get("source") or "").strip()[:4000],
        "image": str(data.get("image") or "")[:80],
        "image_status": str(data.get("image_status") or "")[:20],
    }
    for ing in data.get("ingredients") or []:
        name = str(ing.get("name") or "").strip()
        if not name:
            continue
        item = {"name": name, "amount": str(ing.get("amount") or "").strip(),
                "icon": icons.pick(name, ing.get("icon"))}
        for k in ("grams", "kcal", "protein", "fat", "carbs"):
            try:
                item[k] = round(float(ing.get(k)), 1) if ing.get(k) not in (None, "") else None
            except (TypeError, ValueError):
                item[k] = None
        out["ingredients"].append(item)
    try:
        out["cooked_weight"] = float(out["cooked_weight"]) if out["cooked_weight"] else None
    except (TypeError, ValueError):
        out["cooked_weight"] = None
    out["pos"] = clean_pos(data.get("pos"))
    return out


def clean_pos(pos) -> dict | None:
    """Куда тарелку перетащили на главном экране: x в % ширины, y в пикселях."""
    try:
        x, y = float(pos["x"]), float(pos["y"])
    except (TypeError, KeyError, ValueError):
        return None
    return {"x": round(max(-10.0, min(90.0, x)), 2), "y": round(max(-20.0, min(50000.0, y)), 1)}


def _row(r: sqlite3.Row) -> dict:
    d = json.loads(r["data"])
    d.setdefault("tips", [])
    d.setdefault("description", "")
    d.setdefault("image", "")
    d.setdefault("image_status", "")
    for i in d.get("ingredients", []):
        if not i.get("icon"):
            i["icon"] = icons.pick(i.get("name", ""))
    d.update(id=r["id"], created=r["created"], updated=r["updated"])
    d["nutrition"] = compute(d)
    return d


def add(user_id: int, data: dict) -> dict:
    now = time.time()
    with conn() as c:
        cur = c.execute("INSERT INTO recipes(user_id, data, created, updated) VALUES (?,?,?,?)",
                        (user_id, json.dumps(clean(data), ensure_ascii=False), now, now))
        rid = cur.lastrowid
    return get(user_id, rid)


def get(user_id: int, rid: int) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM recipes WHERE id=? AND user_id=?", (rid, user_id)).fetchone()
    return _row(r) if r else None


def update(user_id: int, rid: int, data: dict, keep_image: bool = True) -> dict | None:
    if keep_image:
        old = get(user_id, rid)
        if old:
            data = {**data, **{k: old.get(k, "") for k in IMAGE_FIELDS}}
            data.setdefault("pos", old.get("pos"))
    with conn() as c:
        cur = c.execute("UPDATE recipes SET data=?, updated=? WHERE id=? AND user_id=?",
                        (json.dumps(clean(data), ensure_ascii=False), time.time(), rid, user_id))
    return get(user_id, rid) if cur.rowcount else None


def delete(user_id: int, rid: int) -> bool:
    old = get(user_id, rid)
    with conn() as c:
        ok = c.execute("DELETE FROM recipes WHERE id=? AND user_id=?", (rid, user_id)).rowcount > 0
    if ok and old and old.get("image"):
        (config.IMAGES_DIR / old["image"]).unlink(missing_ok=True)
    return ok


def set_pos(user_id: int, rid: int, pos) -> dict | None:
    """Запоминает место тарелки на главном экране (None — вернуть на место по умолчанию)."""
    with conn() as c:
        r = c.execute("SELECT data FROM recipes WHERE id=? AND user_id=?", (rid, user_id)).fetchone()
        if not r:
            return None
        d = json.loads(r["data"])
        d["pos"] = clean_pos(pos) if pos else None
        c.execute("UPDATE recipes SET data=? WHERE id=? AND user_id=?",
                  (json.dumps(d, ensure_ascii=False), rid, user_id))
    return get(user_id, rid)


def set_image(user_id: int, rid: int, image: str, status: str) -> None:
    """Записывает наклейку, не трогая остальной рецепт."""
    with conn() as c:
        r = c.execute("SELECT data FROM recipes WHERE id=? AND user_id=?", (rid, user_id)).fetchone()
        if not r:
            return
        d = json.loads(r["data"])
        d["image"], d["image_status"] = image, status
        c.execute("UPDATE recipes SET data=? WHERE id=? AND user_id=?",
                  (json.dumps(d, ensure_ascii=False), rid, user_id))


def list_all(user_id: int, query: str = "") -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM recipes WHERE user_id=? ORDER BY updated DESC",
                         (user_id,)).fetchall()
    items = [_row(r) for r in rows]
    q = query.strip().lower()
    if q:
        items = [r for r in items
                 if q in r["title"].lower()
                 or any(q in i["name"].lower() for i in r["ingredients"])
                 or any(q in t for t in r["tags"])]
    return items
