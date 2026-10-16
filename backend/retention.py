"""Retention check-ins: what the owner does next for each person (attrition.score, SYNTHETIC).

  level     the model's band in plain words: low -> "low", watch -> "moderate", high -> "high"
  next step low / moderate -> "talk": talk to them, with 2-3 short talking points made from the
            model's top reasons in everyday words. high -> "find_cover": also look for someone on
            the tourism portal (done by the platform API, which holds the portal key: GET
            /staffing/cover/{employee_id}); the talking points are still shown.

GET  /retention/plan    one plan per scored person (or one person), with whether a talk is logged
POST /retention/talks   log that the talk happened. Reuses the closed loop's records: a task
                        (idempotency key talk:{week}:{employee}, marked done at once) plus an
                        `intervention` document (kind "talk"), so GET /interventions lists it.
                        Idempotent per person and week: a repeat returns the first record.

No free-text notes are stored (a note could hold personal details); only which suggested points
were covered. The talking points are wording, not measured facts; the reasons come from a model
trained on SYNTHETIC data and are a prompt for a friendly chat, not a judgement.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from pymongo.database import Database

from backend.db import INTERVENTIONS, NO_ID, audit, insert
from backend.schemas import AttritionScore, LiveSignals
from backend.services import NotAvailable, Service
from backend.tasks import engine

LEVEL = {"low": "low", "watch": "moderate", "high": "high"}
LEVEL_LABEL = {"low": "Low", "moderate": "Moderate", "high": "High"}
NEXT_STEP = {"low": "talk", "moderate": "talk", "high": "find_cover"}
NEXT_STEP_LABEL = {
    "talk": "Talk to them",
    "find_cover": "Talk to them, and look for someone on the job portal",
}
# Model reason (driver category) -> a talking point in everyday words.
TALKING_POINTS = {
    "overtime_overload": "They have worked many extra hours lately. Ask how the hours feel "
                         "and what would make them easier.",
    "clustered_leave_burnout": "They have not had a proper break for a while. Ask if a few "
                               "days off together would help.",
    "stalled_progression": "Their job has stayed the same for a long time. Ask what they would "
                           "like to learn or do next.",
    "pay_gap": "Their pay is lower than others in the same job. Listen, and say when pay will "
               "be looked at.",
    "low_engagement": "They seem less involved lately. Ask what is going well and what is not.",
    "manager_relationship": "Work with their manager may be hard. Ask, in private, how the "
                            "team is working.",
    "season_end_exit": "Their season contract ends soon. Ask if they would like to come back "
                       "next season.",
}
SEASON_END = ("season_end_exit",)
GENERAL = ("Ask how work is going for them this month.",
           "Ask if one thing would make their week easier.")
MAX_POINTS = 3
TALK_ACTION, TALK_OWNER = "Talked with them", "owner"


class RetentionPlan(BaseModel):
    employee_id: str
    week_start: date
    level: Literal["low", "moderate", "high"]
    level_label: str
    next_step: Literal["talk", "find_cover"]
    next_step_label: str
    talking_points: list[str]
    reasons: list[str]  # driver categories behind the points (model output)
    talked: bool  # a talk is logged for this person this week
    talked_at: datetime | None = None
    synthetic: bool = True


class TalkIn(BaseModel):
    employee_id: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")
    week_start: date | None = None
    points: list[str] = Field(default_factory=list, max_length=MAX_POINTS)


class TalkOut(BaseModel):
    logged: bool  # False = this talk was already logged (idempotent repeat)
    intervention_id: int
    task_id: int
    employee_id: str
    week_start: date
    points: list[str]
    created_at: datetime
    synthetic: bool = True


def add_checkins(db: Database, live: LiveSignals) -> LiveSignals:
    """Count the logged "We talked" check-ins (intervention kind "talk") into the live weekly
    records, by the week they were logged (a context signal for the staff-leaving estimate)."""
    ids = sorted({r.employee_id for r in live.records})
    counts: dict[tuple[str, date], int] = {}
    for d in db[INTERVENTIONS].find({"kind": "talk", "employee_id": {"$in": ids}},
                                    {"employee_id": 1, "created_at": 1}):
        at = d.get("created_at")
        at = datetime.fromisoformat(at) if isinstance(at, str) else at
        if not isinstance(at, datetime):
            continue
        week = at.date() - timedelta(days=at.weekday())
        counts[(d["employee_id"], week)] = counts.get((d["employee_id"], week), 0) + 1
    if not counts:
        return live
    records = [r.model_copy(update={"checkins": r.checkins + counts.get(
        (r.employee_id, r.week_start), 0)}) for r in live.records]
    return live.model_copy(update={"records": records})


def level_of(score: AttritionScore) -> str:
    return LEVEL.get(score.band, "low")


def talking_points(score: AttritionScore) -> list[str]:
    """2-3 points from the model's top reasons (most important first), filled up with general
    check-in questions so there are always at least 2."""
    cats = [d.category for d in score.drivers]
    if score.segment == "contract_end" and not cats:
        cats = list(SEASON_END)
    points = list(dict.fromkeys(TALKING_POINTS[c] for c in cats if c in TALKING_POINTS))
    for g in GENERAL:
        if len(points) >= 2:
            break
        points.append(g)
    return points[:MAX_POINTS]


def _talk_key(week: date, employee_id: str) -> str:
    return f"talk:{week.isoformat()}:{employee_id}"


def talks(db: Database, week: date, employee_ids: list[str] | None = None) -> dict[str, dict]:
    q: dict = {"kind": "talk", "week_start": week.isoformat()}
    if employee_ids is not None:
        q["employee_id"] = {"$in": employee_ids}
    return {r["employee_id"]: r for r in db[INTERVENTIONS].find(q, NO_ID).sort("id", 1)}


def plan_for(score: AttritionScore, talk: dict | None) -> RetentionPlan:
    lvl = level_of(score)
    step = NEXT_STEP[lvl]
    return RetentionPlan(
        employee_id=score.employee_id, week_start=score.week_start, level=lvl,
        level_label=LEVEL_LABEL[lvl], next_step=step, next_step_label=NEXT_STEP_LABEL[step],
        talking_points=talking_points(score),
        reasons=[d.category for d in score.drivers][:MAX_POINTS],
        talked=talk is not None, talked_at=talk["created_at"] if talk else None)


def plans(db: Database, service: Service, week: date | None,
          employee_id: str | None = None) -> list[RetentionPlan]:
    scores = service.score(week, [employee_id] if employee_id else None)
    if not scores:
        return []
    done = talks(db, scores[0].week_start, [s.employee_id for s in scores])
    return [plan_for(s, done.get(s.employee_id)) for s in scores]


def log_talk(db: Database, service: Service, body: TalkIn, cfg_tasks, now: datetime,  # noqa: ANN001
             source: str) -> TalkOut:
    """Store that the talk happened (task done + intervention kind talk). Idempotent per week."""
    scores = service.score(body.week_start, [body.employee_id])
    if not scores:
        raise NotAvailable(f"{body.employee_id} has no score for that week")
    s = scores[0]
    week = s.week_start
    allowed = set(talking_points(s))
    points = [p for p in dict.fromkeys(body.points) if p in allowed]  # only the suggested points
    task, created = engine.create(db, engine.NewTask(
        idempotency_key=_talk_key(week, s.employee_id), title=f"Talk with {s.employee_id}",
        assignee=TALK_OWNER, supervisor="general manager", employee_id=s.employee_id,
        description="Retention check-in: a friendly talk (logged by the owner).",
        due_in_minutes=7 * 24 * 60), cfg_tasks, now, source)
    engine.done(db, task["id"], now, source)
    existing = db[INTERVENTIONS].find_one({"kind": "talk", "task_id": task["id"]}, NO_ID)
    if existing is None:
        driver = s.drivers[0].category if s.drivers else (
            "season_end_exit" if s.segment == "contract_end" else "check_in")
        existing = insert(db, INTERVENTIONS, {
            "employee_id": s.employee_id, "week_start": week.isoformat(), "kind": "talk",
            "driver": driver, "action": TALK_ACTION, "owner": TALK_OWNER,
            "due_date": (week + timedelta(days=6)).isoformat(), "task_id": task["id"],
            "level": level_of(s), "points": points}, source)
        audit(db, "retention.talk", {"employee_id": s.employee_id, "week_start": week,
                                     "level": level_of(s), "points": len(points)}, source)
        logged = True
    else:
        logged = False
    return TalkOut(logged=logged, intervention_id=existing["id"], task_id=task["id"],
                   employee_id=s.employee_id, week_start=week, points=existing.get("points", []),
                   created_at=existing["created_at"])


def router(get_db, get_service, source_of) -> APIRouter:  # noqa: ANN001
    r = APIRouter()

    def guard(fn):  # noqa: ANN001, ANN202
        try:
            return fn()
        except NotAvailable as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except (ValueError, KeyError) as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    @r.get("/retention/plan", response_model=list[RetentionPlan])
    def retention_plan(week_start: date | None = None,
                       employee_id: str | None = Query(default=None, max_length=20),
                       db: Database = Depends(get_db),
                       service: Service = Depends(get_service)) -> list[RetentionPlan]:
        return guard(lambda: plans(db, service, week_start, employee_id))

    @r.post("/retention/talks", response_model=TalkOut)
    def retention_talk(body: TalkIn, request: Request, db: Database = Depends(get_db),
                       service: Service = Depends(get_service)) -> TalkOut:
        return guard(lambda: log_talk(db, service, body, request.app.state.settings.config.tasks,
                                      request.app.state.clock.now(), source_of(request)))

    return r
