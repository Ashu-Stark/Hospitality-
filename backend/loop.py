"""Closed loop (B4): score -> interventions -> baseline roster -> protected roster -> rescore.

POST /loop/run:
  1. attrition.score for the snapshot week; FLAGGED = high-band PERMANENT staff (any employee,
     demo heroes included: nothing is hard-coded).
  2. For each flagged person: the top-2 playbook actions of their top driver become intervention
     documents and tasks (owner, due = week + check_after_weeks), idempotent per week / person /
     action.
  3. BASELINE roster (no protection) and PROTECTED roster (protected-off bonus for the flagged).
  4. Each roster is turned into the attrition features it changes for that person (this week's
     overtime hours, their 4- and 10-week means, weeks since a full weekend off, consecutive days
     worked, weekly offs skipped in 4 weeks; history from the SYNTHETIC ml data tables) and
     attrition.rescore gives the risk and band under BOTH rosters. Before / after = baseline
     roster vs protected roster: a SIMULATION, not causal proof.
Everything is written to audit_log.

GET /interventions lists the stored interventions with the status of their linked task
(open / acked / done, or overdue = not done and past its deadline on the demo clock), so "open
vs completed" is derived from the task, never stored twice.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from pymongo.database import Database

from backend.config import ML_DATA, BackendConfig
from backend.db import INTERVENTIONS, NO_ID, TASKS, audit, insert
from backend.roster.problem import DAYS, carry_in
from backend.roster.service import RosterRequest, RosterResult, generate
from backend.services import Service
from backend.tasks import engine
from ml.generator.config import load_config as load_ml_config

ROLL_WEEKS = 4
SIMULATION = ("SIMULATION, not causal proof: the same trained attrition model re-scored with the "
              "features each roster implies, on SYNTHETIC data.")


class RosterEffect(BaseModel):
    overtime_hours: float
    full_weekend_off: bool
    days_worked: int
    risk: float
    band: str
    rank: int


class PersonResult(BaseModel):
    employee_id: str
    is_demo_hero: bool
    original_risk: float
    original_band: str
    top_drivers: list[str]
    baseline: RosterEffect
    protected: RosterEffect
    risk_change: float
    overrides_baseline: dict[str, float]
    overrides_protected: dict[str, float]


class InterventionOut(BaseModel):
    employee_id: str
    driver: str
    action: str
    owner: str
    due_date: date
    task_id: int


class InterventionRecord(BaseModel):
    """A stored intervention plus its linked task's status (GET /interventions)."""

    id: int
    employee_id: str
    week_start: date
    driver: str
    action: str
    owner: str
    due_date: date
    task_id: int
    task_status: Literal["open", "acked", "done", "overdue", "missing"]
    task_deadline: datetime | None
    task_done_at: datetime | None
    created_at: datetime
    synthetic: bool = True


class LoopResult(BaseModel):
    week_start: date
    flagged: list[str]
    interventions: list[InterventionOut]
    baseline_roster_id: int
    protected_roster_id: int
    people: list[PersonResult]
    totals: dict[str, dict]
    note: str = SIMULATION
    synthetic: bool = True


def history(week: date) -> pd.DataFrame:
    """Weekly overtime / signals per employee before `week` (staff + demo heroes)."""
    beh = pd.concat([pd.read_csv(ML_DATA / "weekly_behaviour.csv"),
                     pd.read_csv(ML_DATA / "demo" / "hero_weekly.csv")])
    sig = pd.concat([pd.read_csv(ML_DATA / "weekly_signals.csv"),
                     pd.read_csv(ML_DATA / "demo" / "hero_weekly.csv")])
    cols = ["employee_id", "week_start", "weekly_off_skipped", "weeks_since_weekend_off"]
    df = beh[["employee_id", "week_start", "overtime_hours"]].drop_duplicates().merge(
        sig[cols].drop_duplicates(["employee_id", "week_start"]), on=["employee_id", "week_start"])
    return df[df["week_start"] < str(week)].sort_values(["employee_id", "week_start"])


