"""
scheduler.py — APScheduler: проверяет занятия и отправляет напоминания в Telegram.
Часовой пояс: Asia/Almaty (UTC+5).
"""

import logging
from datetime import datetime

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import SessionLocal, get_pending_reminders, Lesson

logger = logging.getLogger(__name__)

TIMEZONE = pytz.timezone("Asia/Almaty")


async def send_reminders(bot):
    """
    Вызывается планировщиком каждую минуту.
    Находит занятия с наступившим временем напоминания и отправляет сообщение.
    """
    db = SessionLocal()
    try:
        # Текущее время в UTC (в БД храним UTC)
        now_utc = datetime.utcnow()
        pending = get_pending_reminders(db, now_utc)
        for lesson in pending:
            # Находим пользователя с telegram_id
            from database import User
            user = db.query(User).filter(User.id == lesson.user_id).first()
            if not user or not user.telegram_id:
                continue

            lesson_dt_str = f"{lesson.lesson_date} {lesson.lesson_time}"
            # Форматируем время для отображения в Almaty
            lesson_naive = datetime.strptime(lesson_dt_str, "%Y-%m-%d %H:%M")
            lesson_almaty = pytz.utc.localize(lesson_naive).astimezone(TIMEZONE)

            text = (
                f"⏰ Напоминание!\n\n"
                f"📚 *{lesson.title}*\n"
                f"🕐 {lesson_almaty.strftime('%d.%m.%Y %H:%M')} (Almaty)\n"
                f"Начало через {lesson.remind_minutes} мин."
            )
            try:
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=text,
                    parse_mode="Markdown"
                )
                lesson.notified = True
                db.commit()
                logger.info(f"Reminder sent for lesson {lesson.id} to {user.telegram_id}")
            except Exception as e:
                logger.error(f"Failed to send reminder to {user.telegram_id}: {e}")
    finally:
        db.close()


def create_scheduler(bot) -> AsyncIOScheduler:
    """Создаёт и настраивает планировщик."""
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    # Проверяем занятия каждую минуту
    scheduler.add_job(
        send_reminders,
        trigger="interval",
        minutes=1,
        args=[bot],
        id="reminder_check",
        replace_existing=True,
    )
    return scheduler
