"""Auto-assign dispatch (quick-commerce style), enforced server-side.

A job is offered to the best on-shift worker with a timed window. Accept assigns it; decline or timeout
moves the offer to the next candidate; with nobody left the job becomes 'unassigned' for a supervisor.
Offer expiry is applied lazily on every read (sweep), so clients cannot extend a window.

Who is on shift comes from the tenant's shift snapshot (dispatch_context), published from the roster.

Ranking (higher is better; every part is returned so 'why this worker' is explainable):
  100 − 25·open_jobs − 8·done_this_shift − 6·floor_distance − (15 if band=high, 6 if watch)
Hard filters: on shift, same department, has not declined/timed out on this job.
"""

from __future__ import annotations

import re
import zlib
from datetime import UTC, datetime, timedelta

from .. import mongo
from . import tenants
from .errors import Conflict, Invalid, NotFound

OPEN_STATES = ("offered", "accepted", "in_progress")
URGENCY = ("high", "medium", "low")
DEPT_KEYWORDS = {
    "maintenance": [
        "ac",
        "a/c",
        "geyser",
        "leak",
        "light",
        "bulb",
        "tv",
        "wifi",
        "plumb",
        "tap",
        "fan",
        "repair",
        "heater",
        "socket",
        "door lock",
    ],
    "housekeeping": ["towel", "clean", "bed", "sheet", "linen", "amenit", "toilet paper", "dust", "turndown", "pillow", "blanket"],
    "fnb_service": ["food", "order", "tea", "coffee", "breakfast", "dinner", "water bottle", "room service", "menu"],
    "front_office": ["checkout", "check-out", "check in", "key card", "bill", "invoice", "taxi", "luggage"],
    "security": ["noise", "suspicious", "parking", "guard", "lost", "fight"],
    "kitchen": ["kitchen", "cook", "allergy", "special meal"],
}


def infer_department(text: str) -> str:
    t = f" {text.lower()} "
    for dept, words in DEPT_KEYWORDS.items():
        if any((f" {w} " in t) if len(w) <= 3 else (w in t) for w in words):
            return dept
    return "housekeeping"


def floor_of_room(room: str | None) -> int | None:
    m = re.match(r"^\s*(\d)(\d{2})\s*$", str(room or ""))
    return int(m.group(1)) if m else None


def home_floor(emp: str, floors: int) -> int:
    return zlib.crc32(emp.encode()) % max(1, floors) + 1


def _settings(tid: str) -> dict:
    return tenants.get_tenant(tid)["settings"]


def offer_seconds(tid: str) -> int:
    return int(_settings(tid).get("offer_seconds", 30))


# ------------------------------------------------------------------ shift context
def set_context(tid: str, day: str | None, shift: str | None, working: dict[str, str], bands: dict[str, str], floors: int = 4) -> dict:
    mongo.col("dispatch_context").update_one(
        {"tenant_id": tid},
        {
            "$set": {
                "day": day,
                "shift": shift,
                "working": mongo.to_pairs(working),
                "bands": mongo.to_pairs(bands),
                "floors": int(floors),
                "updated_at": mongo.now(),
            }
        },
        upsert=True,
    )
    return get_context(tid)


def get_context(tid: str) -> dict:
    r = mongo.find_one("dispatch_context", {"tenant_id": tid})
    if not r:
        staff = {s["employee_id"]: s["department"] for s in tenants.staff(tid)}
        return {
            "tenant_id": tid,
            "day": None,
            "shift": None,
            "working": staff,
            "bands": {},
            "floors": 4,
            "updated_at": None,
            "source": "imported staff (no roster snapshot yet)",
        }
    c = {"tenant_id": tid, "day": r.get("day"), "shift": r.get("shift"), "working": {}, "bands": {}, "floors": r.get("floors", 4)}
    c["updated_at"] = r.get("updated_at")
    c["working"], c["bands"] = mongo.from_pairs(r.get("working")), mongo.from_pairs(r.get("bands"))
    c["source"] = "roster snapshot"
    return c


