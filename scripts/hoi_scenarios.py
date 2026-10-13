"""Operational scenarios for the FICTIONAL "Himsagar Ridge Resort, Mussoorie" (ALL DATA SYNTHETIC).

Reusable by scripts/scenario_report.py (numbers) and scripts/tests/test_scenarios.py (assertions). Everything here runs
IN-PROCESS on mongomock: the ops backend (backend/, hotel "himsagar") and the platform API (platform_api/) as FastAPI
TestClients. Call configure_offline_env() BEFORE importing either app (it forces mongomock, disables the cloud AI so the
concierge uses its rule-based path, and lifts the per-IP rate limits that a simulation from one client would hit).

Sections:
  roster_demo_week()    the demo week through POST /roster/generate (cached deterministic roster)
  roster_stress()       N random scenarios (leave, absences, peak / low weeks, a staff member removed, carried-in runs)
  roster_rolling()      4 consecutive weeks with the consecutive-day run (and last shift) carried from week to week
  DaySim                one full day 06:00-23:00 of jobs through the REAL dispatch engine on a virtual clock
  ops_loop(), onboarding_demo()   attrition scoring + closed loop; voice onboarding (typed) creating this hotel
Assumptions of the simulation itself (worker response probabilities, durations, arrival rates) are ASSUMED and listed in
SIM_ASSUMPTIONS; they are inputs to a stress test, not measurements.
"""

from __future__ import annotations

import heapq
import io
import itertools
import os
import statistics
import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "platform_api"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

HOTEL = "himsagar"
IST = timedelta(hours=5, minutes=30)
SHIFT_WINDOWS = {"morning": (6, 15), "evening": (14, 23), "night": (22, 31)}  # local hours, night ends 07:00 next day
SIM_ASSUMPTIONS = {
    "offer_response": "accept 80% / decline 10% / no answer (timeout) 10%; busy workers (2+ open jobs) decline 35%",
    "response_delay_s": "accept 4-20 s, decline 3-10 s after the offer",
    "travel_min": "2-6 min from accept to start (before photo)",
    "durations_min": "checkout clean 25-40, re-clean 10-20, linen/water/amenities 5-12, tea/food 10-25, maintenance 20-55, front desk 5-15",
    "inspection": "5-20 min after the clean; pass 85% (a re-clean always passes)",
    "escalation": "an unassigned job is retried by the supervisor every 10 min, at most 3 times",
    "day": "the demo-week day on which most flagged staff work (ties: Christmas Day); all 24 rooms change over that day "
    "(peak changeover stress test)",
    "guest_requests": "about 2.6 per occupied room per day from the concierge menu, morning and evening peaks",
}


def configure_offline_env() -> None:
    """In-process mode: mongomock only, no cloud AI, no rate limits for a one-client simulation."""
    os.environ["MONGODB_URI"] = "mongomock://"  # never the real cluster
    os.environ["HOI_PLATFORM_DB"] = f"hoi_platform_scn_{uuid.uuid4().hex[:8]}"
    os.environ["HOI_HOTEL_DATA"] = HOTEL
    os.environ.setdefault("HOI_ADMIN_PASSWORD", "scenario-admin-pw")
    for k, v in {
        "HOI_DEMO_LOGIN": "true",
        "HOI_SEED_DEMO": "true",
        "HOI_GUEST_AI_ENABLED": "false",
        "HOI_LOGIN_RATE_PER_MINUTE": "100000",
        "HOI_GUEST_CHAT_RATE_PER_MINUTE": "100000",
        "HOI_GUEST_STT_RATE_PER_MINUTE": "100000",
        "HOI_GUEST_ACTION_RATE_PER_MINUTE": "100000",
        "HOI_TTS_RATE_PER_MINUTE": "100000",
    }.items():
        os.environ[k] = v
    for k in ("GROQ_API_KEY", "LLM_API_KEY", "GROQ_API_KEYS_BACKUP", "LLM_API_KEYS_BACKUP", "SARVAM_API_KEY", "LOCATIONIQ_API_KEY"):
        os.environ.pop(k, None)  # the concierge must take its rule-based path (no AI calls)


def pct(a: float, b: float) -> float | None:
    return round(100.0 * a / b, 1) if b else None


def med(xs: list[float]) -> float | None:
    return round(statistics.median(xs), 1) if xs else None


def p90(xs: list[float]) -> float | None:
    return round(float(np.percentile(xs, 90)), 1) if xs else None


# =============================================================== roster
def roster_stats(summary: dict, staff_by_dept: dict[str, list[str]]) -> dict:
    """Coverage %, overtime and fairness spreads (max - min inside each department; non-workers count as 0)."""
    cov = summary["coverage"]
    req = sum(c["required_hours"] for c in cov)
    got = sum(min(c["scheduled_hours"], c["required_hours"]) for c in cov)
    people = {p["employee_id"]: p for p in summary["people"]}
    spread = {}
    for dept, members in staff_by_dept.items():
        hours = [people.get(e, {}).get("hours", 0) for e in members]
        wkend = [people.get(e, {}).get("weekend_shifts", 0) for e in members]
        spread[dept] = {"hours": max(hours) - min(hours), "weekend_shifts": max(wkend) - min(wkend)}
    return {
        "coverage_pct": pct(got, req),
        "overtime_hours": summary["cost"]["overtime_hours"],
        "understaffed_shifts": summary["cost"]["understaffed_shifts"],
        "understaffed_hours": summary["cost"]["understaffed_hours"],
        "max_hours_spread": max((v["hours"] for v in spread.values()), default=0),
        "max_weekend_spread": max((v["weekend_shifts"] for v in spread.values()), default=0),
        "spread_by_department": spread,
    }


def _dept_members(staff) -> dict[str, list[str]]:  # noqa: ANN001
    out: dict[str, list[str]] = defaultdict(list)
    for s in staff:
        out[s.department].append(s.employee_id)
    return dict(out)


def roster_demo_week(ops) -> dict:  # noqa: ANN001
    """The demo week through the API (cached deterministic roster), plus its stats."""
    from backend.roster.service import make_problem

    r = ops.post("/roster/generate", json={"use_cache": True, "deterministic": True}).json()
    problem = make_problem(ops.app.state.db, ops.app.state.service, ops.app.state.settings.config.roster, None, [])
    summary = {"coverage": r["coverage"], "cost": r["cost"], "people": r["people"]}
    return {
        "roster": r,
        "status": r["status"],
        "method": r["method"],
        "hard_violations": len(r["hard_violations"]),
        "solve_seconds": r["solve_seconds"],
        "shifts": len(r["assignments"]),
        **roster_stats(summary, _dept_members(problem.staff)),
    }


