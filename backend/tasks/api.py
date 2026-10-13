"""Task endpoints (B3) and the demo clock. All data is SYNTHETIC."""

from __future__ import annotations

from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field
from pymongo.database import Database

from backend.db import EVENTS, NO_ID, TASKS
from backend.tasks import engine


class TaskCreate(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=128)
    title: str
    assignee: str
    supervisor: str = ""
    description: str = ""
    employee_id: str = ""
    due_in_minutes: int | None = Field(default=None, gt=0)


class EventOut(BaseModel):
    kind: str
    message: str
    at: datetime


class TaskOut(BaseModel):
    id: int
    idempotency_key: str
    title: str
    description: str
    assignee: str
    supervisor: str
    employee_id: str
    status: str
    created_at: datetime
    deadline: datetime
    acked_at: datetime | None
    done_at: datetime | None
    events: list[EventOut]
    synthetic: bool = True


class ClockRequest(BaseModel):
    multiplier: float = Field(gt=0)


class ClockOut(BaseModel):
    multiplier: float
    virtual_now: datetime


def task_out(db: Database, task: dict) -> TaskOut:
    events = db[EVENTS].find({"task_id": task["id"]}, NO_ID).sort("id", 1)
    return TaskOut(**{k: task[k] for k in TaskOut.model_fields if k in task},
                   events=[EventOut(kind=e["kind"], message=e["message"], at=e["created_at"])
                           for e in events])


def start_scheduler(app: FastAPI) -> BackgroundScheduler | None:
    cfg = app.state.settings.config.tasks
    if not cfg.scheduler_enabled:
        return None

    def job() -> None:
        engine.tick(app.state.db, cfg, app.state.clock.now())

    scheduler = BackgroundScheduler()
    scheduler.add_job(job, "interval", seconds=cfg.tick_seconds, max_instances=1,
                      coalesce=True)
    scheduler.start()
    return scheduler


def router(get_db, source_of) -> APIRouter:  # noqa: ANN001
    r = APIRouter()

    def now(request: Request) -> datetime:
        return request.app.state.clock.now()

    @r.post("/tasks", response_model=TaskOut)
    def create_task(body: TaskCreate, request: Request, response: Response,
                    db: Database = Depends(get_db)) -> TaskOut:
        new = engine.NewTask(**body.model_dump())
        try:
            task, created = engine.create(db, new, request.app.state.settings.config.tasks,
                                          now(request), source_of(request))
        except engine.IdempotencyConflict as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        response.status_code = 201 if created else 200
        return task_out(db, task)

    def _move(fn, task_id: int, request: Request, db: Database) -> TaskOut:  # noqa: ANN001
        try:
            return task_out(db, fn(db, task_id, now(request), source_of(request)))
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    @r.post("/tasks/{task_id}/ack", response_model=TaskOut)
    def ack_task(task_id: int, request: Request,
                 db: Database = Depends(get_db)) -> TaskOut:
        return _move(engine.ack, task_id, request, db)

    @r.post("/tasks/{task_id}/done", response_model=TaskOut)
    def done_task(task_id: int, request: Request,
                  db: Database = Depends(get_db)) -> TaskOut:
        return _move(engine.done, task_id, request, db)

    @r.get("/tasks", response_model=list[TaskOut])
    def list_tasks(status: str | None = None, employee_id: str | None = None,
                   db: Database = Depends(get_db)) -> list[TaskOut]:
        q: dict = {}
        if status:
            q["status"] = status
        if employee_id:
            q["employee_id"] = employee_id
        return [task_out(db, t) for t in list(db[TASKS].find(q, NO_ID).sort("id", 1))]

    @r.post("/demo/clock", response_model=ClockOut)
    def demo_clock(body: ClockRequest, request: Request) -> ClockOut:
        clock = request.app.state.clock
        virtual = clock.set_multiplier(body.multiplier)
        return ClockOut(multiplier=clock.multiplier, virtual_now=virtual)

    @r.get("/demo/clock", response_model=ClockOut)
    def demo_clock_get(request: Request) -> ClockOut:
        clock = request.app.state.clock
        return ClockOut(multiplier=clock.multiplier, virtual_now=clock.now())

    return r