# ------------------------------------------------------------------ jobs
# Every job write bumps `_v`; state transitions are conditional on the status (and, for offer moves, on `_v`), so two
# requests racing on the same job cannot both win (optimistic concurrency on one document, no transactions needed).
JOB_FIELDS = (
    "id",
    "tenant_id",
    "title",
    "department",
    "room",
    "urgency",
    "source",
    "status",
    "created_at",
    "offer_to",
    "offer_expires_at",
    "assigned_to",
    "accepted_at",
    "started_at",
    "done_at",
    "backend_task_id",
    "attempts",
    "ranking",
    "note",
    "room_id",
    "kind",
    "inspection",
)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def _job(raw: dict) -> dict:
    r = mongo.clean(raw)
    r["attempts"] = r.get("attempts") or []
    r["ranking"] = r.get("ranking") or []
    exp = _aware(raw.get("offer_expires_at"))
    if exp and r["status"] == "offered":
        r["seconds_left"] = max(0, int((exp - datetime.now(UTC)).total_seconds()))
    else:
        r["seconds_left"] = 0
    return r


def _raw(tid: str, jid: str) -> dict:
    r = mongo.col("jobs").find_one({"id": jid, "tenant_id": tid})
    if not r:
        raise NotFound("Job not found")
    return r


def _update(tid: str, jid: str, fields: dict, cond: dict | None = None) -> bool:
    """Set fields on one job (optionally only if `cond` still matches). Returns False when the condition no longer holds."""
    res = mongo.col("jobs").update_one({"id": jid, "tenant_id": tid, **(cond or {})}, {"$set": fields, "$inc": {"_v": 1}})
    return res.matched_count == 1


def _attempts_to_db(attempts: list[dict]) -> list[dict]:
    """Attempts travel through the API as ISO strings; store their times as datetimes again."""
    out = []
    for a in attempts:
        a = dict(a)
        for k in ("offered_at", "at"):
            if isinstance(a.get(k), str):
                a[k] = datetime.fromisoformat(a[k]).astimezone(UTC)
        out.append(a)
    return out


def get_job(tid: str, jid: str) -> dict:
    return _job(_raw(tid, jid))


def list_jobs(tid: str, statuses: list[str] | None = None, worker: str | None = None) -> list[dict]:
    sweep(tid)
    rows = [_job(r) for r in mongo.col("jobs").find({"tenant_id": tid}).sort([("created_at", -1), ("_id", -1)])]
    if statuses:
        rows = [r for r in rows if r["status"] in statuses]
    if worker:
        rows = [r for r in rows if r.get("assigned_to") == worker or (r["status"] == "offered" and r.get("offer_to") == worker)]
    return rows


def rank(tid: str, job: dict, ctx: dict) -> list[dict]:
    excluded = {a["employee_id"] for a in job.get("attempts", []) if a.get("outcome") in ("declined", "timeout")}
    proj = {"id": 1, "status": 1, "assigned_to": 1, "offer_to": 1, "done_at": 1, "room": 1}
    all_jobs = list(mongo.col("jobs").find({"tenant_id": tid}, proj))
    load: dict[str, int] = {}
    for j in all_jobs:
        if j["id"] == job["id"] or j["status"] not in OPEN_STATES:
            continue
        who = j.get("assigned_to") or (j.get("offer_to") if j["status"] == "offered" else None)
        if who:
            load[who] = load.get(who, 0) + 1
    finished: dict[str, int] = {}
    last_room: dict[str, str | None] = {}
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    for j in sorted((j for j in all_jobs if j["status"] == "done"), key=lambda j: _aware(j.get("done_at")) or epoch):
        finished[j["assigned_to"]] = finished.get(j["assigned_to"], 0) + 1
        last_room[j["assigned_to"]] = j.get("room")
    target = floor_of_room(job.get("room"))
    out = []
    for emp, dept in ctx["working"].items():
        if dept != job["department"] or emp in excluded:
            continue
        cur = floor_of_room(last_room.get(emp)) or home_floor(emp, ctx.get("floors", 4))
        band = ctx["bands"].get(emp, "low")
        parts = {
            "base": 100,
            "open_jobs": -25 * load.get(emp, 0),
            "done_this_shift": -8 * finished.get(emp, 0),
            "distance": -6 * (abs(cur - target) if target else 0),
            "retention_guard": -15 if band == "high" else -6 if band == "watch" else 0,
        }
        out.append(
            {"employee_id": emp, "score": sum(parts.values()), "parts": parts, "floor": cur, "band": band, "open_jobs": load.get(emp, 0)}
        )
    return sorted(out, key=lambda r: (-r["score"], r["employee_id"]))


