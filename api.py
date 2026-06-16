"""
api.py — FastAPI приложение: CRUD для задач и занятий.
"""

import os
from datetime import datetime, date
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import (
    init_db, get_db, Task, Lesson, User,
    Priority, TaskStatus, Recurrence,
    get_tasks, get_lessons_for_date, get_or_create_user
)

app = FastAPI(title="TimeManager API", version="1.0")

# CORS: разрешаем запросы с любого origin (в продакшене укажите конкретный домен)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


# ── Pydantic схемы ─────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    title: str
    priority: Priority = Priority.medium
    deadline: Optional[datetime] = None
    status: TaskStatus = TaskStatus.planned
    is_urgent: bool = False
    is_important: bool = False
    scheduled_time: Optional[str] = None  # "HH:MM"
    user_id: Optional[int] = None

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    priority: Optional[Priority] = None
    deadline: Optional[datetime] = None
    status: Optional[TaskStatus] = None
    is_urgent: Optional[bool] = None
    is_important: Optional[bool] = None
    scheduled_time: Optional[str] = None

class TaskOut(BaseModel):
    id: int
    title: str
    priority: Priority
    deadline: Optional[datetime]
    status: TaskStatus
    is_urgent: bool
    is_important: bool
    scheduled_time: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]
    user_id: Optional[int]

    class Config:
        from_attributes = True


class LessonCreate(BaseModel):
    title: str
    lesson_date: date
    lesson_time: str          # "HH:MM"
    recurrence: Recurrence = Recurrence.once
    remind_minutes: int = 15
    user_id: Optional[int] = None

class LessonUpdate(BaseModel):
    title: Optional[str] = None
    lesson_date: Optional[date] = None
    lesson_time: Optional[str] = None
    recurrence: Optional[Recurrence] = None
    remind_minutes: Optional[int] = None

class LessonOut(BaseModel):
    id: int
    title: str
    lesson_date: date
    lesson_time: str
    recurrence: Recurrence
    remind_minutes: int
    notified: bool
    user_id: Optional[int]

    class Config:
        from_attributes = True


class StatsOut(BaseModel):
    done_today: int
    done_week: int
    total: int
    completion_pct: float


# ── Tasks endpoints ────────────────────────────────────────────────────────

@app.get("/tasks", response_model=List[TaskOut])
def list_tasks(
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    return get_tasks(db, user_id=user_id, status=status, priority=priority)


@app.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(body: TaskCreate, db: Session = Depends(get_db)):
    task = Task(**body.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@app.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task


@app.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, body: TaskUpdate, db: Session = Depends(get_db)):
    task = db.query(Task).get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(task, field, value)
    # Фиксируем время завершения
    if body.status == TaskStatus.done and not task.completed_at:
        task.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task


@app.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    db.delete(task)
    db.commit()


# ── Lessons endpoints ──────────────────────────────────────────────────────

@app.get("/lessons", response_model=List[LessonOut])
def list_lessons(
    date_filter: Optional[date] = Query(None, alias="date"),
    user_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    if date_filter:
        lessons = get_lessons_for_date(db, date_filter)
    else:
        lessons = db.query(Lesson).all()
    if user_id:
        lessons = [l for l in lessons if l.user_id == user_id]
    return lessons


@app.post("/lessons", response_model=LessonOut, status_code=201)
def create_lesson(body: LessonCreate, db: Session = Depends(get_db)):
    lesson = Lesson(**body.model_dump())
    db.add(lesson)
    db.commit()
    db.refresh(lesson)
    return lesson


@app.get("/lessons/{lesson_id}", response_model=LessonOut)
def get_lesson(lesson_id: int, db: Session = Depends(get_db)):
    lesson = db.query(Lesson).get(lesson_id)
    if not lesson:
        raise HTTPException(404, "Lesson not found")
    return lesson


@app.patch("/lessons/{lesson_id}", response_model=LessonOut)
def update_lesson(lesson_id: int, body: LessonUpdate, db: Session = Depends(get_db)):
    lesson = db.query(Lesson).get(lesson_id)
    if not lesson:
        raise HTTPException(404, "Lesson not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(lesson, field, value)
    # Сбрасываем флаг уведомления при изменении времени
    if body.lesson_time or body.lesson_date:
        lesson.notified = False
    db.commit()
    db.refresh(lesson)
    return lesson


@app.delete("/lessons/{lesson_id}", status_code=204)
def delete_lesson(lesson_id: int, db: Session = Depends(get_db)):
    lesson = db.query(Lesson).get(lesson_id)
    if not lesson:
        raise HTTPException(404, "Lesson not found")
    db.delete(lesson)
    db.commit()


# ── Stats endpoint ─────────────────────────────────────────────────────────

@app.get("/stats", response_model=StatsOut)
def get_stats(user_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    from datetime import timedelta
    q = db.query(Task)
    if user_id:
        q = q.filter(Task.user_id == user_id)
    all_tasks = q.all()
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=now.weekday())

    done_today = sum(
        1 for t in all_tasks
        if t.status == TaskStatus.done and t.completed_at and t.completed_at >= today_start
    )
    done_week = sum(
        1 for t in all_tasks
        if t.status == TaskStatus.done and t.completed_at and t.completed_at >= week_start
    )
    total = len(all_tasks)
    done_total = sum(1 for t in all_tasks if t.status == TaskStatus.done)
    pct = round(done_total / total * 100, 1) if total else 0.0

    return StatsOut(done_today=done_today, done_week=done_week,
                    total=total, completion_pct=pct)


# ── Export endpoint ────────────────────────────────────────────────────────

@app.get("/export")
def export_data(user_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    """Экспорт всех данных в JSON."""
    tasks = get_tasks(db, user_id=user_id)
    lessons_q = db.query(Lesson)
    if user_id:
        lessons_q = lessons_q.filter(Lesson.user_id == user_id)
    lessons = lessons_q.all()

    def task_dict(t: Task):
        return {
            "id": t.id, "title": t.title, "priority": t.priority,
            "deadline": t.deadline.isoformat() if t.deadline else None,
            "status": t.status, "is_urgent": t.is_urgent,
            "is_important": t.is_important, "scheduled_time": t.scheduled_time,
            "created_at": t.created_at.isoformat(),
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        }

    def lesson_dict(l: Lesson):
        return {
            "id": l.id, "title": l.title,
            "lesson_date": l.lesson_date.isoformat(),
            "lesson_time": l.lesson_time, "recurrence": l.recurrence,
            "remind_minutes": l.remind_minutes,
        }

    return {"tasks": [task_dict(t) for t in tasks],
            "lessons": [lesson_dict(l) for l in lessons]}
