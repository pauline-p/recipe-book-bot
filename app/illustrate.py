"""Наклейки-иллюстрации блюд: ИИ рисует блюдо по описанию в стиле образцов из webapp/stickers."""
import asyncio
import io
import logging
import secrets

from . import config, db

log = logging.getLogger(__name__)

PROMPT = """Draw a single sticker illustration of this dish: {title}. {description}
Main ingredients: {ingredients}.

Style: exactly like the reference stickers — top-down view of the food on a round light-grey ceramic plate
(or a bowl for soups), glossy semi-flat vector illustration, soft gradients, crisp shapes, small white
highlights, appetizing warm colours, a thick white sticker border around the plate with a thin soft
blue-grey outline outside it.
Composition: one plate, centered, filling about 85% of a square image, nothing cropped.
Background: one solid flat pure green colour #00FF00 everywhere around the sticker, no shadows on it,
no texture, no gradient. No text, no hands, no cutlery, no table."""

_running: set[tuple[int, int]] = set()


def _refs() -> list[bytes]:
    return [p.read_bytes() for p in sorted((config.WEBAPP_DIR / "stickers").glob("ref-*.png"))]


def cut_out(png: bytes) -> bytes:
    """Убирает зелёный фон, обрезает по краю и сохраняет в webp 512 px."""
    import numpy as np
    from PIL import Image

    im = Image.open(io.BytesIO(png)).convert("RGBA")
    a = np.asarray(im).astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    greenness = g - np.maximum(r, b)
    alpha = np.clip(255 - (greenness - 40) * 4, 0, 255)          # плавный край
    alpha = np.where(greenness < 40, 255, alpha)
    # убираем зелёный отсвет на краях
    g2 = np.where(greenness > 0, np.maximum(r, b) + greenness // 4, g)
    out = np.stack([r, np.minimum(g, g2), b, np.minimum(alpha, a[..., 3])], -1).astype(np.uint8)
    im = Image.fromarray(out, "RGBA")
    box = im.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
    if box:
        im = im.crop(box)
    side = max(im.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
    canvas = canvas.resize((512, 512), Image.LANCZOS)
    buf = io.BytesIO()
    canvas.save(buf, "WEBP", quality=86)
    return buf.getvalue()


async def _draw(recipe: dict) -> bytes:
    from google.genai import types

    from .ai import _gemini_client
    client = _gemini_client()   # 90 секунд и одна повторная попытка, чтобы не висеть минутами
    names = ", ".join(i["name"] for i in recipe.get("ingredients", [])[:8])
    prompt = PROMPT.format(title=recipe["title"], description=recipe.get("description") or "",
                           ingredients=names or "—")
    contents = [types.Part.from_bytes(data=b, mime_type="image/png") for b in _refs()] + [prompt]
    resp = await client.aio.models.generate_content(
        model=config.IMAGE_MODEL, contents=contents,
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )
    for cand in resp.candidates or []:
        for part in (cand.content.parts if cand.content else []) or []:
            if part.inline_data and part.inline_data.data:
                return part.inline_data.data
    raise RuntimeError("модель не вернула картинку")


async def generate(user_id: int, rid: int) -> None:
    key = (user_id, rid)
    if key in _running:
        return
    _running.add(key)
    try:
        r = db.get(user_id, rid)
        if not r:
            return
        db.set_image(user_id, rid, r.get("image", ""), "pending")
        raw = await _draw(r)
        data = await asyncio.to_thread(cut_out, raw)
        config.IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{secrets.token_urlsafe(12)}.webp"
        (config.IMAGES_DIR / name).write_bytes(data)
        old = r.get("image")
        db.set_image(user_id, rid, name, "ready")
        if old and old != name:
            (config.IMAGES_DIR / old).unlink(missing_ok=True)
    except Exception:
        log.exception("illustration failed for recipe %s", rid)
        r = db.get(user_id, rid)
        db.set_image(user_id, rid, (r or {}).get("image", ""), "failed")
    finally:
        _running.discard(key)


def enabled() -> bool:
    return config.ILLUSTRATIONS and bool(config.GEMINI_API_KEY)


def schedule(user_id: int, rid: int) -> None:
    """Запускает рисование в фоне. Можно вызывать откуда угодно внутри работающей программы."""
    if not enabled():
        return
    try:
        asyncio.get_running_loop().create_task(generate(user_id, rid))
    except RuntimeError:
        pass


def schedule_missing(user_id: int, recipes: list[dict]) -> None:
    """Дорисовывает наклейки рецептам, у которых их ещё нет (например, добавленным в чате).
    Заодно снимает «рисую…», если рисование прервалось (перезапуск, выключили наклейки)."""
    for r in recipes:
        status = r.get("image_status") or ""
        stuck = status == "pending" and (user_id, r["id"]) not in _running
        if stuck and not enabled():
            db.set_image(user_id, r["id"], r.get("image", ""), "failed")
            r["image_status"] = "failed"
        elif enabled() and (stuck or (not status and not r.get("image"))):
            r["image_status"] = "pending"
            schedule(user_id, r["id"])
