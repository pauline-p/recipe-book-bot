"""Настройки берутся из переменных окружения (их задают на хостинге)."""
import os
from pathlib import Path


def _ids(value: str) -> set[int]:
    return {int(x) for x in value.replace(" ", "").split(",") if x}


BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
# Адрес, по которому открывается приложение (https://...), без слеша в конце
WEBAPP_URL = os.environ.get("WEBAPP_URL", "").rstrip("/")
PORT = int(os.environ.get("PORT", "8080"))
DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))

# Владельцы бота. Они пользуются без ограничений и зовут друзей командой /invite.
# Пусто = ботом может пользоваться кто угодно (у каждого своя книга).
ALLOWED_USER_IDS = _ids(os.environ.get("ALLOWED_USER_IDS", ""))
# Сколько раз в день приглашённый человек может просить ИИ разобрать или изменить рецепт (0 = без лимита)
AI_DAILY_LIMIT = int(os.environ.get("AI_DAILY_LIMIT", "20") or 0)

# Какой ИИ разбирает рецепты: gemini или claude
AI_PROVIDER = os.environ.get("AI_PROVIDER", "gemini").lower()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")

# Наклейки-иллюстрации блюд рисует Gemini (нужен тот же GEMINI_API_KEY с включённой оплатой).
# ILLUSTRATIONS=off — не рисовать, вместо наклейки будет тарелка с иконкой главного продукта.
ILLUSTRATIONS = os.environ.get("ILLUSTRATIONS", "on").lower() not in ("off", "0", "no", "false")
IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "gemini-3.1-flash-image")

# Только для проверки приложения в браузере без Телеграма
DEV_USER_ID = int(os.environ.get("DEV_USER_ID", "0") or 0)

WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp"
IMAGES_DIR = DATA_DIR / "images"
