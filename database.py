"""
database.py — модели и операции с базой данных SQLite через SQLAlchemy.
"""

import os
from datetime import datetime, date
from typing import Optional, List

from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean,
    DateTime, Date, Time, Enum as SAEnum, ForeignKey, text
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
import enum

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./timemanager.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ── Enums ──────────────────────────────────────────────────────────────────

class Priority(str, enum.Enum):
    high = "high"
    medium = "medium"
    low = "low"

class TaskStatus(str, enum.Enum):
    planned = "planned"
    in_progress = "in_progress"
    done = "done"

class Recurrence(str, enum.Enum):
    once = "once"
    weekly = "weekly"

class TaskRecurrence(str, enum.Enum):
    none   = "none"
    daily  = "daily"
    weekly = "weekly"


# ── Models ─────────────────────────────────────────────────────────────────

class User(Base):
    """Пользователь: хранит привязку Telegram chat_id."""
    __tablename__ = "users"

    id         = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, unique=True, nullable=True, index=True)
    username   = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Task(Base):
    """Задача с приоритетом, дедлайном, статусом и квадрантом Эйзенхауэра."""
    __tablename__ = "tasks"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=True)
    title       = Column(String, nullable=False)
    priority    = Column(SAEnum(Priority), default=Priority.medium)
    deadline    = Column(DateTime, nullable=True)
    status      = Column(SAEnum(TaskStatus), default=TaskStatus.planned)
    is_urgent   = Column(Boolean, default=False)   # для матрицы Эйзенхауэра
    is_important = Column(Boolean, default=False)
    scheduled_time   = Column(String, nullable=True)   # "HH:MM" для плана дня
    recurrence       = Column(SAEnum(TaskRecurrence), default=TaskRecurrence.none)
    recurrence_day   = Column(Integer, nullable=True)  # 0=Пн, 6=Вс (для weekly)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class Lesson(Base):
    """Занятие/событие с напоминанием через Telegram."""
    __tablename__ = "lessons"

    id             = Column(Integer, primary_key=True, index=True)
    user_id        = Column(Integer, ForeignKey("users.id"), nullable=True)
    title          = Column(String, nullable=False)
    lesson_date    = Column(Date, nullable=False)
    lesson_time    = Column(String, nullable=False)   # "HH:MM"
    recurrence     = Column(SAEnum(Recurrence), default=Recurrence.once)
    remind_minutes = Column(Integer, default=15)       # за сколько минут напомнить
    notified       = Column(Boolean, default=False)    # уже отправлено напоминание?
    created_at     = Column(DateTime, default=datetime.utcnow)


# ── Init ───────────────────────────────────────────────────────────────────

def init_db():
    """Создаёт все таблицы при первом запуске."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Генератор сессии для FastAPI Depends."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── CRUD helpers ───────────────────────────────────────────────────────────

def get_or_create_user(db: Session, telegram_id: Optional[int] = None,
                        username: Optional[str] = None) -> User:
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        user = User(telegram_id=telegram_id, username=username)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def get_tasks(db: Session, user_id: Optional[int] = None,
              status: Optional[str] = None,
              priority: Optional[str] = None) -> List[Task]:
    q = db.query(Task)
    if user_id:
        q = q.filter(Task.user_id == user_id)
    if status:
        q = q.filter(Task.status == status)
    if priority:
        q = q.filter(Task.priority == priority)
    return q.order_by(Task.deadline.asc().nullslast()).all()


def get_lessons_for_date(db: Session, target_date: date) -> List[Lesson]:
    """Возвращает занятия на указанную дату (с учётом еженедельных)."""
    all_lessons = db.query(Lesson).all()
    result = []
    for lesson in all_lessons:
        if lesson.lesson_date == target_date:
            result.append(lesson)
        elif lesson.recurrence == Recurrence.weekly:
            # совпадение по дню недели
            if lesson.lesson_date.weekday() == target_date.weekday():
                result.append(lesson)
    return result


def get_pending_reminders(db: Session, now: datetime) -> List[Lesson]:
    """
    Занятия, для которых ещё не отправлено уведомление и время напоминания
    уже наступило (сейчас >= время_занятия - remind_minutes).
    """
    from datetime import timedelta
    candidates = db.query(Lesson).filter(Lesson.notified == False).all()
    due = []
    for lesson in candidates:
        lesson_dt_str = f"{lesson.lesson_date} {lesson.lesson_time}"
        lesson_dt = datetime.strptime(lesson_dt_str, "%Y-%m-%d %H:%M")
        remind_at = lesson_dt - timedelta(minutes=lesson.remind_minutes)
        if now >= remind_at:
            due.append(lesson)
    return due
