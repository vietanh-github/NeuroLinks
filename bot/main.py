"""NeuroLinks Bot — entry point."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import logging
from dotenv import load_dotenv

_BOT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_BOT_ROOT, ".env"))

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault
from bot.handlers import admin_handler, link_handler

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger(__name__)


_COMMANDS = [
    BotCommand(command="start",    description="🏠 Trang chủ & thống kê"),
    BotCommand(command="help",     description="📖 Hướng dẫn sử dụng"),
    BotCommand(command="web",      description="🌐 Mở NeuroLinks trên web"),
    BotCommand(command="settings", description="⚙️ Cài đặt cá nhân (thông báo)"),
    BotCommand(command="admin",    description="🔧 Bảng điều khiển (admin)"),
]


async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env")

    bot = Bot(token=token)
    dp  = Dispatcher(storage=MemoryStorage())

    # Register Bot Menu commands (shown in the ☰ shortcut bar)
    await bot.set_my_commands(_COMMANDS, scope=BotCommandScopeDefault())

    dp.include_router(admin_handler.router)
    dp.include_router(link_handler.router)

    log.info("🚀 NeuroLinks bot starting…")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    asyncio.run(main())
