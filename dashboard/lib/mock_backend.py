"""In-process stand-in for the backend, serving mocks/*.json in the exact live shapes.

Read-only endpoints return the captured responses. Mutating endpoints (tasks,
ack/done, demo clock, reset, loop) keep a small in-memory state so every UI flow
can be rehearsed offline. Status codes and error bodies mirror the live API.
"""

from __future__ import annotations

import copy
import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .config import MOCK_DIRS

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {}
VOICE_CLIPS = {"clip_01.wav"}  # the only clip the live server has (others return 503)


class MockError(Exception):
    def __init__(self, status: int, detail: Any):
        super().__init__(str(detail))
        self.status, self.detail = status, detail


def mock_path(name: str) -> Path | None:
    for d in MOCK_DIRS:
        p = d / name
        if p.exists():
            return p
    return None


def source_of(name: str) -> str:
    p = mock_path(name)
    return f"{p.parent.parent.name}/{p.parent.name}/{p.name}" if p else "missing"


def load(name: str) -> Any:
    p = mock_path(name)
    if p is None:
        raise MockError(404, f"Mock file '{name}' not found in {[str(d) for d in MOCK_DIRS]}")
    return json.loads(p.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ state
def _ensure() -> None:
    if not _STATE:
        reset()


def reset() -> dict:
    with _LOCK:
        _STATE.clear()
        try:
            tasks = load("tasks.json")
        except MockError:
            tasks = []
        _STATE["tasks"] = {t["id"]: t for t in copy.deepcopy(tasks)}
        _STATE["seq"] = max([int(t["id"]) for t in tasks if str(t["id"]).isdigit()] or [0])
        try:
            vnow = datetime.fromisoformat(load("demo_clock.json")["virtual_now"].replace("Z", ""))
        except (MockError, KeyError):
            vnow = datetime.utcnow()
        _STATE["clock"] = {"anchor_real": time.time(), "anchor_virtual": vnow, "multiplier": 1.0}
        _STATE["loop_ran"] = False
    return {"status": "reset", "mock": True, "tasks": len(_STATE["tasks"])}


def _vnow() -> datetime:
    c = _STATE["clock"]
    return c["anchor_virtual"] + timedelta(seconds=(time.time() - c["anchor_real"]) * c["multiplier"])


def _event(t: dict, kind: str, msg: str) -> None:
    t.setdefault("events", []).append({"kind": kind, "message": msg, "at": _vnow().isoformat()})


def _apply_reminders() -> None:
    """Reminders at 50% and 90% of the deadline, escalation to the supervisor at 100% if not acked."""
    now = _vnow()
    for t in _STATE["tasks"].values():
        if t["status"] == "done":
            continue
        c, d = datetime.fromisoformat(t["created_at"]), datetime.fromisoformat(t["deadline"])
        if d <= c:
            continue
        frac = (now - c).total_seconds() / (d - c).total_seconds()
        kinds = {e["kind"] for e in t.get("events", [])}
        if frac >= 0.5 and "reminder_50" not in kinds:
            _event(t, "reminder_50", f"Reminder to {t['assignee']}: 50% of the time to deadline has passed")
        if frac >= 0.9 and "reminder_90" not in kinds:
            _event(t, "reminder_90", f"Reminder to {t['assignee']}: 90% of the time to deadline has passed")
        if frac >= 1.0 and t["status"] == "open" and "escalated" not in kinds:
            _event(t, "escalated", f"Escalated to {t.get('supervisor') or 'supervisor'}: deadline passed without acknowledgement")


# ------------------------------------------------------------------ tasks
def list_tasks(status: str | None = None, employee_id: str | None = None) -> list[dict]:
    _ensure()
    with _LOCK:
        _apply_reminders()
        return [
            copy.deepcopy(t)
            for t in _STATE["tasks"].values()
            if (not status or t["status"] == status) and (not employee_id or t.get("employee_id") == employee_id)
        ]


def create_task(body: dict) -> dict:
    _ensure()
    missing = [k for k in ("idempotency_key", "title", "assignee") if not body.get(k)]
    if missing:
        raise MockError(422, [{"type": "missing", "loc": ["body", k], "msg": "Field required"} for k in missing])
    with _LOCK:
        for t in _STATE["tasks"].values():
            if t["idempotency_key"] == body["idempotency_key"]:
                return copy.deepcopy(t)  # idempotent: same key -> same task
        _STATE["seq"] += 1
        now = _vnow()
        t = {
            "id": _STATE["seq"],
            "idempotency_key": body["idempotency_key"],
            "title": body["title"],
            "description": body.get("description") or "",
            "assignee": body["assignee"],
            "supervisor": body.get("supervisor") or "general manager",
            "employee_id": body.get("employee_id") or "",
            "status": "open",
            "created_at": now.isoformat(),
            "deadline": (now + timedelta(minutes=int(body.get("due_in_minutes") or 60 * 24 * 7))).isoformat(),
            "acked_at": None,
            "done_at": None,
            "events": [],
            "synthetic": True,
        }
        _event(t, "created", f"Task '{t['title']}' assigned to {t['assignee']}")
        _STATE["tasks"][t["id"]] = t
        return copy.deepcopy(t)


def _transition(task_id: Any, to: str) -> dict:
    _ensure()
    with _LOCK:
        t = _STATE["tasks"].get(task_id) or _STATE["tasks"].get(int(task_id) if str(task_id).isdigit() else task_id)
        if not t:
            raise MockError(404, f"task {task_id} not found")
        if t["status"] != to and not (to == "acked" and t["status"] == "done"):
            t["status"] = to
            t[f"{to}_at"] = _vnow().isoformat()
            _event(t, to, f"Task marked {to}")
        return copy.deepcopy(t)


def ack_task(task_id: Any) -> dict:
    return _transition(task_id, "acked")


def done_task(task_id: Any) -> dict:
    return _transition(task_id, "done")


# ------------------------------------------------------------------ clock
def get_clock() -> dict:
    _ensure()
    return {"multiplier": _STATE["clock"]["multiplier"], "virtual_now": _vnow().isoformat() + "Z"}


def set_clock(body: dict) -> dict:
    _ensure()
    if "multiplier" not in body:
        raise MockError(422, [{"type": "missing", "loc": ["body", "multiplier"], "msg": "Field required"}])
    with _LOCK:
        _STATE["clock"] = {"anchor_real": time.time(), "anchor_virtual": _vnow(), "multiplier": float(body["multiplier"])}
    return get_clock()


# ------------------------------------------------------------------ attrition
def score(body: dict) -> list[dict]:
    rows = load("attrition_scores.json")
    ids = body.get("employee_ids")
    return [r for r in rows if r["employee_id"] in set(ids)] if ids else rows


def rescore(body: dict) -> dict:
    emp = str(body.get("employee_id") or "")
    overrides = body.get("feature_overrides") or {}
    pw = body.get("protected_weekends_off")
    rows = {r["employee_id"]: r for r in load("attrition_scores.json")}
    if emp not in rows:
        raise MockError(404, f"employee {emp} not found")
    canned = load("rescore_sunita.json")
    if not overrides and not pw:  # baseline call: same shape, no change
        return {
            "employee_id": emp,
            "week_start": rows[emp]["week_start"],
            "overrides": {},
            "features_before": {},
            "features_after": {},
            "before": rows[emp],
            "after": rows[emp],
            "risk_change": 0.0,
            "note": canned.get("note", ""),
        }
    if emp != canned["employee_id"]:
        raise MockError(501, "MOCK mode only holds a captured what-if for Sunita (H901). Switch to LIVE to simulate anyone else.")
    out = copy.deepcopy(canned)
    if overrides or pw != 2:
        out["_mock_mismatch"] = {"requested": {"protected_weekends_off": pw, **overrides}, "served": {"protected_weekends_off": 2}}
    return out


# ------------------------------------------------------------------ roster / loop / misc
def generate_roster(body: dict) -> dict:
    if body.get("_simulate_infeasible"):
        return load("roster_infeasible.json")
    time.sleep(0.6)  # the live solve takes seconds; keep the spinner visible
    return load("roster_protected.json" if body.get("protected_ids") else "roster_baseline.json")


def get_roster(roster_id: Any) -> dict:
    for name in ("roster_baseline.json", "roster_protected.json"):
        d = load(name)
        if str(d.get("id")) == str(roster_id):
            return d
    raise MockError(404, f"roster {roster_id} not found")


def run_loop() -> dict:
    d = load("loop_run.json")
    _ensure()
    seen: dict[tuple, int] = {}
    for iv in d.get("interventions", []):
        k = (iv["employee_id"], iv["driver"])
        i = seen[k] = seen.get(k, -1) + 1  # same key format as the backend: loop:{week}:{emp}:{driver}:{n}
        create_task(
            {
                "idempotency_key": f"loop:{d['week_start']}:{iv['employee_id']}:{iv['driver']}:{i}",
                "title": f"{iv['action']} ({iv['employee_id']})",
                "assignee": iv["owner"],
                "employee_id": iv["employee_id"],
                "description": f"Driver: {iv['driver']}",
                "due_in_minutes": 60 * 24 * 21,
            }
        )
    return d


def interventions(params: dict) -> list[dict]:
    """GET /interventions from loop_run.json joined with the in-memory tasks by idempotency key (same key format as the
    backend). An intervention appears only once its task exists, as in the live API; status derives from the task."""
    status = params.get("status") or "all"
    if status not in ("open", "done", "all"):
        raise MockError(422, [{"type": "literal_error", "loc": ["query", "status"], "msg": "Input should be 'open', 'done' or 'all'"}])
    d = load("loop_run.json")
    _ensure()
    with _LOCK:
        by_key = {t.get("idempotency_key"): t for t in _STATE["tasks"].values()}
        now = _vnow()
    out, seen = [], {}
    for iv in d.get("interventions", []):
        k = (iv["employee_id"], iv["driver"])
        i = seen[k] = seen.get(k, -1) + 1
        t = by_key.get(f"loop:{d['week_start']}:{iv['employee_id']}:{iv['driver']}:{i}")
        if t is None:
            continue
        st = t["status"]
        if st != "done" and datetime.fromisoformat(str(t["deadline"]).replace("Z", "")).replace(tzinfo=None) < now:
            st = "overdue"
        if (status == "done" and st != "done") or (status == "open" and st == "done"):
            continue
        if params.get("employee_id") and iv["employee_id"] != params["employee_id"]:
            continue
        if params.get("week_start") and d["week_start"] != params["week_start"]:
            continue
        out.append(
            {
                "id": len(out) + 1,
                **iv,
                "week_start": d["week_start"],
                "task_id": t["id"],
                "task_status": st,
                "task_deadline": t.get("deadline"),
                "task_done_at": t.get("done_at"),
                "created_at": t.get("created_at"),
                "synthetic": True,
            }
        )
    return out


def voice_ingest(body: dict) -> dict:
    f = str(body.get("file") or "")
    if not f:
        raise MockError(422, [{"type": "missing", "loc": ["body", "file"], "msg": "Field required"}])
    if "/" in f or "\\" in f or ".." in f:
        raise MockError(422, "file must be a bare clip name inside the clips folder")
    if f not in VOICE_CLIPS:
        raise MockError(503, f"voice.extract could not run: audio file not found: /app/ml/voice/clips/{f}")
    out = copy.deepcopy(load("voice_ingest.json"))
    if body.get("create_task"):
        ex = out["voice"]["extraction"]
        out["task"] = create_task(
            {
                "idempotency_key": f"voice:{f}",
                "title": f"{pretty_issue(ex.get('issue'))} in room {ex.get('room')}",
                "assignee": ex.get("department") or "maintenance",
                "description": out["voice"]["transcript"],
                "due_in_minutes": 120 if ex.get("urgency") == "high" else 60 * 24,
            }
        )
    return out


def pretty_issue(s: Any) -> str:
    return str(s or "Issue").replace("_", " ").capitalize()


def forecast(params: dict) -> dict:
    d = copy.deepcopy(load("forecast_week.json"))
    f, t = params.get("from"), params.get("to")
    if not f or not t:
        raise MockError(
            422, [{"type": "missing", "loc": ["query", k], "msg": "Field required"} for k in ("from", "to") if not params.get(k)]
        )
    d["days"] = [x for x in d["days"] if f <= x["date"] <= t]
    return d


def metrics(params: dict) -> dict:
    d = copy.deepcopy(load("metrics_overview.json"))
    rc = params.get("replacement_cost_inr")
    if rc:
        d["replacement_cost_inr"] = float(rc)
        d["roi_inr"] = d["flagged_still_employed"] * float(rc)
    return d


# ------------------------------------------------------------------ hotel onboarding by voice
# MOCK mode runs the backend's real onboarding engine (backend/onboarding: templates, question flow,
# rule-based extractor, confirm rules) in-process on an in-memory mongomock database, so the page
# behaves exactly like the live API with its default config: typed answers and rule-based
# extraction, no LLM, no cloud speech-to-text, nothing leaves this process. It needs the repo
# checkout (backend/ and ml/ next to dashboard/); without it the calls answer 501.
_ONB: dict[str, Any] = {}
ONB_DB = "hoi_ops_dashboard_mock"


def _onb() -> dict[str, Any]:
    if not _ONB:
        import sys

        from .config import REPO_ROOT

        if str(REPO_ROOT) not in sys.path:
            sys.path.append(str(REPO_ROOT))
        try:
            import mongomock

            from backend.db import ensure_indexes
            from backend.onboarding import service
            from backend.onboarding.config import load_config
            from backend.onboarding.demo import load_fixture
            from backend.onboarding.flow import load_questions
            from backend.onboarding.seed import ensure_demo_properties
            from backend.onboarding.store import NotFound
            from backend.onboarding.stt import AudioRejected, SttRefused, transcribe_upload
        except ImportError as e:
            raise MockError(
                501,
                f"Hotel setup in MOCK mode runs the backend onboarding engine in-process and needs the repo checkout "
                f"(backend/ and ml/). Switch to LIVE on the Admin page. ({e})",
            ) from None
        db = mongomock.MongoClient(tz_aware=True)[ONB_DB]
        cfg = load_config()
        ensure_indexes(db)
        ensure_demo_properties(db, cfg)
        _ONB.update(
            db=db,
            cfg=cfg,
            service=service,
            questions=load_questions,
            NotFound=NotFound,
            AudioRejected=AudioRejected,
            SttRefused=SttRefused,
            transcribe=transcribe_upload,
            fixture=load_fixture,
        )
    return _ONB


def _onb_call(fn, *args) -> dict:
    o = _onb()
    svc = o["service"]
    try:
        out = fn(*args)
    except o["NotFound"] as e:
        raise MockError(404, str(e)) from None
    except svc.Conflict as e:
        raise MockError(409, str(e)) from None
    except svc.Blocked as e:
        raise MockError(422, e.detail) from None
    except (KeyError, ValueError) as e:  # pydantic ValidationError is a ValueError
        raise MockError(422, svc.edit_errors(e)) from None
    return json.loads(out.model_dump_json()) if hasattr(out, "model_dump_json") else json.loads(json.dumps(out, default=str))


def onboarding_start(body: dict) -> dict:
    o = _onb()
    svc = o["service"]
    return _onb_call(lambda: svc.start(o["db"], svc.StartRequest.model_validate(body), o["cfg"], "dashboard:mock"))


def onboarding_answer(body: dict, audio: tuple[str, bytes, str] | None = None) -> dict:
    o = _onb()
    svc = o["service"]
    sid = str(body.get("session_id") or "")
    if audio is not None:
        name, data, ctype = audio
        try:
            text = o["transcribe"](data, name, ctype, bool(body.get("consent")), o["cfg"].audio, None)
        except o["AudioRejected"] as e:
            raise MockError(422, str(e)) from None
        except o["SttRefused"] as e:
            lang = _onb_call(lambda: svc.summary(o["db"], sid, o["cfg"]))["language"]
            msg = o["questions"]().message(e.key, lang)
            return _onb_call(lambda: svc.stt_failed(o["db"], sid, o["cfg"], msg))
        return _onb_call(lambda: svc.answer(o["db"], sid, text, "voice", o["cfg"], None, "dashboard:mock"))
    text = str(body.get("text") or "")
    if not text.strip():
        raise MockError(422, [{"type": "missing", "loc": ["body", "text"], "msg": "Field required"}])
    return _onb_call(lambda: svc.answer(o["db"], sid, text, "typed", o["cfg"], None, "dashboard:mock"))


def onboarding_edit(body: dict) -> dict:
    o = _onb()
    svc = o["service"]
    return _onb_call(lambda: svc.edit(o["db"], svc.FieldEdit.model_validate(body), o["cfg"], "dashboard:mock"))


def onboarding_summary(session_id: str) -> dict:
    o = _onb()
    return _onb_call(lambda: o["service"].summary(o["db"], session_id, o["cfg"]))


def onboarding_confirm(body: dict) -> dict:
    o = _onb()
    svc = o["service"]
    return _onb_call(lambda: svc.confirm(o["db"], svc.ConfirmRequest.model_validate(body), o["cfg"], "dashboard:mock"))


def onboarding_property_settings(property_id: str) -> dict:
    o = _onb()
    return _onb_call(lambda: o["service"].get_settings(o["db"], property_id))


def onboarding_demo_transcript() -> dict:
    fx = _onb()["fixture"]()
    return {
        "synthetic": fx.synthetic,
        "language": fx.language,
        "answers": fx.answers,
        "note": "SYNTHETIC: written by us, not recorded speech",
    }
