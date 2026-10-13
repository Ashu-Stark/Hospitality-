"""Metrics, demo reset and voice ingest (B5). All data is SYNTHETIC.

GET /metrics/overview: from the latest roster (overtime hours and cost, understaffed shifts),
tasks (on-time rate = tasks done by their deadline / tasks that are done or past their
deadline), the latest closed-loop run (flagged count) and an ROI that is an ASSUMPTION:
  ROI = flagged employees still employed x replacement_cost_inr
replacement_cost_inr comes from config (ASSUMED) and can be overridden per request. "Still
employed" is all that is known: the synthetic data ends with the demo week, so the 90-day outcome
of the interventions is NOT known; the response says so.
POST /demo/reset: drop every hoi_ops collection, rebuild the indexes, reseed, demo clock back
to x1, and recreate the three SYNTHETIC demo properties (hotel onboarding, template path).
POST /voice/ingest: voice.extract on a clip in ml/voice/clips (file name only), then a task for
the department owner, due by urgency; a clear 4xx/503 error otherwise.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo import DESCENDING
from pymongo.database import Database

from backend.config import REPO_ROOT
from backend.db import (
    AUDIT,
    EMPLOYEES,
    NO_ID,
    ROSTERS,
    TASKS,
    audit,
    drop_all,
    ensure_indexes,
    seed,
)
from backend.onboarding.seed import seed_demo_properties
from backend.services import NotAvailable, Service
from backend.tasks import engine
from backend.tasks.api import TaskOut, task_out
from ml.voice.api import VoiceResult, VoiceUnavailable

ROI_NOTE = ("ASSUMPTION: ROI = flagged employees still employed x an assumed replacement cost. "
            "The synthetic data ends with the demo week, so whether interventions prevented an "
            "exit is NOT known; this is the value at stake, not a measured saving.")


class MetricsOverview(BaseModel):
    roster_id: int | None
    overtime_hours: float
    overtime_cost_inr: float
    total_roster_cost_inr: float
    understaffed_shifts: int
    tasks_total: int
    tasks_on_time_rate: float | None
    flagged_count: int
    flagged_still_employed: int
    replacement_cost_inr: float
    roi_inr: float
    roi_note: str = ROI_NOTE
    synthetic: bool = True


class VoiceIngest(BaseModel):
    file: str = Field(description="clip file name inside ml/voice/clips, e.g. clip_01.wav")
    create_task: bool = True


class VoiceIngestOut(BaseModel):
    voice: VoiceResult
    task: TaskOut | None
    synthetic: bool = True


def _aware(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def overview(db: Database, replacement_cost: float, now: datetime) -> MetricsOverview:
    roster = db[ROSTERS].find_one({}, {"_id": 0, "id": 1, "summary.cost": 1},
                                  sort=[("id", DESCENDING)])
    cost = roster["summary"]["cost"] if roster else {}
    tasks = list(db[TASKS].find({}, {"_id": 0, "done_at": 1, "deadline": 1}))
    on_time = [t for t in tasks if t["done_at"] and _aware(t["done_at"]) <= _aware(t["deadline"])]
    judged = [t for t in tasks if t["done_at"] or _aware(t["deadline"]) < now]
    loop = db[AUDIT].find_one({"action": "loop.result"}, NO_ID, sort=[("id", DESCENDING)])
    flagged = loop["detail"]["flagged"] if loop else []
    employed = set(db[EMPLOYEES].distinct("employee_id"))
    still = sum(e in employed for e in flagged)
    return MetricsOverview(
        roster_id=roster["id"] if roster else None,
        overtime_hours=cost.get("overtime_hours", 0.0),
        overtime_cost_inr=cost.get("overtime_cost_inr", 0.0),
        total_roster_cost_inr=cost.get("total_cost_inr", 0.0),
        understaffed_shifts=cost.get("understaffed_shifts", 0), tasks_total=len(tasks),
        tasks_on_time_rate=round(len(on_time) / len(judged), 4) if judged else None,
        flagged_count=len(flagged), flagged_still_employed=still,
        replacement_cost_inr=replacement_cost, roi_inr=still * replacement_cost)


def reset(request: Request) -> tuple[int, list[str]]:
    app = request.app
    db = app.state.db
    drop_all(db)
    ensure_indexes(db)
    app.state.clock.set_multiplier(1.0)
    n = seed(db, app.state.settings.config.data_source)
    properties = seed_demo_properties(db, app.state.onboarding_cfg)
    audit(db, "demo.reset", {"rows": n, "demo_properties": properties}, "api")
    return n, properties


def ingest(db: Database, service: Service, request: Request, body: VoiceIngest,
           source: str) -> VoiceIngestOut:
    cfg = request.app.state.settings.config
    clips = (REPO_ROOT / cfg.voice.clips_dir).resolve()
    path = (clips / body.file).resolve()
    if path.parent != clips:
        raise HTTPException(status_code=422, detail="file must be a clip name inside "
                                                    f"{cfg.voice.clips_dir}")
    try:
        result = service.voice(path)
    except (VoiceUnavailable, NotAvailable) as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    audit(db, "voice.ingest", {"file": body.file, "provider": result.provider,
                                    "fallback_used": result.fallback_used,
                                    "extraction": result.extraction.model_dump()}, source)
    x = result.extraction
    task = None
    if body.create_task:
        if x.issue is None or x.department is None:
            raise HTTPException(status_code=422, detail=f"no hotel issue recognised in: "
                                                        f"{result.transcript!r}")
        room = f" in room {x.room}" if x.room else ""
        new = engine.NewTask(
            idempotency_key=f"voice:{body.file}:{x.issue}:{x.room}",
            title=f"{x.issue.replace('_', ' ')}{room}", description=result.transcript,
            assignee=cfg.voice.department_owner.get(x.department, x.department),
            supervisor="general manager", due_in_minutes=cfg.voice.urgency_due_minutes[x.urgency])
        t, _ = engine.create(db, new, cfg.tasks, request.app.state.clock.now(), source)
        task = task_out(db, t)
    return VoiceIngestOut(voice=result, task=task)


def router(get_db, get_service, source_of) -> APIRouter:  # noqa: ANN001
    r = APIRouter()

    @r.get("/metrics/overview", response_model=MetricsOverview)
    def metrics_overview(request: Request, replacement_cost_inr: float | None = None,
                         db: Database = Depends(get_db)) -> MetricsOverview:
        cost = (replacement_cost_inr if replacement_cost_inr is not None
                else request.app.state.settings.config.metrics.replacement_cost_inr)
        return overview(db, cost, request.app.state.clock.now())

    @r.post("/demo/reset")
    def demo_reset(request: Request) -> dict:
        rows, properties = reset(request)
        return {"status": "reset", "employee_snapshot_rows": rows,
                "demo_property_ids": properties, "synthetic": True}

    @r.post("/voice/ingest", response_model=VoiceIngestOut)
    def voice_ingest(body: VoiceIngest, request: Request,
                     db: Database = Depends(get_db),
                     service: Service = Depends(get_service)) -> VoiceIngestOut:
        return ingest(db, service, request, body, source_of(request))

    return r
