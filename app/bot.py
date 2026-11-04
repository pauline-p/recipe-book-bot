"""Бот: добавление и правка рецептов прямо в чате."""
import asyncio
import io
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           MenuButtonWebApp, Message, WebAppInfo)
from aiogram.client.default import DefaultBotProperties

from . import ai, config, db, illustrate, photos
from .formatting import card, n

log = logging.getLogger(__name__)
router = Router()

# Что бот ждёт от человека следующим сообщением: {user_id: ("edit"|"weight", recipe_id)}
pending: dict[int, tuple[str, int]] = {}
# Какой рецепт показан в каком сообщении — чтобы можно было ответить на карточку
card_msgs: dict[tuple[int, int], int] = {}
# Альбомы из нескольких скриншотов собираем вместе
albums: dict[str, list[Message]] = {}


def kb(rid: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="Изменить", callback_data=f"edit:{rid}"),
             InlineKeyboardButton(text="Вес готового", callback_data=f"weight:{rid}")],
            [InlineKeyboardButton(text="Фото блюда", callback_data=f"photo:{rid}")]]
    second = [InlineKeyboardButton(text="Удалить", callback_data=f"del:{rid}")]
    if config.WEBAPP_URL:
        second.insert(0, InlineKeyboardButton(
            text="Открыть в книге", web_app=WebAppInfo(url=f"{config.WEBAPP_URL}/#/r/{rid}")))
    rows.append(second)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show(msg: Message, r: dict, prefix: str = "") -> None:
    sent = await msg.answer((prefix + "\n\n" if prefix else "") + card(r), reply_markup=kb(r["id"]))
    card_msgs[(msg.chat.id, sent.message_id)] = r["id"]


async def download(bot: Bot, file_id: str) -> bytes:
    buf = io.BytesIO()
    await bot.download(file_id, destination=buf)
    return buf.getvalue()


async def collect_parts(bot: Bot, messages: list[Message]) -> tuple[list[ai.Part], str]:
    """Превращает сообщения в куски для ИИ и текст-источник для истории."""
    parts, source = [], []
    for m in messages:
        text = m.text or m.caption
        if text:
            parts.append(ai.Part("text", text=text))
            source.append(text)
        if m.photo:
            parts.append(ai.Part("image", data=await download(bot, m.photo[-1].file_id), mime="image/jpeg"))
            source.append("[скриншот]")
        if m.document and (m.document.mime_type or "").startswith("image/"):
            parts.append(ai.Part("image", data=await download(bot, m.document.file_id),
                                 mime=m.document.mime_type))
            source.append("[картинка]")
        if m.voice or m.audio:
            f = m.voice or m.audio
            parts.append(ai.Part("audio", data=await download(bot, f.file_id),
                                 mime=f.mime_type or "audio/ogg"))
            source.append("[голосовое]")
    return parts, "\n".join(source)


async def keep_typing(bot: Bot, chat_id: int, stop: asyncio.Event) -> None:
    while not stop.is_set():
        await bot.send_chat_action(chat_id, ChatAction.TYPING)
        try:
            await asyncio.wait_for(stop.wait(), 4)
        except asyncio.TimeoutError:
            pass


async def handle(bot: Bot, messages: list[Message]) -> None:
    first = messages[0]
    uid = first.from_user.id
    if not config.allowed(uid):
        await first.answer("Это личная книга рецептов, доступ закрыт.")
        return

    # Это ответ на карточку рецепта? Тогда считаем это правкой.
    target = None
    if first.reply_to_message:
        rid = card_msgs.get((first.chat.id, first.reply_to_message.message_id))
        if rid:
            target = ("edit", rid)
    target = target or pending.pop(uid, None)

    # Фото готового блюда: после кнопки «Фото блюда» или фото без подписи в ответ на рецепт
    if target and first.photo and (target[0] == "photo" or not first.caption):
        try:
            r = photos.save(uid, target[1], await download(bot, first.photo[-1].file_id))
            await show(first, r, "Поставила фото в тарелку.")
        except photos.PhotoError as e:
            await first.answer(str(e))
        return
    if target and target[0] == "photo":
        await first.answer("Жду фото готового блюда. Пришли картинку, а не текст.")
        pending[uid] = target
        return

    # Вес готового блюда — просто число, ИИ не нужен
    if target and target[0] == "weight" and first.text:
        try:
            w = float(first.text.replace(",", ".").lower().replace("г", "").strip())
        except ValueError:
            await first.answer("Напиши вес числом, например: 850")
            pending[uid] = target
            return
        r = db.get(uid, target[1])
        if r:
            r["cooked_weight"] = w or None
            r = db.update(uid, r["id"], r)
            await show(first, r, f"Записала вес готового блюда: {n(w)} г. Пересчитала КБЖУ на 100 г.")
        return

    stop = asyncio.Event()
    typing = asyncio.create_task(keep_typing(bot, first.chat.id, stop))
    try:
        parts, source = await collect_parts(bot, messages)
        if not parts:
            await first.answer("Пришли рецепт текстом, скриншотом или голосовым.")
            return
        if target:
            r = db.get(uid, target[1])
            if not r:
                await first.answer("Не нашла этот рецепт, возможно, он удалён.")
                return
            data = await ai.edit_recipe(r, parts)
            data["source"] = r.get("source", "")
            await ai.fill_nutrition(data.get("ingredients", []))
            r = db.update(uid, r["id"], data)
            await show(first, r, "Готово, обновила.")
        else:
            data = await ai.parse_recipe(parts)
            data["source"] = source
            await ai.fill_nutrition(data.get("ingredients", []))
            r = db.add(uid, data)
            illustrate.schedule(uid, r["id"])
            await show(first, r, "Сохранила в книгу.")
    except ai.AIError as e:
        await first.answer(str(e))
    except Exception:
        log.exception("handle failed")
        await first.answer("Что-то пошло не так. Попробуй ещё раз.")
    finally:
        stop.set()
        typing.cancel()