def _offer_next(tid: str, job: dict, ranking: list[dict], cond: dict | None = None) -> dict:
    attempts = job.get("attempts", [])
    if not ranking:
        fields = {
            "status": "unassigned",
            "offer_to": None,
            "offer_expires_at": None,
            "ranking": [],
            "attempts": _attempts_to_db(attempts),
            "note": "No on-shift worker left in this department. Supervisor must assign manually.",
        }
    else:
        top = ranking[0]
        attempts.append({"employee_id": top["employee_id"], "offered_at": mongo.now(), "outcome": "pending"})
        exp = mongo.now() + timedelta(seconds=offer_seconds(tid))
        fields = {
            "status": "offered",
            "offer_to": top["employee_id"],
            "ranking": ranking[:6],
            "attempts": _attempts_to_db(attempts),
            "offer_expires_at": exp,
        }
    if not _update(tid, job["id"], fields, cond):
        raise Conflict("This job changed meanwhile. Refresh and try again.")
    return get_job(tid, job["id"])


def create_job(
    tid: str,
    title: str,
    department: str | None,
    room: str | None,
    urgency: str,
    source: str,
    actor: str,
    room_id: str | None = None,
    kind: str = "general",
) -> dict:
    if not title.strip():
        raise Invalid("Describe the request.")
    if urgency not in URGENCY:
        raise Invalid(f"Urgency must be one of {URGENCY}")
    dept = department or infer_department(f"{title} {room or ''}")
    jid = mongo.new_id("job")
    doc = dict.fromkeys(JOB_FIELDS)
    doc.update(
        id=jid,
        tenant_id=tid,
        title=title.strip()[:200],
        department=dept,
        room=room,
        urgency=urgency,
        source=source,
        status="new",
        created_at=mongo.now(),
        attempts=[],
        ranking=[],
        room_id=room_id,
        kind=kind,
        _v=0,
    )
    mongo.col("jobs").insert_one(doc)
    tenants.audit(tid, actor, "job.created", f"{jid} {dept}")
    job = get_job(tid, jid)
    if _settings(tid).get("assign_mode", "auto") == "auto":
        return _offer_next(tid, job, rank(tid, job, get_context(tid)))
    return job


def _close_attempt(job: dict, emp: str, outcome: str) -> list[dict]:
    att = job.get("attempts", [])
    for a in reversed(att):
        if a["employee_id"] == emp and a["outcome"] == "pending":
            a["outcome"], a["at"] = outcome, mongo.iso(mongo.now())
            break
    return att


def decline(tid: str, jid: str, emp: str, outcome: str = "declined") -> dict:
    raw = _raw(tid, jid)
    j = _job(raw)
    if j["status"] != "offered" or j["offer_to"] != emp:
        raise Conflict("This offer is no longer yours.")
    j["attempts"] = _close_attempt(j, emp, outcome)
    cond = {"status": "offered", "offer_to": emp, "_v": raw.get("_v", 0)}
    try:
        return _offer_next(tid, j, rank(tid, j, get_context(tid)), cond)
    except Conflict:
        raise Conflict("This offer is no longer yours.") from None


def sweep(tid: str) -> int:
    """Expire overdue offers and move them on; release express checkouts whose time has come. Called on every read."""
    from . import guest  # local import: guest depends on dispatch

    guest.release_due(tid)
    moved = 0
    due = mongo.col("jobs").find(
        {"tenant_id": tid, "status": "offered", "offer_expires_at": {"$lte": mongo.now()}}, {"id": 1, "offer_to": 1}
    )
    for r in list(due):
        try:
            decline(tid, r["id"], r["offer_to"], outcome="timeout")
            moved += 1
        except Conflict:  # another request moved it first
            continue
    return moved


def accept(tid: str, jid: str, emp: str) -> dict:
    sweep(tid)
    raw = _raw(tid, jid)
    j = _job(raw)
    if j["status"] != "offered" or j["offer_to"] != emp:
        raise Conflict("This offer is no longer available.")
    j["attempts"] = _close_attempt(j, emp, "accepted")
    fields = {
        "status": "accepted",
        "assigned_to": emp,
        "accepted_at": mongo.now(),
        "offer_expires_at": None,
        "attempts": _attempts_to_db(j["attempts"]),
    }
    if not _update(tid, jid, fields, {"status": "offered", "offer_to": emp, "_v": raw.get("_v", 0)}):
        raise Conflict("This offer is no longer available.")
    tenants.audit(tid, emp, "job.accepted", jid)
    return get_job(tid, jid)


