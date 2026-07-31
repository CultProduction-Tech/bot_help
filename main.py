import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

import config
from handlers import get_handlers_router
from amo_service import check_amo_on_startup
from notify_server import start_notify_server

logging.basicConfig(level=logging.INFO)

async def main():
    await check_amo_on_startup()

    if not config.WEBHOOK_SECRET_TELEGRAM_BOT:
        logging.error("CUP notify: WEBHOOK_SECRET_TELEGRAM_BOT / TELEGRAM_CUP_SECRET не заданы в .env")
    if not config.TELEGRAM_NOTIFY_CHAT_ID:
        logging.error("CUP notify: TELEGRAM_NOTIFY_CHAT_ID не задан в .env")

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    
    dp.include_router(get_handlers_router())

    notify_runner = await start_notify_server(bot)

    logging.info("Бот успешно запущен!")
    try:
        await dp.start_polling(bot)
    finally:
        await notify_runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())