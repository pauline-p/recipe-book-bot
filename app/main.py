"""Запуск: бот и приложение работают в одной программе."""
import asyncio
import logging

from aiohttp import web

from . import bot, config, db, web as webapp


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    db.init()
    runner = web.AppRunner(webapp.create())
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", config.PORT).start()
    logging.info("Приложение запущено на порту %s", config.PORT)
    if not config.BOT_TOKEN:
        logging.warning("BOT_TOKEN не задан — работает только приложение (режим проверки)")
        await asyncio.Event().wait()
    b, dp = bot.create()
    await dp.start_polling(b)


if __name__ == "__main__":
    asyncio.run(main())
