"""Разбор рецептов с помощью ИИ: текст, скриншоты, голосовые."""
import base64
import json
import re
from dataclasses import dataclass

from . import config, icons

RECIPE_SCHEMA = """{
  "is_recipe": true,
  "reason": "если не рецепт — коротко почему, иначе пусто",
  "title": "Название блюда",
  "description": "Как блюдо выглядит, одной фразой: румяные сырники со сметаной и ягодами",
  "servings": 4,
  "tags": ["завтрак", "выпечка"],
  "ingredients": [
    {"name": "Мука пшеничная", "amount": "1,5 стакана", "grams": 195, "icon": "sheaf_of_rice",
     "kcal": 334, "protein": 10.3, "fat": 1.1, "carbs": 69.9}
  ],
  "steps": ["Первый шаг", "Второй шаг"],
  "notes": "Заметки из оригинала: замены, время готовки — если есть",
  "tips": ["Если творог водянистый, отожми его руками — марля не нужна"],
  "cooked_weight": null
}"""

ICON_RULE = ("- \"icon\" — ключ иконки продукта из списка: {keys}. Выбери самую похожую по виду "
             "(крупы и мука — sheaf_of_rice, соусы и специи в банке — jar). Только ключ из списка.")

RULES = f"""Ты помогаешь вести личную книгу рецептов. Отвечай только JSON без пояснений, строго в таком виде:
{RECIPE_SCHEMA}

Правила:
- Всё на русском языке. Текст рецепта не выдумывай: бери из того, что прислали. Можно чуть причесать формулировки шагов.
- "amount" — количество как в оригинале ("2 ст. л.", "1 шт.", "по вкусу").
- "grams" — то же количество в граммах (оцени: 1 яйцо ≈ 55 г, 1 ст. л. сахара ≈ 25 г, 1 стакан муки ≈ 130 г, 1 ст. л. масла ≈ 17 г, "по вкусу" для соли ≈ 3 г, для специй ≈ 1 г). Жидкости в мл считай в граммах.
- "kcal", "protein", "fat", "carbs" — калории и белки/жиры/углеводы НА 100 Г этого продукта в сыром виде, по стандартным таблицам калорийности. Это значения продукта, а не блюда.
- "description" — как блюдо выглядит на тарелке, одной короткой фразой (по ней рисуется картинка).
{{ICON_RULE}}
- "cooked_weight" — вес готового блюда в граммах, только если он прямо указан, иначе null.
- "servings" — число порций, если указано, иначе null.
- "tags" — ОБЯЗАТЕЛЬНО 1–3 коротких метки (например: завтрак, суп, десерт, выпечка, салат, ужин, перекус).
- "tips" — лайфхаки к ЭТОМУ блюду: 1–3 коротких практичных совета из твоих знаний (здесь можно и нужно добавлять своё, это исключение из правила «не выдумывай»), обращение на «ты», которые спасают от типичных ошибок или упрощают готовку (как в примере про творог). Только там, где это правда полезно; банальности вроде «используйте свежие продукты» не пиши. Пустой список — только для совсем простых вещей вроде бутерброда. Если в оригинале уже есть советы, перенеси их сюда.
- Если на скриншотах есть чужие КБЖУ, игнорируй их — мы считаем сами.
- Если прислано несколько скриншотов, это один рецепт по частям.
- Если в сообщении нет рецепта (нет ингредиентов или способа приготовления), верни "is_recipe": false и "reason"."""

EDIT_RULES = f"""Ты помогаешь вести личную книгу рецептов. Тебе дают рецепт в JSON и просьбу его изменить.
Верни ПОЛНЫЙ обновлённый рецепт в том же виде, только JSON без пояснений:
{RECIPE_SCHEMA}

Правила те же: граммы у каждого ингредиента, КБЖУ продукта на 100 г, всё по-русски.
{{ICON_RULE}}
Меняй только то, о чём просят, остальное оставь как было (включая "tips").
Если просят добавить лайфхак или совет, добавь его в "tips" своими словами на «ты»; если похожий совет уже есть, объедини их в один, без повторов. Если просят «добавь лайфхаки», придумай 1–3 полезных к этому блюду. "is_recipe" всегда true.
Если просят указать вес готового блюда, запиши его в "cooked_weight"."""

FILL_RULES = """Для каждого продукта из списка укажи калорийность и БЖУ на 100 г в сыром виде по стандартным таблицам.
Если у продукта не указаны граммы, но есть количество, оцени граммы. Ответ только JSON:
{"items": [{"name": "...", "grams": 100, "icon": "jar", "kcal": 0, "protein": 0, "fat": 0, "carbs": 0}]}
Порядок и названия — как в списке.
{ICON_RULE}"""


class AIError(Exception):
    """Понятная пользователю ошибка."""


@dataclass
class Part:
    kind: str           # text | image | audio
    text: str = ""
    data: bytes = b""
    mime: str = ""


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise AIError("ИИ ответил что-то непонятное, попробуй ещё раз.")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise AIError("ИИ ответил что-то непонятное, попробуй ещё раз.") from e