STRESS_KINDS = ("random", "peak_week", "low_season", "heavy_leave", "sudden_absences", "staff_removed")


def stress_problems(n: int, seed: int, carry_mode: str = "random") -> list[tuple[str, str, Any]]:
    """(kind, description, Problem) for n seeded scenarios on the demo-week staff. carry_mode "random": every person
    carries a random 0-6 day run into the week (as backend/roster/stress.py, deliberately harsh); "data": the run
    actually carried into the demo week (ml weekly_signals)."""
    from backend.config import hotel_data, load_backend_config
    from backend.db import snapshot_frame
    from backend.roster.problem import DAYS, build_problem, carry_in

    cfg = load_backend_config(hotel=HOTEL).roster
    data_carry = carry_in(cfg.demo_week, cfg)
    rows = snapshot_frame(hotel_data(HOTEL).data_dir).to_dict("records")
    rng = np.random.default_rng([seed, n, 20])
    out = []
    for i in range(n):
        kind = STRESS_KINDS[i % len(STRESS_KINDS)]
        lo, hi = {"peak_week": (0.85, 1.0), "low_season": (0.2, 0.45)}.get(kind, (0.35, 0.95))
        occ = rng.uniform(lo, hi, DAYS).round(3).tolist()
        drawn = {r["employee_id"]: int(rng.integers(0, 7)) for r in rows}  # always drawn: streams stay aligned
        carry = drawn if carry_mode == "random" else data_carry
        base = build_problem(cfg.demo_week, rows, occ, cfg, carry=carry)
        probs = [0.45, 0.3, 0.15, 0.1] if kind == "heavy_leave" else [0.75, 0.15, 0.07, 0.03]
        staff, notes = [], []
        for s in base.staff:
            k = int(rng.choice([0, 1, 2, 3], p=probs))
            start = int(rng.integers(0, DAYS - k + 1))
            staff.append(replace(s, leave_days=frozenset(range(start, start + k))))
        if kind == "sudden_absences":
            for j in rng.choice(len(staff), size=3, replace=False):
                day = int(rng.integers(0, DAYS))
                staff[j] = replace(staff[j], leave_days=staff[j].leave_days | {day})
                notes.append(f"{staff[j].employee_id} absent day {day}")
        if kind == "staff_removed":
            gone = staff.pop(int(rng.integers(0, len(staff))))
            notes.append(f"{gone.employee_id} ({gone.department}) removed")
        desc = f"occupancy {min(occ):.2f}-{max(occ):.2f}; leave days {sum(len(s.leave_days) for s in staff)}" + (
            "; " + ", ".join(notes) if notes else ""
        )
        out.append((kind, desc, replace(base, staff=staff)))
    return out


def roster_stress(n: int = 100, seed: int = 42, carry_mode: str = "random") -> dict:
    from backend.roster.check import hard_violations
    from backend.roster.solver import solve

    rows, causes_by_dept = [], Counter()
    for i, (kind, desc, p) in enumerate(stress_problems(n, seed, carry_mode)):
        o = solve(p)
        recheck = hard_violations(p, o.assignments) if o.assignments else []
        row = {
            "i": i,
            "kind": kind,
            "desc": desc,
            "status": o.status,
            "method": o.method,
            "seconds": round(o.solve_seconds, 3),
            "published": bool(o.assignments),
            "hard_violations": len(o.hard_violations) + len(recheck),
            "causes": o.causes,
        }
        if o.assignments:
            row.update(roster_stats(o.summary, _dept_members(p.staff)))
        for c in o.causes:
            causes_by_dept[c.split(",")[0]] += 1
        rows.append(row)
    solved = [r for r in rows if r["published"]]
    secs = [r["seconds"] for r in rows]
    by_kind = {k: dict(Counter(r["status"] for r in rows if r["kind"] == k)) for k in STRESS_KINDS}
    return {
        "scenarios": n,
        "carry_mode": carry_mode,
        "solved": len(solved),
        "infeasible": sum(r["status"] == "infeasible" for r in rows),
        "infeasible_with_causes": sum(bool(r["causes"]) for r in rows if r["status"] == "infeasible"),
        "hard_violations_total": sum(r["hard_violations"] for r in rows),
        "statuses": dict(Counter(r["status"] for r in rows)),
        "by_kind": by_kind,
        "infeasible_causes_by_department": dict(causes_by_dept),
        "solve_seconds": {"median": med(secs), "p95": round(float(np.percentile(secs, 95)), 2), "max": max(secs)},
        "coverage_pct_mean": round(statistics.mean(r["coverage_pct"] for r in solved), 1) if solved else None,
        "coverage_pct_min": min((r["coverage_pct"] for r in solved), default=None),
        "overtime_hours_mean": round(statistics.mean(r["overtime_hours"] for r in solved), 1) if solved else None,
        "overtime_hours_max": max((r["overtime_hours"] for r in solved), default=None),
        "hours_spread_max": max((r["max_hours_spread"] for r in solved), default=None),
        "weekend_spread_max": max((r["max_weekend_spread"] for r in solved), default=None),
        "examples_infeasible": [
            {"i": r["i"], "kind": r["kind"], "desc": r["desc"], "causes": r["causes"][:3]} for r in rows if r["status"] == "infeasible"
        ][:6],
        "results": rows,
    }


def _last_run(days_worked: set[int], carry: int, n_days: int = 7) -> int:
    run = 0
    for d in range(n_days - 1, -1, -1):
        if d in days_worked:
            run += 1
        else:
            return run
    return run + carry  # worked every day: the run continues from the previous week