def offer_to(tid: str, jid: str, emp: str, actor: str) -> dict:
    """Supervisor: offer a waiting job to a specific on-shift worker."""
    raw = _raw(tid, jid)
    j = _job(raw)
    if j["status"] not in ("unassigned", "new"):
        raise Conflict("Only waiting jobs can be offered manually.")
    j["attempts"] = [a for a in j["attempts"] if a["employee_id"] != emp]
    r = [x for x in rank(tid, j, get_context(tid)) if x["employee_id"] == emp]
    if not r:
        raise Invalid(f"{emp} is not on shift in {j['department']}.")
    tenants.audit(tid, actor, "job.manual_offer", f"{jid} → {emp}")
    return _offer_next(tid, j, r, {"_v": raw.get("_v", 0)})


def retry(tid: str, jid: str, actor: str) -> dict:
    raw = _raw(tid, jid)
    j = _job(raw)
    if j["status"] not in ("unassigned", "new"):
        raise Conflict("Only waiting jobs can be retried.")
    j["attempts"] = []
    if not _update(tid, jid, {"attempts": [], "status": "new", "assigned_to": None, "note": None}, {"_v": raw.get("_v", 0)}):
        raise Conflict("Only waiting jobs can be retried.")
    tenants.audit(tid, actor, "job.retry", jid)
    raw = _raw(tid, jid)
    return _offer_next(tid, j, rank(tid, j, get_context(tid)), {"_v": raw.get("_v", 0)})


def _has_photo(tid: str, jid: str, kind: str) -> bool:
    return mongo.col("photos").count_documents({"tenant_id": tid, "job_id": jid, "kind": kind}, limit=1) > 0


def start(tid: str, jid: str, emp: str) -> dict:
    j = get_job(tid, jid)
    if j["status"] != "accepted" or j["assigned_to"] != emp:
        raise Conflict("Only the assigned worker can start an accepted job.")
    if not _has_photo(tid, jid, "before"):
        raise Invalid("Take a before photo first.")
    if not _update(tid, jid, {"status": "in_progress", "started_at": mongo.now()}, {"status": "accepted", "assigned_to": emp}):
        raise Conflict("Only the assigned worker can start an accepted job.")
    return _room_hook(tid, get_job(tid, jid))


def complete(tid: str, jid: str, emp: str) -> dict:
    j = get_job(tid, jid)
    if j["status"] != "in_progress" or j["assigned_to"] != emp:
        raise Conflict("Only the assigned worker can finish a job in progress.")
    if not _has_photo(tid, jid, "after"):
        raise Invalid("Take an after photo first.")
    if not _update(tid, jid, {"status": "done", "done_at": mongo.now()}, {"status": "in_progress", "assigned_to": emp}):
        raise Conflict("Only the assigned worker can finish a job in progress.")
    _room_hook(tid, get_job(tid, jid))
    tenants.audit(tid, emp, "job.done", jid)
    return get_job(tid, jid)


def link_task(tid: str, jid: str, task_id: str) -> dict:
    get_job(tid, jid)
    _update(tid, jid, {"backend_task_id": str(task_id)})
    return get_job(tid, jid)


def reset_ops(tid: str) -> None:
    d = mongo.db()
    d.photo_blobs.delete_many({"tenant_id": tid})
    d.photos.delete_many({"tenant_id": tid})
    d.jobs.delete_many({"tenant_id": tid})


def _room_hook(tid: str, job: dict) -> dict:
    from . import rooms  # local import: rooms depends on dispatch

    rooms.on_job_progress(tid, job)
    return job


# ------------------------------------------------------------------ published roster (read by the worker portal)
def publish_roster(tid: str, week_start: str | None, assignments: list[dict]) -> dict:
    clean = [
        {"employee_id": str(a["employee_id"]), "date": str(a["date"]), "shift": str(a["shift"]), "hours": int(a.get("hours") or 8)}
        for a in assignments
        if a.get("employee_id") and a.get("date") and a.get("shift")
    ]
    mongo.col("roster_snapshots").update_one(
        {"tenant_id": tid}, {"$set": {"week_start": week_start, "assignments": clean, "published_at": mongo.now()}}, upsert=True
    )
    return {"week_start": week_start, "assignments": len(clean)}


def shifts_for(tid: str, employee_id: str) -> dict:
    r = mongo.find_one("roster_snapshots", {"tenant_id": tid})
    if not r:
        return {"week_start": None, "published_at": None, "shifts": []}
    rows = [a for a in r.get("assignments") or [] if a["employee_id"] == employee_id]
    return {"week_start": r["week_start"], "published_at": r["published_at"], "shifts": sorted(rows, key=lambda a: a["date"])}