def roster_overrides(person: dict, hist: pd.DataFrame, window: int, carry: int) -> dict:
    """Attrition features implied by one roster week for one person (see module docstring)."""
    prev = hist[hist["employee_id"] == person["employee_id"]]
    ot = float(person["overtime_hours"])
    last = lambda n: prev["overtime_hours"].tail(n).tolist()  # noqa: E731
    roll4, win = last(ROLL_WEEKS - 1) + [ot], last(window - 1) + [ot]
    since_prev = int(prev["weeks_since_weekend_off"].iloc[-1]) if len(prev) else 0
    skipped_prev = int(prev["weekly_off_skipped"].tail(ROLL_WEEKS - 1).astype(bool).sum())
    worked = person["worked_days"]
    run = carry if 0 in worked else 0
    longest, cur = 0, run
    for d in range(DAYS):
        cur = cur + 1 if d in worked else 0
        longest = max(longest, cur)
    skipped_now = 0 if len(worked) < DAYS else 1
    return {"overtime_hours": ot, "overtime_roll4_mean": round(sum(roll4) / len(roll4), 4),
            "overtime_window_mean": round(sum(win) / len(win), 4),
            "weeks_since_weekend_off": 0.0 if person["full_weekend_off"] else since_prev + 1.0,
            "consecutive_days_worked": float(longest),
            "weekly_off_skipped_4w": float(skipped_prev + skipped_now)}


def coverage(roster: RosterResult) -> float:
    """Scheduled hours / required hours, each department capped at full coverage."""
    req = sum(c["required_hours"] for c in roster.coverage)
    got = sum(min(c["scheduled_hours"], c["required_hours"]) for c in roster.coverage)
    return round(got / req, 4) if req else 1.0


def _person_rows(roster: RosterResult, week: date) -> dict[str, dict]:
    days: dict[str, set[int]] = {}
    for a in roster.assignments:
        days.setdefault(a.employee_id, set()).add((a.date - week).days)
    return {p["employee_id"]: {**p, "worked_days": days.get(p["employee_id"], set())}
            for p in roster.people}


def run_loop(db: Database, service: Service, cfg: BackendConfig, now: datetime,
             source: str) -> LoopResult:
    week = service.latest_week()
    scores = service.score(week, None)
    flagged = [s for s in scores if s.band == "high" and s.segment == "resignation"]
    ids = [s.employee_id for s in flagged]
    audit(db, "loop.start", {"week_start": week, "flagged": ids}, source)
    interventions = []
    for s in flagged:
        for i, a in enumerate(s.actions[:2]):
            due = week + timedelta(weeks=a.check_after_weeks)
            new = engine.NewTask(
                idempotency_key=f"loop:{week}:{s.employee_id}:{a.driver}:{i}",
                title=f"{a.action} ({s.employee_id})", assignee=a.owner,
                supervisor="general manager", employee_id=s.employee_id,
                description=f"Driver: {a.driver}. Expected effect (ASSUMPTION): "
                            f"{a.expected_effect}",
                due_in_minutes=a.check_after_weeks * DAYS * 24 * 60)
            task, created = engine.create(db, new, cfg.tasks, now, source)
            if created:
                insert(db, INTERVENTIONS, {
                    "employee_id": s.employee_id, "week_start": week.isoformat(),
                    "driver": a.driver, "action": a.action, "owner": a.owner,
                    "due_date": due.isoformat(), "task_id": task["id"]}, source)
            interventions.append(InterventionOut(employee_id=s.employee_id, driver=a.driver,
                                                 action=a.action, owner=a.owner, due_date=due,
                                                 task_id=task["id"]))
    # Both rosters: cached when inputs match, else a DETERMINISTIC solve, so the before / after
    # numbers are identical on every run (B4b).
    base = generate(db, service, cfg.roster,
                    RosterRequest(use_cache=True, deterministic=True), source)
    prot = generate(db, service, cfg.roster,
                    RosterRequest(protected_ids=ids, use_cache=True, deterministic=True), source)
    for name, r in (("baseline", base), ("protected", prot)):
        if r.status == "infeasible":
            raise ValueError(f"{name} roster is infeasible: " + "; ".join(r.causes))
    hist = history(week)
    window = load_ml_config().attrition.hazard.overtime_window_weeks
    carry = carry_in(week, cfg.roster)
    rows_b, rows_p = _person_rows(base, week), _person_rows(prot, week)
    people = []
    for s in flagged:
        effects = {}
        overrides = {}
        for name, rows in (("baseline", rows_b), ("protected", rows_p)):
            p = rows[s.employee_id]
            ov = roster_overrides(p, hist, window, carry.get(s.employee_id, 0))
            r = service.rescore(s.employee_id, ov, week, None)
            overrides[name] = ov
            effects[name] = RosterEffect(overtime_hours=p["overtime_hours"],
                                         full_weekend_off=p["full_weekend_off"],
                                         days_worked=p["days_worked"], risk=r.after.risk,
                                         band=r.after.band, rank=r.after.rank)
        people.append(PersonResult(
            employee_id=s.employee_id, is_demo_hero=s.is_demo_hero, original_risk=s.risk,
            original_band=s.band, top_drivers=[d.category for d in s.drivers],
            baseline=effects["baseline"], protected=effects["protected"],
            risk_change=round(effects["protected"].risk - effects["baseline"].risk, 4),
            overrides_baseline=overrides["baseline"], overrides_protected=overrides["protected"]))
    totals = {name: {**r.cost, "coverage": coverage(r), "hard_violations": len(r.hard_violations),
                     "method": r.method} for name, r in (("baseline", base), ("protected", prot))}
    result = LoopResult(week_start=week, flagged=ids, interventions=interventions,
                        baseline_roster_id=base.id, protected_roster_id=prot.id, people=people,
                        totals=totals)
    audit(db, "loop.result", result.model_dump(mode="json"), source)
    return result