def roster_rolling(weeks: int = 4, carry_last_shift: bool = True) -> dict:
    """`weeks` consecutive weeks ending with the demo week; week 1 carries the run from the ml signals, later weeks
    from the previous solved roster. Stitched check: consecutive days (<= max) and rest across the week boundaries."""
    import pandas as pd

    from backend.config import hotel_data, load_backend_config
    from backend.db import snapshot_frame
    from backend.roster.problem import DAYS, build_problem, carry_in, forbidden_pairs
    from backend.roster.solver import solve
    from backend.services import ModelService

    cfg = load_backend_config(hotel=HOTEL).roster
    data = hotel_data(HOTEL).data_dir
    rows = snapshot_frame(data).to_dict("records")
    beh = pd.read_csv(data / "weekly_behaviour.csv")
    svc = ModelService(HOTEL)
    first = cfg.demo_week - timedelta(weeks=weeks - 1)
    carry = carry_in(first, cfg)
    last_shift: dict[str, str] = {}
    timeline: dict[str, dict[int, str]] = defaultdict(dict)
    bad = set(forbidden_pairs(cfg))
    out = []
    for w in range(weeks):
        week = first + timedelta(weeks=w)
        leave = beh[beh["week_start"] == str(week)].set_index("employee_id")["leave_days"].to_dict()
        wk_rows = [{**r, "leave_days": int(leave.get(r["employee_id"], 0))} for r in rows]
        occ = [d.mean for d in svc.forecast(week, week + timedelta(days=DAYS - 1), None).days]
        p = build_problem(week, wk_rows, occ, cfg, carry=carry, last_shift=last_shift if carry_last_shift else None)
        o = solve(p, deterministic=True)  # reproducible: each week depends on the previous roster
        stats = roster_stats(o.summary, _dept_members(p.staff)) if o.assignments else {}
        cross_rest = 0
        days_by: dict[str, set[int]] = defaultdict(set)
        for a in o.assignments:
            days_by[a.employee_id].add(a.day)
            timeline[a.employee_id][w * DAYS + a.day] = a.shift
            if a.day == 0 and (last_shift.get(a.employee_id), a.shift) in bad:
                cross_rest += 1
        out.append(
            {
                "week_start": str(week),
                "status": o.status,
                "seconds": round(o.solve_seconds, 2),
                "hard_violations": len(o.hard_violations),
                "rest_violations_across_boundary": cross_rest,
                "carry_in_max": max(carry.values(), default=0),
                "causes": o.causes[:3],
                **{k: v for k, v in stats.items() if k != "spread_by_department"},
            }
        )
        if not o.assignments:
            break
        carry = {s.employee_id: min(_last_run(days_by.get(s.employee_id, set()), s.carry_days), cfg.max_consecutive_days) for s in p.staff}
        last_shift = {
            e: d[DAYS - 1] for e in timeline if (d := {k - w * DAYS: v for k, v in timeline[e].items() if k >= w * DAYS}) and DAYS - 1 in d
        }
    longest = 0
    for e, t in timeline.items():
        run = 0
        for d in range(weeks * DAYS):
            run = run + 1 if d in t else 0
            longest = max(longest, run)
    return {
        "weeks": out,
        "max_consecutive_days_stitched": longest,
        "limit": cfg.max_consecutive_days,
        "rest_violations_across_boundaries": sum(w["rest_violations_across_boundary"] for w in out),
    }


# =============================================================== apps
def ops_client():  # noqa: ANN201
    from fastapi.testclient import TestClient

    from backend.config import make_settings
    from backend.main import create_app

    s = make_settings(f"hoi_ops_scn_{uuid.uuid4().hex[:8]}", mongodb_uri="mongomock://", hotel=HOTEL)
    c = TestClient(create_app(s))
    c.__enter__()
    c.post("/demo/reset")
    return c


class Clock:
    """Virtual clock for the platform API (mongo.now, the guest page's local time, express-checkout due times)."""

    def __init__(self, start_utc: datetime) -> None:
        self.t = start_utc

    def now(self) -> datetime:
        return self.t.replace(microsecond=0)

    def install(self) -> None:
        import types

        from hoi_platform import mongo, ratelimit
        from hoi_platform.services import guest

        orig_next = guest.next_occurrence
        # the per-IP / per-room sliding windows run on the virtual clock too (limits stay active, at simulated speed)
        ratelimit.time = types.SimpleNamespace(monotonic=lambda: self.t.timestamp())
        mongo.now = self.now
        guest.local_now = lambda: self.t.astimezone(guest.tz())
        guest.next_occurrence = lambda hhmm, now=None: orig_next(hhmm, now or self.t)

    def set(self, t: datetime) -> None:
        self.t = max(self.t, t)  # monotonic


def platform_client(clock: Clock | None = None):  # noqa: ANN201
    """The platform API in-process; the demo hotel is seeded at startup (on the virtual clock when given)."""
    if clock is not None:
        clock.install()
    from fastapi.testclient import TestClient

    from hoi_platform import config

    config.reload()
    from hoi_platform.main import create_app

    c = TestClient(create_app())
    c.__enter__()
    return c


def bearer(client, username: str) -> dict:  # noqa: ANN001
    r = client.post(f"/auth/demo/{username}")
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def jpeg() -> bytes:
    from PIL import Image

    b = io.BytesIO()
    Image.new("RGB", (160, 120), (90, 140, 170)).save(b, "JPEG")
    return b.getvalue()


# =============================================================== day simulation
MENU_WEIGHTS = {
    "towels": 0.18,
    "water": 0.18,
    "tea": 0.15,
    "food": 0.15,
    "amenities": 0.1,
    "cleaning": 0.06,
    "hot_water": 0.07,
    "ac": 0.05,
    "electrical": 0.04,
    "other": 0.02,
}
LATE_LINES = {"12:00": "late checkout till 12", "13:00": "late checkout till 1", "14:00": "late checkout till 2"}
CHAT_LINES = {"towels": "Towels please", "ac": "AC not working", "food": "ek poha bhej do", "hot_water": "garam paani nahi aa raha"}
KITCHEN_JOBS = ["Jain meal for room {room}", "Birthday cake for room {room}", "Low-oil kids' meal for room {room}"]
SECURITY_JOBS = ["Noise complaint near room {room}", "Late-night gate opening for a returning guest"]
FAULTS = [
    ("Geyser not heating", "high"),
    ("Room heater tripping", "high"),
    ("Leaking tap in bathroom", "medium"),
    ("TV not switching on", "medium"),
    ("Door lock sticky", "medium"),
    ("Corridor light fused", "low"),
]
DURATION = {
    "cleaning": (25, 40),
    "reclean": (10, 20),
    "guest_hk": (5, 12),
    "guest_fnb": (10, 25),
    "maintenance": (20, 55),
    "front": (5, 15),
}


