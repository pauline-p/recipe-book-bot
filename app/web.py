"""Сервер для приложения внутри Телеграма (Mini App) и его API."""
import hashlib
import hmac
import json
import logging
import re
import time
from urllib.parse import parse_qsl

from aiohttp import web

from . import access, photos, ai, config, db, illustrate

log = logging.getLogger(__name__)


def user_from_init_data(init_data: str) -> int | None:
    """Проверяет подпись Телеграма и возвращает id пользователя."""
    if not init_data:
        return None
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received):
        return None
    if time.time() - int(pairs.get("auth_date", 0)) > 7 * 24 * 3600:
        return None
    try:
        return int(json.loads(pairs["user"])["id"])
    except (KeyError, ValueError):
        return None


@web.middleware
async def auth(request: web.Request, handler):
    if not request.path.startswith("/api/"):
        return await handler(request)
    uid = user_from_init_data(request.headers.get("X-Init-Data", ""))
    if uid is None and config.DEV_USER_ID:
        uid = config.DEV_USER_ID
    if uid is None or not access.allowed(uid):
        return web.json_response({"error": "Открой книгу из Телеграма."}, status=401)
    request["uid"] = uid
    try:
        return await handler(request)
    except (ai.AIError, access.LimitError) as e:
        return web.json_response({"error": str(e)}, status=422)
    except web.HTTPException:
        raise
    except Exception:
        log.exception("api failed: %s", request.path)
        return web.json_response({"error": "Что-то сломалось на сервере. Попробуй ещё раз."}, status=500)


def rid(request) -> int:
    return int(request.match_info["rid"])


async def list_recipes(request):
    items = db.list_all(request["uid"], request.query.get("q", ""))
    illustrate.schedule_missing(request["uid"], items)
    return web.json_response(items)


async def meta(request):
    return web.json_response({"illustrations": illustrate.enabled()})


async def redraw(request):
    if not illustrate.enabled():
        return web.json_response({"error": "Рисование наклеек выключено: нужен ключ Gemini с оплатой."}, status=400)
    r = db.get(request["uid"], rid(request))
    if not r:
        return web.json_response({"error": "Не найден"}, status=404)
    db.set_image(request["uid"], r["id"], r.get("image", ""), "pending")
    illustrate.schedule(request["uid"], r["id"])
    return web.json_response(db.get(request["uid"], r["id"]))


async def set_pos(request):
    body = await request.json()
    r = db.set_pos(request["uid"], rid(request), None if body.get("reset") else body)
    return web.json_response(r) if r else web.json_response({"error": "Не найден"}, status=404)


async def upload_photo(request):
    data = await request.read()
    if not data:
        return web.json_response({"error": "Фото не пришло, попробуй ещё раз."}, status=400)
    try:
        return web.json_response(photos.save(request["uid"], rid(request), data))
    except photos.PhotoError as e:
        return web.json_response({"error": str(e)}, status=400)


async def image(request):
    name = request.match_info["name"]
    path = config.IMAGES_DIR / name
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,40}\.webp", name) or not path.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable"})


async def get_recipe(request):
    r = db.get(request["uid"], rid(request))
    return web.json_response(r) if r else web.json_response({"error": "Не найден"}, status=404)


async def create_recipe(request):
    data = await request.json()
    await ai.fill_nutrition(data.get("ingredients", []))
    r = db.add(request["uid"], data)
    illustrate.schedule(request["uid"], r["id"])
    return web.json_response(r)


async def update_recipe(request):
    data = await request.json()
    old = db.get(request["uid"], rid(request))
    if not old:
        return web.json_response({"error": "Не найден"}, status=404)
    # Новые или переименованные ингредиенты приходят без КБЖУ — дозаполним
    await ai.fill_nutrition(data.get("ingredients", []))
    data.setdefault("source", old.get("source", ""))
    return web.json_response(db.update(request["uid"], rid(request), data))


async def delete_recipe(request):
    db.delete(request["uid"], rid(request))
    return web.json_response({"ok": True})


async def parse_text(request):
    body = await request.json()
    text = str(body.get("text", "")).strip()
    if not text:
        return web.json_response({"error": "Вставь текст рецепта."}, status=400)
    access.spend_ai(request["uid"])
    data = await ai.parse_recipe([ai.Part("text", text=text)])
    data["source"] = text
    await ai.fill_nutrition(data.get("ingredients", []))
    r = db.add(request["uid"], data)
    illustrate.schedule(request["uid"], r["id"])
    return web.json_response(r)


async def index(request):
    return web.FileResponse(config.WEBAPP_DIR / "index.html",
                            headers={"Cache-Control": "no-cache"})


def create() -> web.Application:
    app = web.Application(middlewares=[auth], client_max_size=5 * 1024 * 1024)
    app.router.add_get("/", index)
    app.router.add_get("/api/recipes", list_recipes)
    app.router.add_post("/api/recipes", create_recipe)
    app.router.add_post("/api/parse", parse_text)
    app.router.add_get("/api/recipes/{rid:\\d+}", get_recipe)
    app.router.add_put("/api/recipes/{rid:\\d+}", update_recipe)
    app.router.add_delete("/api/recipes/{rid:\\d+}", delete_recipe)
    app.router.add_post("/api/recipes/{rid:\\d+}/illustration", redraw)
    app.router.add_get("/api/meta", meta)
    app.router.add_post("/api/recipes/{rid:\\d+}/photo", upload_photo)
    app.router.add_put("/api/recipes/{rid:\\d+}/pos", set_pos)
    app.router.add_get("/img/{name}", image)
    app.router.add_static("/static", config.WEBAPP_DIR)
    app.router.add_get("/health", lambda r: web.Response(text="ok"))
    return app