# ---------- Команды ----------

@router.message(CommandStart())
async def start(msg: Message) -> None:
    if not config.allowed(msg.from_user.id):
        await msg.answer(f"Это личная книга рецептов. Твой id: {msg.from_user.id}")
        return
    await msg.answer(
        "Это твоя книга рецептов.\n\n"
        "Чтобы добавить рецепт, просто пришли его сюда: текстом, скриншотом "
        "(можно несколько сразу) или голосовым. Я сама разберу ингредиенты и посчитаю КБЖУ на 100 г.\n\n"
        "Чтобы изменить рецепт, нажми «Изменить» под ним или ответь на его сообщение, "
        "например: «убери сахар», «добавь 50 г грецких орехов» или «добавь лайфхак: …».\n\n"
        "Фото готового блюда: нажми «Фото блюда» под рецептом или ответь на рецепт фотографией.\n\n"
        "/list — все рецепты\n/find слово — поиск\n\n"
        "Всю книгу можно открыть кнопкой «Книга» внизу слева.")


@router.message(Command("list"))
async def list_cmd(msg: Message) -> None:
    await send_list(msg, db.list_all(msg.from_user.id))


@router.message(Command("find"))
async def find_cmd(msg: Message, command: CommandObject) -> None:
    if not command.args:
        await msg.answer("Напиши, что искать, например: /find сырники")
        return
    await send_list(msg, db.list_all(msg.from_user.id, command.args), command.args)


async def send_list(msg: Message, items: list[dict], query: str = "") -> None:
    if not items:
        await msg.answer("Ничего не нашла." if query else "Пока в книге пусто. Пришли первый рецепт.")
        return
    buttons = [[InlineKeyboardButton(
        text=f"{r['title']} · {round(r['nutrition']['per100']['kcal'])} ккал/100 г",
        callback_data=f"show:{r['id']}")] for r in items[:40]]
    await msg.answer(f"Рецептов: {len(items)}", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


# ---------- Кнопки под рецептом ----------

@router.callback_query(F.data.startswith("show:"))
async def cb_show(cq: CallbackQuery) -> None:
    r = db.get(cq.from_user.id, int(cq.data.split(":")[1]))
    await cq.answer()
    if r:
        await show(cq.message, r)


@router.callback_query(F.data.startswith("edit:"))
async def cb_edit(cq: CallbackQuery) -> None:
    pending[cq.from_user.id] = ("edit", int(cq.data.split(":")[1]))
    await cq.answer()
    await cq.message.answer("Что поменять? Напиши или скажи голосом. "
                            "Например: «сахара 30 г вместо 50», «добавь шаг: остудить 10 минут».")


@router.callback_query(F.data.startswith("weight:"))
async def cb_weight(cq: CallbackQuery) -> None:
    pending[cq.from_user.id] = ("weight", int(cq.data.split(":")[1]))
    await cq.answer()
    await cq.message.answer("Сколько весит готовое блюдо, в граммах? Тогда КБЖУ на 100 г будет точнее "
                            "(при варке и запекании вес меняется). Напиши 0, чтобы считать по сырым продуктам.")


@router.callback_query(F.data.startswith("photo:"))
async def cb_photo(cq: CallbackQuery) -> None:
    pending[cq.from_user.id] = ("photo", int(cq.data.split(":")[1]))
    await cq.answer()
    await cq.message.answer("Пришли фото готового блюда, поставлю его в тарелку.")


@router.callback_query(F.data.startswith("del:"))
async def cb_del(cq: CallbackQuery) -> None:
    rid = int(cq.data.split(":")[1])
    await cq.answer()
    await cq.message.answer("Точно удалить рецепт?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Да, удалить", callback_data=f"delok:{rid}"),
        InlineKeyboardButton(text="Нет", callback_data="cancel")]]))


@router.callback_query(F.data.startswith("delok:"))
async def cb_delok(cq: CallbackQuery) -> None:
    ok = db.delete(cq.from_user.id, int(cq.data.split(":")[1]))
    await cq.answer()
    await cq.message.edit_text("Удалила." if ok else "Этого рецепта уже нет.")


@router.callback_query(F.data == "cancel")
async def cb_cancel(cq: CallbackQuery) -> None:
    await cq.answer()
    await cq.message.delete()


# ---------- Любое другое сообщение = рецепт или правка ----------

@router.message(F.media_group_id)
async def album(msg: Message, bot: Bot) -> None:
    key = msg.media_group_id
    if key in albums:
        albums[key].append(msg)
        return
    albums[key] = [msg]
    await asyncio.sleep(1.5)  # ждём остальные скриншоты альбома
    await handle(bot, albums.pop(key))


@router.message(F.text | F.photo | F.voice | F.audio | F.document)
async def any_msg(msg: Message, bot: Bot) -> None:
    await handle(bot, [msg])


def create() -> tuple[Bot, Dispatcher]:
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    async def on_startup() -> None:
        if config.WEBAPP_URL:
            await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
                text="Книга", web_app=WebAppInfo(url=config.WEBAPP_URL)))
    dp.startup.register(on_startup)
    return bot, dp