def pick_day(roster: dict, flagged: list[str], prefer: date = date(2029, 12, 25)) -> date:
    """The demo-week day on which most flagged (high-band) staff work a day shift, so the retention guard is exercised;
    ties go to Christmas Day (the peak)."""
    count = Counter(a["date"] for a in roster["assignments"] if a["employee_id"] in flagged and a["shift"] != "night")
    days = sorted({a["date"] for a in roster["assignments"]})
    best = max(days, key=lambda d: (count.get(d, 0), d == str(prefer), d))
    return date.fromisoformat(best)


@dataclass
class Worker:
    emp: str
    dept: str
    free_at: datetime
    done: int = 0
    open_jobs: set = field(default_factory=set)


class DaySim:
    """One day of operations through the real platform API (dispatch engine, rooms, guest pages, inventory)."""

    def __init__(
        self,
        ops,
        seed: int = 7,
        day: date | None = None,
        roster: dict | None = None,  # noqa: ANN001
        bands: dict[str, str] | None = None,
    ) -> None:
        self.rng = np.random.default_rng(seed)
        self.roster = roster if roster is not None else roster_demo_week(ops)["roster"]
        self.bands = bands or {}
        day = day or pick_day(self.roster, [e for e, b in self.bands.items() if b == "high"])
        self.day = day
        self.start = datetime(day.year, day.month, day.day, 6, 0, tzinfo=UTC) - IST  # 06:00 local
        self.end = self.start + timedelta(hours=17)  # 23:00 local
        self.clock = Clock(self.start - timedelta(days=1))  # the demo seed's history ends the day before
        self.pc = platform_client(self.clock)
        self.clock.set(self.start - timedelta(minutes=30))
        self.owner = bearer(self.pc, "demo.owner")
        self.hk_head = bearer(self.pc, "demo.housekeeping")
        self.fo_head = bearer(self.pc, "demo.frontoffice")
        self.store = bearer(self.pc, "demo.store")
        self.hs05 = bearer(self.pc, "HS05")
        self.photo = jpeg()
        self.q: list = []
        self.seq = itertools.count()
        self.workers: dict[str, Worker] = {}
        self.scheduled_offers: set = set()
        self.retries: Counter = Counter()
        self.offer_log: list[dict] = []
        self.violations: list[str] = []
        self.job_meta: dict[str, dict] = {}
        self.room_log: dict[str, dict] = {}
        self.events: Counter = Counter()
        self.concierge: Counter = Counter()
        self.late_ids: list[str] = []
        self.arrivals_waited: list[float] = []
        self.ctx_key = None
        self.staff_dept = {s["employee_id"]: s["department"] for s in self.pc.get("/workspace/staff", headers=self.owner).json()}

    # ------------------------------------------------------------ helpers
    def local(self, t: datetime) -> datetime:
        return t + IST

    def at(self, t: datetime, fn, *args) -> None:  # noqa: ANN001
        heapq.heappush(self.q, (t, next(self.seq), fn, args))

    def u(self, lo: float, hi: float) -> float:
        return float(self.rng.uniform(lo, hi))

    def on_shift(self, t: datetime) -> dict[str, str]:
        loc = self.local(t)
        out = {}
        for a in self.roster["assignments"]:
            d = date.fromisoformat(a["date"])
            s, e = SHIFT_WINDOWS[a["shift"]]
            start = datetime(d.year, d.month, d.day, tzinfo=UTC) + timedelta(hours=s)
            end = datetime(d.year, d.month, d.day, tzinfo=UTC) + timedelta(hours=e)
            if start <= loc.replace(tzinfo=UTC) < end:
                out[a["employee_id"]] = self.staff_dept[a["employee_id"]]
        return out

    def shift_end(self, emp: str, t: datetime) -> datetime | None:
        loc = self.local(t).replace(tzinfo=UTC)
        for a in self.roster["assignments"]:
            if a["employee_id"] != emp:
                continue
            d = date.fromisoformat(a["date"])
            s, e = SHIFT_WINDOWS[a["shift"]]
            start = datetime(d.year, d.month, d.day, tzinfo=UTC) + timedelta(hours=s)
            if start <= loc < start + timedelta(hours=e - s):
                return start + timedelta(hours=e - s) - IST
        return None

    def sync_context(self) -> None:
        working = self.on_shift(self.clock.t)
        key = tuple(sorted(working.items()))
        if key != self.ctx_key:
            bands = {e: b for e, b in self.bands.items() if e in working}
            self.pc.put(
                "/dispatch/context",
                json={"day": str(self.day), "shift": None, "working": working, "bands": bands, "floors": 3},
                headers=self.owner,
            ).raise_for_status()
            self.ctx_key = key

    def jobs(self) -> list[dict]:
        return self.pc.get("/dispatch/jobs", headers=self.owner).json()  # also sweeps expired offers and due checkouts

    def worker(self, emp: str) -> Worker:
        if emp not in self.workers:
            self.workers[emp] = Worker(emp, self.staff_dept.get(emp, "?"), self.start)
        return self.workers[emp]

    # ------------------------------------------------------------ scan after every event
    def scan(self) -> None:
        for j in self.jobs():
            jid = j["id"]
            self.job_meta.setdefault(
                jid,
                {
                    "created": self.clock.now(),
                    "title": j["title"],
                    "dept": j["department"],
                    "urgency": j["urgency"],
                    "kind": j.get("kind"),
                    "room": j.get("room"),
                },
            )
            if j["status"] == "offered":
                key = (jid, self.retries[jid], len(j["attempts"]))
                if key in self.scheduled_offers:
                    continue
                self.scheduled_offers.add(key)
                emp = j["offer_to"]
                working = self.on_shift(self.clock.t)
                self.offer_log.append(
                    {
                        "job": jid,
                        "emp": emp,
                        "at": self.clock.now(),
                        "dept": j["department"],
                        "band": self.bands.get(emp, "low"),
                        "guard": next((r["parts"]["retention_guard"] for r in j["ranking"] if r["employee_id"] == emp), 0),
                    }
                )
                if emp not in working:
                    self.violations.append(f"{jid} offered to {emp} who is off shift at {self.local(self.clock.t):%H:%M}")
                elif working[emp] != j["department"]:
                    self.violations.append(f"{jid} offered to {emp} of {working[emp]} for {j['department']}")
                w = self.worker(emp)
                p_decline = 0.35 if len(w.open_jobs) >= 2 else 0.10
                x = self.rng.random()
                if x < p_decline:
                    self.at(self.clock.t + timedelta(seconds=self.u(3, 10)), self.respond, jid, emp, key, False)
                elif x < p_decline + 0.10:
                    self.events["timeouts"] += 1
                    self.at(self.clock.t + timedelta(seconds=32), lambda: None)  # a later read sweeps the offer on
                else:
                    self.at(self.clock.t + timedelta(seconds=self.u(4, 20)), self.respond, jid, emp, key, True)
            elif j["status"] == "unassigned" and self.retries[jid] < 3 and (jid, "retry", self.retries[jid]) not in self.scheduled_offers:
                self.scheduled_offers.add((jid, "retry", self.retries[jid]))
                self.at(self.clock.t + timedelta(minutes=10), self.retry, jid)

    def retry(self, jid: str) -> None:
        self.retries[jid] += 1
        self.events["supervisor_retries"] += 1
        self.pc.post(f"/dispatch/jobs/{jid}/retry", headers=self.owner)

    def respond(self, jid: str, emp: str, key: tuple, accept: bool) -> None:
        j = self.pc.get("/dispatch/jobs?status=offered", headers=self.owner).json()
        j = next((x for x in j if x["id"] == jid), None)
        if not j or j["offer_to"] != emp or len(j["attempts"]) != key[2]:
            return
        if not accept:
            self.events["declines"] += 1
            self.pc.post(f"/dispatch/jobs/{jid}/decline", json={"employee_id": emp}, headers=self.owner)
            return
        r = self.pc.post(f"/dispatch/jobs/{jid}/accept", json={"employee_id": emp}, headers=self.owner)
        if r.status_code != 200:
            return
        self.events["accepts"] += 1
        m = self.job_meta[jid]
        m["accepted"], m["worker"] = self.clock.now(), emp
        w = self.worker(emp)
        w.open_jobs.add(jid)
        begin = max(self.clock.t + timedelta(minutes=self.u(2, 6)), w.free_at)
        kind = self.duration_kind(m)
        w.free_at = begin + timedelta(minutes=self.u(*DURATION[kind]))
        self.at(begin, self.start_job, jid, emp, w.free_at)

    def duration_kind(self, m: dict) -> str:
        if m["kind"] == "cleaning":
            return "reclean" if m["title"].startswith("Re-clean") else "cleaning"
        if m["dept"] == "maintenance":
            return "maintenance"
        if m["dept"] == "front_office":
            return "front"
        return "guest_fnb" if m["dept"] in ("fnb_service", "kitchen") else "guest_hk"

    def start_job(self, jid: str, emp: str, done_at: datetime) -> None:
        self.pc.post(
            f"/dispatch/jobs/{jid}/photos",
            data={"kind": "before", "employee_id": emp},
            files={"file": ("b.jpg", self.photo, "image/jpeg")},
            headers=self.owner,
        ).raise_for_status()
        self.pc.post(f"/dispatch/jobs/{jid}/start", json={"employee_id": emp}, headers=self.owner).raise_for_status()
        self.at(done_at, self.finish_job, jid, emp)

    def finish_job(self, jid: str, emp: str) -> None:
        self.pc.post(
            f"/dispatch/jobs/{jid}/photos",
            data={"kind": "after", "employee_id": emp},
            files={"file": ("a.jpg", self.photo, "image/jpeg")},
            headers=self.owner,
        ).raise_for_status()
        self.pc.post(f"/dispatch/jobs/{jid}/complete", json={"employee_id": emp}, headers=self.owner).raise_for_status()
        m = self.job_meta[jid]
        m["done"] = self.clock.now()
        w = self.worker(emp)
        w.done += 1
        w.open_jobs.discard(jid)
        end = self.shift_end(emp, m["accepted"])
        if end and self.clock.t > end:
            self.events["finished_after_shift_end"] += 1
        if m["kind"] == "cleaning":
            self.at(self.clock.t + timedelta(minutes=self.u(5, 20)), self.inspect, m["room"], m["title"].startswith("Re-clean"))

    # ------------------------------------------------------------ rooms
    def rooms(self) -> dict[str, dict]:
        return {r["number"]: r for r in self.pc.get("/rooms", headers=self.owner).json()["rooms"]}

    def inspect(self, number: str, was_reclean: bool) -> None:
        r = self.rooms()[number]
        if r["status"] != "inspection":
            return
        passed = was_reclean or self.rng.random() < 0.85
        self.pc.post(
            f"/rooms/{r['id']}/inspect", json={"passed": passed, "note": "" if passed else "dust under bed"}, headers=self.hk_head
        ).raise_for_status()
        log = self.room_log[number]
        log.setdefault("inspections", []).append("pass" if passed else "fail")
        if passed:
            log["ready"] = self.clock.now()

    def front_checkout(self, number: str) -> None:
        r = self.rooms()[number]
        if r["status"] != "occupied":
            return
        self.pc.post(f"/rooms/{r['id']}/checkout", headers=self.fo_head).raise_for_status()
        self.room_log[number]["checkout"] = self.clock.now()
        self.events["front_desk_checkouts"] += 1

    def arrival(self, number: str, first: datetime) -> None:
        r = self.rooms()[number]
        if r["status"] == "ready":
            self.pc.post(f"/rooms/{r['id']}/check-in", headers=self.fo_head).raise_for_status()
            self.room_log[number]["checked_in"] = self.clock.now()
            self.arrivals_waited.append((self.clock.t - first).total_seconds() / 60)
            self.events["check_ins"] += 1
        elif self.clock.t < self.end:
            self.at(self.clock.t + timedelta(minutes=10), self.arrival, number, first)
        else:
            self.events["arrivals_not_roomed"] += 1

    # ------------------------------------------------------------ guests
    def chat_action(self, token: str, message: str) -> dict | None:
        out = self.pc.post(f"/public/guest/{token}/chat", json={"message": message}).json()
        self.concierge[f"source_{out.get('source')}"] += 1
        act = out.get("proposed_action")
        if not act:
            return None
        res = self.pc.post(f"/public/guest/{token}/actions", json={"action": act["action"], "params": act["params"]})
        self.concierge[f"confirmed_{act['action']}_{res.status_code}"] += 1
        return act

    def guest_request(self, number: str, key: str) -> None:
        r = self.rooms()[number]
        if r["status"] != "occupied":
            return
        if key in CHAT_LINES and self.rng.random() < 0.5:
            self.chat_action(r["guest_token"], CHAT_LINES[key])
        else:
            res = self.pc.post(f"/public/guest/{r['guest_token']}/requests", json={"key": key})
            self.events[f"guest_request_{res.status_code}"] += 1
        self.events["guest_requests"] += 1

    def express(self, number: str, hhmm: str, luggage: bool) -> None:
        r = self.rooms()[number]
        if r["status"] != "occupied":
            return
        res = self.pc.post(f"/public/guest/{r['guest_token']}/checkout", json={"time": hhmm, "luggage_help": luggage})
        if res.status_code == 201:
            self.events["express_checkouts"] += 1
            due = datetime.combine(self.day, datetime.strptime(hhmm, "%H:%M").time(), UTC) - IST
            self.room_log[number]["express_due"] = due
            self.at(due + timedelta(seconds=5), self.mark_express, number)

    def mark_express(self, number: str) -> None:
        self.jobs()  # a read releases the due express checkout (room checkout + cleaning job)
        r = self.rooms()[number]
        if r["status"] != "occupied":
            self.room_log[number].setdefault("checkout", self.clock.now())

    def late_request(self, number: str, until: str) -> None:
        r = self.rooms()[number]
        act = self.chat_action(r["guest_token"], LATE_LINES[until])
        if act and act["action"] == "late_checkout":
            self.events["late_requests"] += 1
            self.at(self.clock.t + timedelta(minutes=self.u(5, 30)), self.decide_late, number, until)

    def decide_late(self, number: str, _asked: str) -> None:
        pending = self.pc.get("/guest-services/late-checkouts?status=pending", headers=self.fo_head).json()
        item = next((x for x in pending if x["room"] == number), None)
        if not item:
            return
        approve = self.rng.random() < 0.8
        self.pc.post(
            f"/guest-services/late-checkouts/{item['id']}/decide",
            json={"approve": approve, "note": "Enjoy the extra time" if approve else "Fully booked today"},
            headers=self.fo_head,
        ).raise_for_status()
        self.events["late_approved" if approve else "late_declined"] += 1
        t = item["until"] if approve else "11:00"
        when = datetime.combine(self.day, datetime.strptime(t, "%H:%M").time(), UTC) - IST
        self.at(max(when, self.clock.t + timedelta(minutes=1)), self.front_checkout, number)

    def feedback(self, number: str) -> None:
        r = self.rooms()[number]
        rating = int(self.rng.choice([5, 4, 3, 2, 1], p=[0.5, 0.3, 0.12, 0.05, 0.03]))
        if self.rng.random() < 0.4:
            self.chat_action(r["guest_token"], f"{rating} star feedback, thank you")
        else:
            res = self.pc.post(f"/public/guest/{r['guest_token']}/feedback", json={"rating": rating, "lang": "en"})
            self.events[f"feedback_{res.status_code}"] += 1

    # ------------------------------------------------------------ staff jobs + supplies
    def fault(self, number: str | None, title: str, urgency: str) -> None:
        body = {
            "title": f"{title}" + (f" · room {number}" if number else " · floor 2"),
            "department": "maintenance",
            "room": number,
            "urgency": urgency,
            "source": "staff",
        }
        self.pc.post("/dispatch/jobs", json=body, headers=self.owner).raise_for_status()
        self.events["maintenance_faults"] += 1

    def staff_job(self, title: str, dept: str, urgency: str) -> None:
        self.pc.post(
            "/dispatch/jobs", json={"title": title, "department": dept, "urgency": urgency, "source": "staff"}, headers=self.owner
        ).raise_for_status()
        self.events[f"{dept}_jobs"] += 1

    def supply_request(self, lines: dict[str, float], note: str) -> None:
        r = self.pc.post(
            "/inventory/requests",
            json={"department": "housekeeping", "lines": lines, "location_id": self.loc["Housekeeping pantry (floor 2)"], "note": note},
            headers=self.hs05,
        )
        r.raise_for_status()
        rid = r.json().get("id") or r.json().get("request_id")
        self.events["supply_requests"] += 1
        self.at(self.clock.t + timedelta(minutes=self.u(15, 45)), self.fulfil, rid, lines)

    def fulfil(self, rid: str, lines: dict[str, float]) -> None:
        r = self.pc.post(
            f"/inventory/requests/{rid}/fulfil", json={"issued": lines, "from_location": self.loc["Main store"]}, headers=self.store
        )
        self.events[f"supply_fulfilled_{r.status_code}"] += 1

    def daily_issue(self) -> dict:
        """Storekeeper issues the day's per-room consumables for the occupied room-nights (ASSUMED per_occ_room)."""
        items = self.pc.get("/inventory/items", headers=self.store).json()
        stock = self.pc.get("/inventory/stock", headers=self.store).json()["stock"]
        level = defaultdict(float)
        for s in stock:
            level[(s["item_id"], s["location_id"])] += s["qty"]
        occupied = 24
        used, value = {}, 0.0
        for it in items:
            if not it["per_occ_room"]:
                continue
            qty = round(it["per_occ_room"] * occupied)
            home = max(((loc, q) for (iid, loc), q in level.items() if iid == it["id"]), key=lambda x: x[1], default=None)
            if qty <= 0 or home is None:
                continue
            qty = min(qty, int(home[1]))
            r = self.pc.post(
                "/inventory/issue",
                json={
                    "item_id": it["id"],
                    "location_id": home[0],
                    "qty": qty,
                    "department": it["department"],
                    "reason": "daily room consumables",
                },
                headers=self.store,
            )
            if r.status_code == 201:
                used[it["sku"]] = qty
                value += qty * it["unit_cost"]
        return {"items_issued": len(used), "units": sum(used.values()), "value_inr": round(value), "by_sku": used}

    # ------------------------------------------------------------ plan + run
    def plan(self) -> None:
        rooms = self.rooms()
        numbers = sorted(rooms)
        for n in numbers:
            self.room_log[n] = {}
        # night arrivals: every room is occupied at 06:00 (Christmas peak changeover day, stress test)
        for n, r in rooms.items():
            if r["status"] == "ready":
                self.pc.post(f"/rooms/{r['id']}/check-in", headers=self.fo_head).raise_for_status()
        order = list(self.rng.permutation(numbers))
        late, express, desk = order[:5], order[5:13], order[13:]
        d = self.day

        def t(h: float) -> datetime:
            return datetime(d.year, d.month, d.day, tzinfo=UTC) - IST + timedelta(hours=h)

        for n in late:
            self.at(t(self.u(8, 10)), self.late_request, n, str(self.rng.choice(["12:00", "13:00", "14:00"])))
        for n in express:
            hh = int(self.rng.integers(8, 11))
            mm = int(self.rng.choice([0, 15, 30, 45]))
            self.at(t(self.u(7, hh - 0.25)), self.express, n, f"{hh:02d}:{mm:02d}", bool(self.rng.random() < 0.5))
        for n in desk:
            self.at(t(self.u(7.5, 11)), self.front_checkout, n)
        for n in numbers:
            if self.rng.random() < 0.6:
                self.at(t(self.u(7, 10.5)), self.feedback, n)
        # 20 arrivals into the changed-over rooms
        for n in self.rng.choice(numbers, size=20, replace=False):
            first = t(self.u(12, 21))
            self.at(first, self.arrival, str(n), first)
        # guest requests from occupied rooms, morning and evening peaks (~2.6 per room-day)
        keys, w = list(MENU_WEIGHTS), np.array(list(MENU_WEIGHTS.values()))
        for h in range(6, 23):
            lam = {7: 6, 8: 7, 9: 6, 18: 5, 19: 6, 20: 6, 21: 4}.get(h, 2)
            for _ in range(int(self.rng.poisson(lam))):
                self.at(t(h + self.u(0, 1)), self.guest_request, str(self.rng.choice(numbers)), str(self.rng.choice(keys, p=w / w.sum())))
        for title, urg in FAULTS:
            room = None if title.startswith("Corridor") else str(self.rng.choice(numbers))
            self.at(t(self.u(7, 21)), self.fault, room, title, urg)
        for title in KITCHEN_JOBS:
            self.at(t(self.u(11, 20)), self.staff_job, title.format(room=self.rng.choice(numbers)), "kitchen", "medium")
        for title in SECURITY_JOBS:
            self.at(t(self.u(22.1, 22.9)), self.staff_job, title.format(room=self.rng.choice(numbers)), "security", "high")
        items = {i["sku"]: i["id"] for i in self.pc.get("/inventory/items", headers=self.store).json()}
        self.loc = {x["name"]: x["id"] for x in self.pc.get("/inventory/locations", headers=self.store).json()}
        self.at(t(9), self.supply_request, {items["AMN-SH"]: 20, items["AMN-SP"]: 20, items["AMN-TP"]: 12}, "Morning pantry top-up")
        self.at(t(15), self.supply_request, {items["LIN-BT"]: 10, items["LIN-PC"]: 12}, "Linen for evening turndown")
        for h in range(6, 24):  # shift changes and periodic reads
            for m in (0, 30):
                self.at(t(h + m / 60), lambda: None)

    def run(self) -> dict:
        self.stock_before = self.pc.get("/inventory/analytics", headers=self.store).json()
        self.plan()
        self.inventory = None
        stop = self.end + timedelta(minutes=60)
        while self.q:
            when, _, fn, args = heapq.heappop(self.q)
            if when > stop:
                break
            self.clock.set(when)
            if self.inventory is None and self.local(self.clock.t).hour >= 10:
                self.inventory = self.daily_issue()
            self.sync_context()
            fn(*args)
            self.scan()
        return self.report()

    # ------------------------------------------------------------ report
    def report(self) -> dict:
        jobs = {j["id"]: j for j in self.jobs()}
        final = Counter(j["status"] for j in jobs.values())
        resp, comp, ontime = [], [], []
        by_dept: dict[str, dict] = defaultdict(lambda: {"jobs": 0, "done": 0, "on_time": 0})
        from hoi_platform.services.performance import TARGET_MINUTES

        for jid, j in jobs.items():
            m = self.job_meta.get(jid, {})
            dpt = by_dept[j["department"]]
            dpt["jobs"] += 1
            if j.get("accepted_at"):
                resp.append((datetime.fromisoformat(j["accepted_at"]) - datetime.fromisoformat(j["created_at"])).total_seconds() / 60)
            if j["status"] == "done":
                dpt["done"] += 1
                acc, done = datetime.fromisoformat(j["accepted_at"]), datetime.fromisoformat(j["done_at"])
                mins = (done - acc).total_seconds() / 60
                comp.append((done - datetime.fromisoformat(j["created_at"])).total_seconds() / 60)
                ok = mins <= TARGET_MINUTES.get(j["urgency"], 60)
                ontime.append(ok)
                dpt["on_time"] += ok
            _ = m
        loads: dict[str, list[int]] = defaultdict(list)  # per department and shift of the simulated day
        for a in self.roster["assignments"]:
            if a["date"] == str(self.day):
                w = self.workers.get(a["employee_id"])
                loads[f"{self.staff_dept[a['employee_id']]}/{a['shift']}"].append(w.done if w else 0)
        flagged = [e for e, b in self.bands.items() if b == "high"]
        guard = {
            "flagged": flagged,
            "offers_to_flagged": sum(o["emp"] in flagged for o in self.offer_log),
            "guard_applied_on_offers": Counter(o["guard"] for o in self.offer_log if o["emp"] in flagged),
            "jobs_done_flagged_vs_dept_peers": {},
        }
        shift_of = {a["employee_id"]: a["shift"] for a in self.roster["assignments"] if a["date"] == str(self.day)}
        for e in flagged:
            dept, sh = self.staff_dept[e], shift_of.get(e)
            peers = [
                self.workers[x].done if x in self.workers else 0
                for x, s2 in shift_of.items()
                if s2 == sh and self.staff_dept[x] == dept and x not in flagged
            ]
            guard["jobs_done_flagged_vs_dept_peers"][e] = {
                "shift": sh,
                "done": self.workers[e].done if e in self.workers else 0,
                "same_shift_peer_mean": round(statistics.mean(peers), 1) if peers else None,
            }
        perf = self.pc.get("/dispatch/performance?days=1", headers=self.owner).json()
        k_ok = (
            all((w.get("score") is not None) == (w.get("completed_jobs", 0) >= perf.get("min_jobs", 5)) for w in perf["workers"])
            if perf.get("workers")
            else True
        )
        rooms = self.rooms()
        turn = [
            (log["ready"] - log["checkout"]).total_seconds() / 60
            for log in self.room_log.values()
            if log.get("ready") and log.get("checkout")
        ]
        insp = Counter(x for log in self.room_log.values() for x in log.get("inspections", []))
        gs = self.pc.get("/guest-services/summary", headers=self.fo_head).json()
        fb = self.pc.get("/guest-services/feedback?days=1", headers=self.fo_head).json()
        after = self.pc.get("/inventory/analytics", headers=self.store).json()
        items = self.pc.get("/inventory/items", headers=self.store).json()
        on_hand = defaultdict(float)
        for x in self.pc.get("/inventory/stock", headers=self.store).json()["stock"]:
            on_hand[x["item_id"]] += x["qty"]
        below = sorted(i["sku"] for i in items if on_hand[i["id"]] < i["reorder_point"])
        return {
            "day": str(self.day),
            "jobs_total": len(jobs),
            "final_status": dict(final),
            "every_job_assigned_or_escalated": all(j["status"] in ("done", "accepted", "in_progress", "unassigned") for j in jobs.values()),
            "escalated_unassigned": final.get("unassigned", 0),
            "escalated_jobs": [
                {
                    "title": j["title"],
                    "department": j["department"],
                    "created_local": (datetime.fromisoformat(j["created_at"]).astimezone(UTC) + IST).strftime("%H:%M")
                    if datetime.fromisoformat(j["created_at"]).tzinfo
                    else j["created_at"][11:16],
                    "note": j.get("note"),
                }
                for j in jobs.values()
                if j["status"] == "unassigned"
            ],
            "offers": len(self.offer_log),
            "events": dict(self.events),
            "off_shift_or_wrong_department_offers": len(self.violations),
            "violations": self.violations[:10],
            "response_min_median": med(resp),
            "response_min_p90": p90(resp),
            "completion_min_median": med(comp),
            "completion_min_p90": p90(comp),
            "on_time_pct": pct(sum(ontime), len(ontime)),
            "by_department": {k: {**v, "on_time_pct": pct(v["on_time"], v["done"])} for k, v in by_dept.items()},
            "load_per_worker": {
                d: {"jobs_done": sorted(v, reverse=True), "max_min_gap": max(v) - min(v) if v else 0} for d, v in loads.items()
            },
            "retention_guard": guard,
            "performance": {
                "workers": len(perf.get("workers", [])),
                "scored": sum(w.get("score") is not None for w in perf.get("workers", [])),
                "insufficient_data": sum(w.get("status") == "insufficient_data" for w in perf.get("workers", [])),
                "k_min_rule_holds": k_ok,
                "min_jobs": perf.get("min_jobs"),
                "scores": {w["employee_id"]: (w.get("score"), w.get("completed_jobs")) for w in perf.get("workers", [])},
            },
            "rooms": {
                "final_status": dict(Counter(r["status"] for r in rooms.values())),
                "checked_out": sum(1 for x in self.room_log.values() if x.get("checkout")),
                "made_ready": sum(1 for x in self.room_log.values() if x.get("ready")),
                "inspections": dict(insp),
                "turnaround_min_median": med(turn),
                "turnaround_min_p90": p90(turn),
                "check_ins": self.events.get("check_ins", 0),
                "arrival_wait_min_median": med(self.arrivals_waited),
                "arrival_wait_min_max": round(max(self.arrivals_waited), 1) if self.arrivals_waited else None,
            },
            "concierge": dict(self.concierge),
            "guest_services": {
                "late_checkouts_pending": gs.get("late_checkouts_pending"),
                "checkouts_today": gs.get("checkouts_today", {}).get("count"),
                "feedback_count": fb.get("count"),
                "feedback_average": fb.get("average"),
            },
            "inventory": {
                "daily_issue": self.inventory,
                "ledger_errors": after.get("ledger_errors"),
                "stock_value_before_inr": round(self.stock_before.get("stock_value", 0)),
                "stock_value_after_inr": round(after.get("stock_value", 0)),
                "below_reorder_after": below,
            },
        }


