"""Фото готового блюда: обрезаем в квадрат, уменьшаем и кладём рядом с базой."""
import io
import secrets

from PIL import Image, ImageOps

from . import config, db

SIZE = 900


class PhotoError(Exception):
    pass


def save(user_id: int, rid: int, data: bytes) -> dict:
    r = db.get(user_id, rid)
    if not r:
        raise PhotoError("Не нашла этот рецепт.")
    try:
        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im).convert("RGB")
    except Exception as e:
        raise PhotoError("Не получилось открыть картинку. Пришли обычное фото.") from e
    im = ImageOps.fit(im, (SIZE, SIZE), Image.LANCZOS)
    name = f"photo_{rid}_{secrets.token_hex(6)}.webp"
    config.IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    im.save(config.IMAGES_DIR / name, "WEBP", quality=82)
    old = r.get("image")
    db.set_image(user_id, rid, name, "photo")
    if old and old != name:
        (config.IMAGES_DIR / old).unlink(missing_ok=True)
    return db.get(user_id, rid)
