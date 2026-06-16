"""
main.py — точка входа: запускает FastAPI и Telegram-бота в одном процессе.
"""

import asyncio
import logging
import os
import threading

import uvicorn
from dotenv import load_dotenv

load_dotenv()  # загружаем .env

from bot import create_bot_and_dispatcher
from scheduler import create_scheduler
from api import app as fastapi_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("PORT", os.getenv("API_PORT", 8000)))  # Railway задаёт PORT


def run_api():
    """Запускает FastAPI в отдельном потоке."""
    uvicorn.run(fastapi_app, host=API_HOST, port=API_PORT, log_level="info")


async def run_bot():
    """Запускает бота и планировщик напоминаний."""
    bot, dp = create_bot_and_dispatcher()
    scheduler = create_scheduler(bot)
    scheduler.start()
    logger.info("Scheduler started")
    try:
        await dp.start_polling(bot, allowed_updates=["message"])
    finally:
        scheduler.shutdown()
        await bot.session.close()


def main():
    # FastAPI в daemon-потоке
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()
    logger.info(f"API running on http://{API_HOST}:{API_PORT}")

    # Бот в главном event loop
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