# =============================================================== ops: attrition + loop, onboarding
def ops_loop(ops) -> dict:  # noqa: ANN001
    scores = ops.post("/attrition/score", json={}).json()
    loop = ops.post("/loop/run").json()
    m = ops.get("/metrics/overview").json()
    return {
        "scored": len(scores),
        "bands": dict(Counter(s["band"] for s in scores)),
        "segments": dict(Counter(s["segment"] for s in scores)),
        "flagged": loop["flagged"],
        "interventions": len(loop["interventions"]),
        "people": [
            {
                "employee_id": p["employee_id"],
                "top_drivers": p["top_drivers"],
                "baseline": {k: p["baseline"][k] for k in ("overtime_hours", "full_weekend_off", "risk", "band")},
                "protected": {k: p["protected"][k] for k in ("overtime_hours", "full_weekend_off", "risk", "band")},
                "risk_change": p["risk_change"],
            }
            for p in loop["people"]
        ],
        "totals": {
            k: {x: v[x] for x in ("coverage", "overtime_hours", "understaffed_shifts", "total_cost_inr", "hard_violations")}
            for k, v in loop["totals"].items()
        },
        "metrics": {k: m[k] for k in ("flagged_count", "tasks_total", "roi_inr")},
        "bands_by_employee": {s["employee_id"]: s["band"] for s in scores},
    }


