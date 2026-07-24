import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

import config
from handlers import get_handlers_router
from amo_service import check_amo_on_startup

logging.basicConfig(level=logging.INFO)

async def main():
    await check_amo_on_startup()

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    
    dp.include_router(get_handlers_router())
    
    logging.info("Бот успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())