def task_status(task: dict | None, now: datetime) -> str:
    """open / acked / done from the task; overdue = not done and past its deadline."""
    if task is None:
        return "missing"  # the task was removed (e.g. a partial reset): never hide the row
    if task["status"] != engine.DONE and engine._aware(task["deadline"]) < now:
        return "overdue"
    return task["status"]


def list_interventions(db: Database, now: datetime, status: str = "all",
                       employee_id: str | None = None,
                       week_start: date | None = None) -> list[InterventionRecord]:
    """Stored interventions (oldest first) joined with their task; status open = not done."""
    q: dict = {}
    if employee_id:
        q["employee_id"] = employee_id
    if week_start:
        q["week_start"] = week_start.isoformat()
    rows = list(db[INTERVENTIONS].find(q, NO_ID).sort("id", 1))
    ids = [r["task_id"] for r in rows]
    tasks = {t["id"]: t for t in db[TASKS].find({"id": {"$in": ids}}, NO_ID)}
    out = []
    for r in rows:
        task = tasks.get(r["task_id"])
        st = task_status(task, now)
        if (status == "done" and st != "done") or (status == "open" and st == "done"):
            continue
        out.append(InterventionRecord(
            **{k: r[k] for k in ("id", "employee_id", "week_start", "driver", "action", "owner",
                                 "due_date", "task_id", "created_at")},
            task_status=st, task_deadline=task["deadline"] if task else None,
            task_done_at=task.get("done_at") if task else None))
    return out


def router(get_db, get_service, source_of) -> APIRouter:  # noqa: ANN001
    r = APIRouter()

    @r.post("/loop/run", response_model=LoopResult)
    def loop_run(request: Request, db: Database = Depends(get_db),
                 service: Service = Depends(get_service)) -> LoopResult:
        try:
            return run_loop(db, service, request.app.state.settings.config,
                            request.app.state.clock.now(), source_of(request))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    @r.get("/interventions", response_model=list[InterventionRecord])
    def interventions(request: Request,
                      status: Literal["open", "done", "all"] = Query(default="all"),
                      employee_id: str | None = None, week_start: date | None = None,
                      db: Database = Depends(get_db)) -> list[InterventionRecord]:
        return list_interventions(db, request.app.state.clock.now(), status, employee_id,
                                  week_start)

    return r