ONBOARDING_ANSWERS = {
    "rooms": "hamare paas 24 kamre hain",
    "location": "Mussoorie",
    "departments": "housekeeping mein chhe, kitchen mein teen, front desk pe teen",
    "peak_months": "may se june aur december",
    "shifts": "subah 6 se 3, shaam 2 se 11",
    "overtime_rate_multiplier": "double",
    "min_rest_hours": "das ghante",
}


def onboarding_demo(ops) -> dict:  # noqa: ANN001
    """Typed (no audio, no keys) onboarding that creates the hotel as a confirmed property."""
    s = ops.post(
        "/onboarding/start", json={"hotel_type": "resort", "language": "en", "hotel_name": "Himsagar Ridge Resort (fictional)"}
    ).json()
    asked = []
    for _ in range(12):
        q = s.get("question")
        if not q:
            break
        asked.append(q["field"])
        s = ops.post("/onboarding/answer", json={"session_id": s["session_id"], "text": ONBOARDING_ANSWERS.get(q["field"], "skip")}).json()
    out = ops.post("/onboarding/confirm", json={"session": s["session_id"], "acknowledged_legal_fields": s.get("legal_fields", [])})
    prop = out.json()
    got = ops.get(f"/properties/{prop.get('property_id')}").json() if out.status_code == 200 else {}
    f = s.get("fields", {})
    return {
        "asked": asked,
        "confirm_status": out.status_code,
        "created": prop.get("created"),
        "property_id": prop.get("property_id"),
        "rooms": (f.get("rooms") or {}).get("value"),
        "location": (f.get("location") or {}).get("value"),
        "property_saved": bool(got),
    }
