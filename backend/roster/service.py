"""Roster use cases and endpoints (B2): generate a roster for a week, store it, fetch it.

The week must be the snapshot week (the employee_snapshot collection); occupancy comes from
forecast.predict for that week. Each result is saved as one roster document with its assignments
embedded (one atomic write) and every run is written to audit_log. All data is SYNTHETIC.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo.database import Database

from backend.config import RosterConfig
from backend.db import EMPLOYEES, NO_ID, ROSTERS, audit, insert, json_safe
from backend.roster.problem import DAYS, Problem, build_problem
from backend.roster.solver import Outcome, solve
from backend.services import Service


class RosterRequest(BaseModel):
    week_start: date | None = None  # default: the snapshot week
    protected_ids: list[str] = Field(default_factory=list)  # protected-off bonus applies
    use_cache: bool = False  # return the cached demo-week roster when its inputs match
    deterministic: bool = False  # reproducible solve (demo week); slower than the default


class AssignmentOut(BaseModel):
    employee_id: str
    date: date
    shift: str
    hours: int


class RosterResult(BaseModel):
    id: int
    week_start: date
    method: str
    status: str
    solve_seconds: float
    objective: float | None
    protected_ids: list[str]
    hard_violations: list[str]
    causes: list[str]  # why the week is infeasible (status "infeasible", no assignments)
    coverage: list[dict]
    cost: dict
    people: list[dict]
    violated_soft_goals: list[dict]
    assignments: list[AssignmentOut]
    synthetic: bool = True


def snapshot_rows(db: Database) -> list[dict]:
    rows = db[EMPLOYEES].find({}, NO_ID).sort("employee_id", 1)
    return [{"employee_id": r["employee_id"], "department": r["department"],
             "skills": json.dumps(r["skills"]), "monthly_pay": r["monthly_pay"],
             "leave_days": r["leave_days"], "is_demo_hero": r["is_demo_hero"],
             "week_start": date.fromisoformat(r["week_start"])} for r in rows]


def make_problem(db: Database, service: Service, cfg: RosterConfig,
                 week_start: date | None, protected: list[str]) -> Problem:
    rows = snapshot_rows(db)
    week = rows[0]["week_start"]
    if week_start is not None and week_start != week:
        raise ValueError(f"rosters can be generated for the snapshot week {week} only")
    unknown = sorted(set(protected) - {r["employee_id"] for r in rows})
    if unknown:
        raise ValueError(f"protected_ids not in the snapshot: {unknown}")
    days = service.forecast(week, week + timedelta(days=DAYS - 1), None).days
    return build_problem(week, rows, [d.mean for d in days], cfg, frozenset(protected))


def store(db: Database, problem: Problem, outcome: Outcome, source: str) -> RosterResult:
    hours = {n: s.hours for n, s in problem.cfg.shifts.items()}
    summary = {**outcome.summary, "solve_seconds": outcome.solve_seconds,
               "objective": outcome.objective, "hard_violations": outcome.hard_violations,
               "causes": outcome.causes, "protected_ids": sorted(problem.protected)}
    assignments = [{"employee_id": a.employee_id, "day": problem.days[a.day].isoformat(),
                    "shift": a.shift, "hours": float(hours[a.shift])}
                   for a in outcome.assignments]
    roster = insert(db, ROSTERS, {"week_start": problem.week_start.isoformat(),
                                  "method": outcome.method, "status": outcome.status,
                                  "summary": json_safe(summary), "assignments": assignments},
                    source)
    audit(db, "roster.generate", {"roster_id": roster["id"], "method": outcome.method,
                                       "status": outcome.status,
                                       "hard_violations": len(outcome.hard_violations),
                                       "causes": outcome.causes,
                                       "protected_ids": sorted(problem.protected),
                                       "cost": outcome.summary.get("cost")}, source)
    return load(db, roster["id"])


def load(db: Database, roster_id: int) -> RosterResult:
    roster = db[ROSTERS].find_one({"id": roster_id}, NO_ID)
    if roster is None:
        raise LookupError(f"roster {roster_id} not found")
    s = roster["summary"]
    rows = sorted(roster["assignments"], key=lambda a: (a["day"], a["employee_id"]))
    return RosterResult(
        id=roster["id"], week_start=date.fromisoformat(roster["week_start"]),
        method=roster["method"], status=roster["status"],
        solve_seconds=s["solve_seconds"], objective=s["objective"],
        protected_ids=s["protected_ids"], hard_violations=s["hard_violations"],
        causes=s.get("causes", []),
        coverage=s["coverage"], cost=s["cost"], people=s["people"],
        violated_soft_goals=s["violated_soft_goals"],
        assignments=[AssignmentOut(employee_id=r["employee_id"], date=date.fromisoformat(r["day"]),
                                   shift=r["shift"], hours=int(r["hours"])) for r in rows])


def generate(db: Database, service: Service, cfg: RosterConfig, body: RosterRequest,
             source: str) -> RosterResult:
    problem = make_problem(db, service, cfg, body.week_start, body.protected_ids)
    outcome = solve(problem, use_cache=body.use_cache, deterministic=body.deterministic)
    return store(db, problem, outcome, source)


def router(get_db, get_service, source_of) -> APIRouter:  # noqa: ANN001
    r = APIRouter()

    @r.post("/roster/generate", response_model=RosterResult)
    def roster_generate(body: RosterRequest, request: Request,
                        db: Database = Depends(get_db),
                        service: Service = Depends(get_service)) -> RosterResult:
        cfg = request.app.state.settings.config.roster
        try:
            return generate(db, service, cfg, body, source_of(request))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    @r.get("/roster/{roster_id}", response_model=RosterResult)
    def roster_get(roster_id: int, db: Database = Depends(get_db)) -> RosterResult:
        try:
            return load(db, roster_id)
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    return r

