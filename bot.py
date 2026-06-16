"""
bot.py — Telegram-бот на aiogram 3.x.
Команды: /start, /today, /add, /list.
"""

import logging
import os
from datetime import date, datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message

from database import (
    SessionLocal, get_or_create_user, get_lessons_for_date,
    Lesson, Recurrence, Task, Priority, TaskStatus, User
)

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")


# ── FSM состояния для /add ─────────────────────────────────────────────────

class AddLesson(StatesGroup):
    title          = State()
    date_time      = State()   # "DD.MM.YYYY HH:MM"
    recurrence     = State()   # once / weekly
    remind_minutes = State()


# ── Хелперы ────────────────────────────────────────────────────────────────

def fmt_lesson(l: Lesson) -> str:
    rec = "еженедельно" if l.recurrence == Recurrence.weekly else "разово"
    return f"📌 *{l.title}* — {l.lesson_date} {l.lesson_time} ({rec}), напомнить за {l.remind_minutes} мин."


def fmt_task(t: Task) -> str:
    emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(t.priority, "⚪")
    deadline = t.deadline.strftime("%d.%m") if t.deadline else "—"
    return f"{emoji} {t.title} | дедлайн: {deadline} | {t.status}"


# ── Handlers ───────────────────────────────────────────────────────────────

async def cmd_start(message: Message):
    """Привязывает Telegram аккаунт к записи User в БД."""
    db = SessionLocal()
    try:
        user = get_or_create_user(
            db,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
        )
        await message.answer(
            f"👋 Привет, {message.from_user.first_name}!\n\n"
            f"Твой аккаунт привязан (ID: {user.id}).\n\n"
            "Доступные команды:\n"
            "/today — расписание на сегодня\n"
            "/add — добавить занятие\n"
            "/list — ближайшие занятия"
        )
    finally:
        db.close()


async def cmd_today(message: Message):
    """Показывает занятия и задачи на сегодня."""
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=message.from_user.id).first()
        today = date.today()
        lessons = get_lessons_for_date(db, today)
        # Показываем задачи пользователя + задачи без владельца (добавленные с сайта)
        q = db.query(Task).filter(Task.status != TaskStatus.done)
        if user:
            q = q.filter((Task.user_id == user.id) | (Task.user_id == None))
        tasks = q.all()

        text = f"📅 *Расписание на {today.strftime('%d.%m.%Y')}*\n\n"

        if lessons:
            text += "🎓 *Занятия:*\n"
            for l in sorted(lessons, key=lambda x: x.lesson_time):
                text += fmt_lesson(l) + "\n"
        else:
            text += "🎓 Занятий нет.\n"

        text += "\n📋 *Задачи:*\n"
        if tasks:
            for t in tasks:
                text += fmt_task(t) + "\n"
        else:
            text += "Задач нет.\n"

        await message.answer(text, parse_mode="Markdown")
    finally:
        db.close()


async def cmd_list(message: Message):
    """Ближайшие 7 дней занятий."""
    db = SessionLocal()
    try:
        today = date.today()
        lines = []
        for i in range(7):
            d = today + timedelta(days=i)
            lessons = get_lessons_for_date(db, d)
            if lessons:
                lines.append(f"\n*{d.strftime('%d.%m %a')}*")
                for l in sorted(lessons, key=lambda x: x.lesson_time):
                    lines.append(fmt_lesson(l))
        text = "📅 *Занятия на 7 дней:*\n" + "\n".join(lines) if lines else "Занятий нет."
        await message.answer(text, parse_mode="Markdown")
    finally:
        db.close()


# ── /add FSM ───────────────────────────────────────────────────────────────

async def cmd_add(message: Message, state: FSMContext):
    await state.set_state(AddLesson.title)
    await message.answer("📝 Введите название занятия:")


async def add_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AddLesson.date_time)
    await message.answer("📅 Введите дату и время (ДД.ММ.ГГГГ ЧЧ:ММ):")


async def add_datetime(message: Message, state: FSMContext):
    try:
        dt = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        await message.answer("❌ Неверный формат. Попробуйте: 25.06.2026 09:00")
        return
    await state.update_data(lesson_date=dt.date(), lesson_time=dt.strftime("%H:%M"))
    await state.set_state(AddLesson.recurrence)
    await message.answer("🔁 Периодичность? Введите: once или weekly")


async def add_recurrence(message: Message, state: FSMContext):
    val = message.text.strip().lower()
    if val not in ("once", "weekly"):
        await message.answer("❌ Введите 'once' или 'weekly'")
        return
    await state.update_data(recurrence=val)
    await state.set_state(AddLesson.remind_minutes)
    await message.answer("⏰ За сколько минут напомнить? (например: 15)")


async def add_remind(message: Message, state: FSMContext):
    try:
        minutes = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите число минут")
        return

    data = await state.get_data()
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=message.from_user.id).first()
        lesson = Lesson(
            user_id=user.id if user else None,
            title=data["title"],
            lesson_date=data["lesson_date"],
            lesson_time=data["lesson_time"],
            recurrence=Recurrence(data["recurrence"]),
            remind_minutes=minutes,
        )
        db.add(lesson)
        db.commit()
        await message.answer(
            f"✅ Занятие добавлено:\n{fmt_lesson(lesson)}",
            parse_mode="Markdown"
        )
    finally:
        db.close()

    await state.clear()


# ── Регистрация хендлеров ──────────────────────────────────────────────────

def register_handlers(dp: Dispatcher):
    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_today, Command("today"))
    dp.message.register(cmd_list, Command("list"))
    dp.message.register(cmd_add, Command("add"))
    dp.message.register(add_title, AddLesson.title)
    dp.message.register(add_datetime, AddLesson.date_time)
    dp.message.register(add_recurrence, AddLesson.recurrence)
    dp.message.register(add_remind, AddLesson.remind_minutes)


def create_bot_and_dispatcher():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан в .env")
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    register_handlers(dp)
    return bot, dp
