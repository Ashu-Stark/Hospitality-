"""Typed views of the HOI API responses.

Field names match the live backend's OpenAPI schema (captured 2026-10-13 from
https://hospitality-management-9jdk.onrender.com/openapi.json). Every response
passes through a `parse_*` function. A missing required field is recorded in
SCHEMA_WARNINGS (shown on the Admin page) instead of crashing a page, so a
backend schema change shows up in one place.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

SCHEMA_WARNINGS: dict[str, str] = {}


def req(d: dict, key: str, ctx: str, default: Any = None) -> Any:
    if isinstance(d, dict) and key in d:
        return d[key]
    SCHEMA_WARNINGS[f"{ctx}.{key}"] = f"{ctx}: expected field '{key}' is missing"
    return default


def as_list(v: Any) -> list:
    return v if isinstance(v, list) else []


def norm_band(v: Any) -> str:
    s = str(v or "").strip().lower()
    return s if s in {"high", "watch", "low"} else "unknown"


def norm_basis(v: Any) -> str:
    s = str(v or "").lower()
    return "contract_date" if ("contract" in s or "date" in s) else "model_rank"


def norm_support(v: Any) -> str:
    s = str(v or "").lower().replace(" ", "_").replace("-", "_")
    if s.startswith("un"):
        return "unsupported"
    if "weak" in s:
        return "weakly_supported"
    return "supported"


def parse_dt(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def pretty(s: str) -> str:
    return str(s).replace("_", " ").capitalize()


# ------------------------------------------------------------------ attrition
@dataclass
class Driver:
    category: str
    title: str
    reason: str
    contribution_logodds: float
    support_level: str


@dataclass
class Action:
    driver: str
    action: str
    owner: str
    check_after_weeks: int | None
    expected_effect: str


@dataclass
class AttritionScore:
    employee_id: str
    week_start: str
    segment: str  # "resignation" (permanent) | "contract_end" (seasonal)
    model: str
    risk: float
    rank: int | None
    group_size: int | None
    band: str
    band_basis: str  # normalized: "model_rank" | "contract_date"
    rank_is_tied: bool
    is_demo_hero: bool
    drivers: list[Driver]
    actions: list[Action]
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def contract_type(self) -> str:
        return "seasonal" if self.segment == "contract_end" else "permanent"

    @property
    def top_driver(self) -> Driver | None:
        pos = [d for d in self.drivers if d.contribution_logodds > 0]
        return max(pos, key=lambda d: d.contribution_logodds) if pos else None


def parse_driver(d: dict) -> Driver:
    cat = str(req(d, "category", "Driver", "unknown"))
    return Driver(
        cat,
        str(d.get("title") or pretty(cat)),
        str(d.get("reason") or ""),
        float(req(d, "contribution_logodds", "Driver", 0.0)),
        norm_support(d.get("support_level")),
    )


def parse_action(a: dict) -> Action:
    return Action(
        str(a.get("driver") or ""),
        str(req(a, "action", "Action", "")),
        str(a.get("owner") or "manager"),
        a.get("check_after_weeks"),
        str(a.get("expected_effect") or ""),
    )


def parse_score(e: dict) -> AttritionScore:
    c = "AttritionScore"
    return AttritionScore(
        employee_id=str(req(e, "employee_id", c, "?")),
        week_start=str(e.get("week_start") or ""),
        segment=str(req(e, "segment", c, "resignation")),
        model=str(e.get("model") or ""),
        risk=float(req(e, "risk", c, 0.0)),
        rank=req(e, "rank", c),
        group_size=e.get("group_size"),
        band=norm_band(req(e, "band", c)),
        band_basis=norm_basis(req(e, "band_basis", c)),
        rank_is_tied=bool(e.get("rank_is_tied")),
        is_demo_hero=bool(e.get("is_demo_hero")),
        drivers=[parse_driver(x) for x in as_list(e.get("drivers"))],
        actions=[parse_action(x) for x in as_list(e.get("actions"))],
        raw=e,
    )


def parse_scores(d: Any) -> list[AttritionScore]:
    rows = d if isinstance(d, list) else as_list((d or {}).get("items"))
    return [parse_score(r) for r in rows if isinstance(r, dict)]


# ------------------------------------------------------------------ forecast
@dataclass
class ForecastDay:
    date: str
    horizon_days: int | None
    source: str
    mean: float
    low: float
    high: float
    high_demand_alert: bool
    low_demand_alert: bool


@dataclass
class Forecast:
    as_of: str
    band: str
    days: list[ForecastDay]


def parse_forecast(d: dict) -> Forecast:
    days = []
    for r in as_list(req(d, "days", "ForecastResult", [])):
        m = float(req(r, "mean", "ForecastDay", 0.0))
        days.append(
            ForecastDay(
                str(r.get("date")),
                r.get("horizon_days"),
                str(r.get("source") or ""),
                m,
                float(r.get("low", m)),
                float(r.get("high", m)),
                bool(r.get("high_demand_alert")),
                bool(r.get("low_demand_alert")),
            )
        )
    return Forecast(str(d.get("as_of") or ""), str(d.get("band") or ""), days)


# ------------------------------------------------------------------ heroes (mock-only file)
@dataclass
class HeroWeek:
    week_start: str
    risk: float
    rank: int | None
    band: str
    overtime_hours: float | None = None
    weeks_since_weekend_off: float | None = None
    note: str | None = None


@dataclass
class Hero:
    employee_id: str
    display_name: str
    story: str
    department: str | None
    weeks: list[HeroWeek]
    illustrative: bool = False


def parse_heroes(d: Any) -> list[Hero]:
    rows = d if isinstance(d, list) else as_list((d or {}).get("heroes"))
    illustrative = bool((d or {}).get("illustrative")) if isinstance(d, dict) else False
    out = []
    for h in rows:
        weeks = [
            HeroWeek(
                str(w.get("week_start")),
                float(w.get("risk") or w.get("risk_score") or 0.0),
                w.get("rank"),
                norm_band(w.get("band")),
                w.get("overtime_hours"),
                w.get("weeks_since_weekend_off"),
                w.get("note") or w.get("annotation"),
            )
            for w in as_list(h.get("weeks") or h.get("trajectory") or h.get("history"))
        ]
        out.append(
            Hero(
                str(h.get("employee_id")),
                str(h.get("display_name") or h.get("name") or ""),
                str(h.get("story") or ""),
                h.get("department"),
                weeks,
                illustrative,
            )
        )
    return out


# ------------------------------------------------------------------ rescore
@dataclass
class RescoreResult:
    employee_id: str
    week_start: str
    overrides: dict
    features_before: dict
    features_after: dict
    before: AttritionScore
    after: AttritionScore
    risk_change: float
    note: str
    raw: dict = field(default_factory=dict, repr=False)


def parse_rescore(d: dict) -> RescoreResult:
    c = "RescoreResult"
    before, after = parse_score(req(d, "before", c, {})), parse_score(req(d, "after", c, {}))
    rc = d.get("risk_change")
    return RescoreResult(
        str(req(d, "employee_id", c, "?")),
        str(d.get("week_start") or ""),
        d.get("overrides") or {},
        d.get("features_before") or {},
        d.get("features_after") or {},
        before,
        after,
        float(rc if rc is not None else after.risk - before.risk),
        str(d.get("note") or ""),
        d,
    )


# ------------------------------------------------------------------ roster
SHIFT_ORDER = ["morning", "evening", "night"]
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass
class Roster:
    id: int | None
    week_start: str
    method: str
    status: str
    solve_seconds: float | None
    protected_ids: list[str]
    hard_violations: list
    causes: list
    coverage: list[dict]
    cost: dict
    people: list[dict]
    violated_soft_goals: list[dict]
    assignments: list[dict]
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def feasible(self) -> bool:
        return self.status.lower() not in {"infeasible", "failed", "error", "unknown", "model_invalid"} and not self.causes

    @property
    def dept_of(self) -> dict[str, str]:
        return {p["employee_id"]: p.get("department", "unknown") for p in self.people}

    @property
    def dates(self) -> list[str]:
        return sorted({a["date"] for a in self.assignments})

    @property
    def coverage_ratio(self) -> float | None:
        req_h = sum(c.get("required_hours", 0) for c in self.coverage)
        sch_h = sum(min(c.get("scheduled_hours", 0), c.get("required_hours", 0)) for c in self.coverage)
        return sch_h / req_h if req_h else None

    def short_by_cell(self) -> dict[tuple[str, int, str], float]:
        """(department, day_index, shift) -> hours short, from the 'understaffed' soft-goal entries."""
        out: dict[tuple[str, int, str], float] = defaultdict(float)
        for g in self.violated_soft_goals:
            if g.get("goal") == "understaffed":
                out[(g.get("department"), int(g.get("day", 0)), g.get("shift"))] += float(g.get("hours_short", 0))
        return out

    def cell_people(self) -> dict[tuple[str, str, str], list[str]]:
        """(department, date, shift) -> employee_ids assigned."""
        dept = self.dept_of
        out: dict[tuple[str, str, str], list[str]] = defaultdict(list)
        for a in self.assignments:
            out[(dept.get(a["employee_id"], "unknown"), a["date"], a["shift"])].append(a["employee_id"])
        return out


def parse_roster(d: dict) -> Roster:
    c = "RosterResult"
    return Roster(
        d.get("id"),
        str(d.get("week_start") or ""),
        str(d.get("method") or ""),
        str(req(d, "status", c, "unknown")),
        d.get("solve_seconds"),
        as_list(d.get("protected_ids")),
        as_list(d.get("hard_violations")),
        as_list(d.get("causes")),
        as_list(d.get("coverage")),
        d.get("cost") or {},
        as_list(d.get("people")),
        as_list(d.get("violated_soft_goals")),
        as_list(d.get("assignments")),
        d,
    )


# ------------------------------------------------------------------ tasks
@dataclass
class Task:
    id: int | str
    idempotency_key: str
    title: str
    description: str
    assignee: str
    supervisor: str
    employee_id: str | None
    status: str  # normalized: open | acked | done
    created_at: datetime | None
    deadline: datetime | None
    acked_at: datetime | None
    done_at: datetime | None
    events: list[dict]
    raw: dict = field(default_factory=dict, repr=False)

    def deadline_fraction(self, now: datetime) -> float | None:
        if not self.created_at or not self.deadline or self.deadline <= self.created_at:
            return None
        return (now - self.created_at).total_seconds() / (self.deadline - self.created_at).total_seconds()

    @property
    def escalated(self) -> bool:
        return any("escalat" in str(e.get("kind", "")).lower() for e in self.events)


def norm_status(s: Any) -> str:
    s = str(s or "open").lower()
    return {"created": "open", "new": "open", "acknowledged": "acked", "ack": "acked", "completed": "done", "closed": "done"}.get(s, s)


def parse_task(t: dict) -> Task:
    c = "TaskOut"
    return Task(
        req(t, "id", c, "?"),
        str(t.get("idempotency_key") or ""),
        str(req(t, "title", c, "(untitled)")),
        str(t.get("description") or ""),
        str(t.get("assignee") or "unassigned"),
        str(t.get("supervisor") or ""),
        t.get("employee_id") or None,
        norm_status(t.get("status")),
        parse_dt(t.get("created_at")),
        parse_dt(t.get("deadline")),
        parse_dt(t.get("acked_at")),
        parse_dt(t.get("done_at")),
        as_list(t.get("events")),
        t,
    )


def parse_tasks(d: Any) -> list[Task]:
    rows = d if isinstance(d, list) else as_list((d or {}).get("tasks"))
    return [parse_task(t) for t in rows if isinstance(t, dict)]


# ------------------------------------------------------------------ loop
@dataclass
class Effect:
    overtime_hours: float
    full_weekend_off: bool
    days_worked: int
    risk: float
    band: str
    rank: int | None


@dataclass
class LoopPerson:
    employee_id: str
    is_demo_hero: bool
    original_risk: float
    original_band: str
    top_drivers: list[str]
    baseline: Effect
    protected: Effect
    risk_change: float


@dataclass
class LoopResult:
    week_start: str
    flagged: list[str]
    interventions: list[dict]
    baseline_roster_id: int | None
    protected_roster_id: int | None
    people: list[LoopPerson]
    totals: dict
    note: str
    raw: dict = field(default_factory=dict, repr=False)


def _effect(d: dict) -> Effect:
    d = d or {}
    return Effect(
        float(d.get("overtime_hours", 0)),
        bool(d.get("full_weekend_off")),
        int(d.get("days_worked", 0)),
        float(d.get("risk", 0)),
        norm_band(d.get("band")),
        d.get("rank"),
    )


def parse_loop(d: dict) -> LoopResult:
    c = "LoopResult"
    people = [
        LoopPerson(
            str(p.get("employee_id")),
            bool(p.get("is_demo_hero")),
            float(p.get("original_risk", 0)),
            norm_band(p.get("original_band")),
            [str(x) for x in as_list(p.get("top_drivers"))],
            _effect(p.get("baseline")),
            _effect(p.get("protected")),
            float(p.get("risk_change", 0)),
        )
        for p in as_list(req(d, "people", c, []))
    ]
    return LoopResult(
        str(d.get("week_start") or ""),
        [str(x) for x in as_list(req(d, "flagged", c, []))],
        as_list(req(d, "interventions", c, [])),
        d.get("baseline_roster_id"),
        d.get("protected_roster_id"),
        people,
        d.get("totals") or {},
        str(d.get("note") or ""),
        d,
    )


# ------------------------------------------------------------------ metrics / misc
@dataclass
class Metrics:
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
    roi_note: str


def parse_metrics(d: dict) -> Metrics:
    c = "MetricsOverview"
    g = lambda k, default=0: req(d, k, c, default)  # noqa: E731
    return Metrics(
        g("roster_id", None),
        float(g("overtime_hours")),
        float(g("overtime_cost_inr")),
        float(g("total_roster_cost_inr")),
        int(g("understaffed_shifts")),
        int(g("tasks_total")),
        g("tasks_on_time_rate", None),
        int(g("flagged_count")),
        int(g("flagged_still_employed")),
        float(g("replacement_cost_inr")),
        float(g("roi_inr")),
        str(d.get("roi_note") or ""),
    )


@dataclass
class Clock:
    multiplier: float
    virtual_now: datetime | None


def parse_clock(d: dict) -> Clock:
    return Clock(float(req(d, "multiplier", "ClockOut", 1.0)), parse_dt(req(d, "virtual_now", "ClockOut")))