# ---------- Gemini ----------

# Если основная модель перегружена или устарела, пробуем следующую
GEMINI_FALLBACKS = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-flash-lite-latest"]


def _gemini_client():
    from google import genai
    from google.genai import types
    # Не ждём одну модель бесконечно: 90 секунд и одна повторная попытка, потом следующая модель
    return genai.Client(api_key=config.GEMINI_API_KEY, http_options=types.HttpOptions(
        timeout=90_000, retry_options=types.HttpRetryOptions(attempts=2)))


async def _gemini_call(client, **kwargs):
    models = [config.GEMINI_MODEL] + [m for m in GEMINI_FALLBACKS if m != config.GEMINI_MODEL]
    last = None
    for model in models:
        try:
            return await client.aio.models.generate_content(model=model, **kwargs)
        except Exception as e:  # 404 — модель убрали, 429/503 — перегрузка
            code = getattr(e, "code", None)
            if code not in (404, 429, 500, 503) and "Timeout" not in type(e).__name__:
                raise
            last = e
    raise last

async def _gemini(system: str, parts: list[Part]) -> dict:
    if not config.GEMINI_API_KEY:
        raise AIError("Не задан ключ GEMINI_API_KEY.")
    from google import genai
    from google.genai import types

    client = _gemini_client()
    contents = []
    for p in parts:
        if p.kind == "text":
            contents.append(p.text)
        else:
            contents.append(types.Part.from_bytes(data=p.data, mime_type=p.mime))
    resp = await _gemini_call(
        client,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )
    return _parse_json(resp.text or "")


async def _gemini_transcribe(audio: Part) -> str:
    from google import genai
    from google.genai import types

    client = _gemini_client()
    resp = await _gemini_call(
        client,
        contents=["Расшифруй это голосовое сообщение дословно, без комментариев.",
                  types.Part.from_bytes(data=audio.data, mime_type=audio.mime)],
    )
    return (resp.text or "").strip()


# ---------- Claude ----------

async def _claude(system: str, parts: list[Part]) -> dict:
    if not config.ANTHROPIC_API_KEY:
        raise AIError("Не задан ключ ANTHROPIC_API_KEY.")
    import anthropic

    content = []
    for p in parts:
        if p.kind == "audio":
            # Claude не слушает аудио — сначала расшифровываем через Gemini
            if not config.GEMINI_API_KEY:
                raise AIError("Чтобы понимать голосовые, нужен ещё ключ GEMINI_API_KEY.")
            text = await _gemini_transcribe(p)
            content.append({"type": "text", "text": f"Расшифровка голосового:\n{text}"})
        elif p.kind == "image":
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": p.mime,
                "data": base64.b64encode(p.data).decode()}})
        else:
            content.append({"type": "text", "text": p.text})
    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    msg = await client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    return _parse_json("".join(b.text for b in msg.content if b.type == "text"))


async def _ask(system: str, parts: list[Part]) -> dict:
    system = system.replace("{ICON_RULE}", ICON_RULE.format(keys=icons.key_list()))
    try:
        if config.AI_PROVIDER == "claude":
            return await _claude(system, parts)
        return await _gemini(system, parts)
    except AIError:
        raise
    except Exception as e:  # сеть, лимиты, неверный ключ
        raise AIError(f"Не получилось связаться с ИИ ({type(e).__name__}). Попробуй ещё раз чуть позже.") from e


# ---------- Публичные функции ----------

async def parse_recipe(parts: list[Part]) -> dict:
    """Новый рецепт из текста/картинок/голосового."""
    data = await _ask(RULES, parts)
    if not data.get("is_recipe", True):
        raise AIError(data.get("reason") or "Не нашла здесь рецепта.")
    return data


async def edit_recipe(recipe: dict, instruction: list[Part]) -> dict:
    """Меняет рецепт по просьбе (текстом или голосом)."""
    current = {k: recipe.get(k) for k in
               ("title", "description", "servings", "tags", "ingredients", "steps", "notes", "tips",
                "cooked_weight")}
    parts = [Part("text", text="Рецепт:\n" + json.dumps(current, ensure_ascii=False)),
             Part("text", text="Что изменить:")] + instruction
    return await _ask(EDIT_RULES, parts)


async def fill_nutrition(ingredients: list[dict]) -> None:
    """Дозаполняет КБЖУ у ингредиентов, где его нет (например, добавленных вручную)."""
    missing = [i for i in ingredients
               if any(i.get(k) in (None, "") for k in ("kcal", "protein", "fat", "carbs"))
               or i.get("grams") in (None, "")]
    if not missing:
        return
    lst = [{"name": i["name"], "amount": i.get("amount", ""), "grams": i.get("grams")} for i in missing]
    data = await _ask(FILL_RULES, [Part("text", text=json.dumps(lst, ensure_ascii=False))])
    for ing, got in zip(missing, data.get("items", [])):
        for k in ("grams", "icon", "kcal", "protein", "fat", "carbs"):
            if ing.get(k) in (None, "") and got.get(k) is not None:
                ing[k] = got[k]
