"""Rooms: housekeeping status board and guest service requests (QR per room).

Status flow (housekeeping):
    occupied --checkout--> dirty (auto-creates a cleaning job) --job done--> inspection --pass--> ready
                                                                              \\--fail--> dirty (new job)
    any --out_of_order (reason)--> out_of_order (optional maintenance job) --back--> dirty
    ready --check_in--> occupied

Guest requests come from a public page reached by the room's QR code. The guest enters no personal data;
the room's random token identifies the room only, and requests are rate-limited per room.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from pymongo.errors import DuplicateKeyError

from .. import config, mongo
from . import dispatch, tenants
from .errors import Conflict, Invalid, NotFound

STATUSES = ("ready", "occupied", "dirty", "cleaning", "inspection", "out_of_order")
GUEST_MENU = {
    "towels": {"label": "Fresh towels", "label_hi": "ताज़े तौलिये", "dept": "housekeeping", "urgency": "low"},
    "cleaning": {"label": "Clean my room", "label_hi": "कमरे की सफ़ाई", "dept": "housekeeping", "urgency": "medium"},
    "water": {"label": "Drinking water", "label_hi": "पीने का पानी", "dept": "housekeeping", "urgency": "medium"},
    "amenities": {"label": "Toiletries / amenities", "label_hi": "टॉयलेटरीज़", "dept": "housekeeping", "urgency": "low"},
    "tea": {"label": "Tea / coffee", "label_hi": "चाय / कॉफ़ी", "dept": "fnb_service", "urgency": "medium"},
    "food": {"label": "Food order (room service)", "label_hi": "खाना ऑर्डर (रूम सर्विस)", "dept": "fnb_service", "urgency": "medium"},
    "ac": {"label": "AC / heater not working", "label_hi": "AC / हीटर ख़राब", "dept": "maintenance", "urgency": "high"},
    "hot_water": {"label": "No hot water", "label_hi": "गरम पानी नहीं", "dept": "maintenance", "urgency": "high"},
    "electrical": {"label": "Light / socket / TV problem", "label_hi": "लाइट / सॉकेट / टीवी", "dept": "maintenance", "urgency": "medium"},
    "other": {"label": "Something else (front desk will call)", "label_hi": "कुछ और", "dept": "front_office", "urgency": "medium"},
}
GUEST_LIMIT, GUEST_WINDOW_MIN = 5, 15


ROOM_FIELDS = ("id", "tenant_id", "property_id", "number", "floor", "room_type", "status", "guest_token", "current_job_id", "note")
# `stay` counts checkouts (one stay = until the next checkout); guest checkout/feedback records are keyed by it.
# `stay_since` = time of the last checkout: the guest page shows only requests from the current stay.


def _get(tid: str, rid: str) -> dict:
    r = mongo.find_one("rooms", {"id": rid, "tenant_id": tid})
    if not r:
        raise NotFound("Room not found")
    return r


def list_rooms(tid: str) -> list[dict]:
    return mongo.find("rooms", {"tenant_id": tid}, [("floor", 1), ("number", 1)])


def _room_doc(tid: str, number: str, floor: int | None, room_type: str, property_id: str | None) -> dict:
    doc = dict.fromkeys(ROOM_FIELDS)
    doc.update(
        id=mongo.new_id("room"),
        tenant_id=tid,
        property_id=property_id,
        number=number,
        floor=floor,
        room_type=room_type,
        status="ready",
        guest_token=secrets.token_urlsafe(16),
        updated_at=mongo.now(),
        stay=0,
        stay_since=None,
    )
    return doc


def add_room(tid: str, number: str, floor: int | None = None, room_type: str = "standard", property_id: str | None = None) -> dict:
    number = number.strip()
    if not number:
        raise Invalid("Room number is required.")
    floor = floor if floor is not None else (int(number[0]) if number[:1].isdigit() and len(number) >= 3 else None)
    doc = _room_doc(tid, number, floor, room_type, property_id)
    try:
        mongo.col("rooms").insert_one(doc)  # unique (tenant_id, number)
    except DuplicateKeyError:
        raise Invalid(f"Room {number} already exists.") from None
    return mongo.clean(doc)


def bulk_add(tid: str, floors: int, per_floor: int, property_id: str | None = None) -> int:
    have = {r["number"] for r in mongo.col("rooms").find({"tenant_id": tid}, {"number": 1})}
    docs = [
        _room_doc(tid, f"{f}{i:02d}", f, "standard", property_id)
        for f in range(1, floors + 1)
        for i in range(1, per_floor + 1)
        if f"{f}{i:02d}" not in have
    ]
    if not docs:
        return 0
    try:
        return len(mongo.col("rooms").insert_many(docs, ordered=False).inserted_ids)
    except Exception as e:  # BulkWriteError: rooms added concurrently are skipped by the unique index
        return int(getattr(e, "details", {}).get("nInserted", 0))


def _set(tid: str, rid: str, status: str, actor: str, *, job_id: str | None = None, note: str | None = None) -> dict:
    mongo.col("rooms").update_one(
        {"id": rid, "tenant_id": tid}, {"$set": {"status": status, "current_job_id": job_id, "note": note, "updated_at": mongo.now()}}
    )
    tenants.audit(tid, actor, f"room.{status}", _get(tid, rid)["number"])
    return _get(tid, rid)


def checkout(tid: str, rid: str, actor: str) -> dict:
    r = _get(tid, rid)
    if r["status"] not in ("occupied", "ready"):
        raise Conflict(f"Room {r['number']} is {r['status']}; only occupied rooms can be checked out.")
    # a new stay starts: the next guest sees none of this guest's requests, checkout or feedback
    mongo.col("rooms").update_one({"id": rid, "tenant_id": tid}, {"$inc": {"stay": 1}, "$set": {"stay_since": mongo.now()}})
    return _new_cleaning(tid, r, actor, "Checkout clean")


def _new_cleaning(tid: str, r: dict, actor: str, title: str) -> dict:
    job = dispatch.create_job(
        tid, f"{title} · room {r['number']}", "housekeeping", r["number"], "medium", "room_board", actor, room_id=r["id"], kind="cleaning"
    )
    return _set(tid, r["id"], "dirty", actor, job_id=job["id"])


def check_in(tid: str, rid: str, actor: str) -> dict:
    r = _get(tid, rid)
    if r["status"] != "ready":
        raise Conflict(f"Room {r['number']} is {r['status']}; only ready rooms can be checked in.")
    return _set(tid, rid, "occupied", actor)


def inspect(tid: str, rid: str, passed: bool, actor: str, note: str = "") -> dict:
    r = _get(tid, rid)
    if r["status"] != "inspection":
        raise Conflict(f"Room {r['number']} is not waiting for inspection.")
    _stamp_inspection(tid, r.get("current_job_id"), passed, actor)
    if passed:
        return _set(tid, rid, "ready", actor)
    return _new_cleaning(tid, r, actor, f"Re-clean after inspection{': ' + note if note else ''}")


def _stamp_inspection(tid: str, job_id: str | None, passed: bool, actor: str) -> None:
    """Record the outcome on the cleaning job just inspected (feeds the quality part of the performance score)."""
    if not job_id:
        return
    res = mongo.col("jobs").update_one(
        {"id": job_id, "tenant_id": tid, "kind": "cleaning", "status": "done"},
        {"$set": {"inspection": "pass" if passed else "fail", "inspected_at": mongo.now()}, "$inc": {"_v": 1}},
    )
    if res.matched_count:
        tenants.audit(tid, actor, "job.inspected", f"{job_id} {'pass' if passed else 'fail'}")


def out_of_order(tid: str, rid: str, reason: str, actor: str, create_job: bool = True) -> dict:
    if not reason.strip():
        raise Invalid("Give a reason for out of order.")
    r = _get(tid, rid)
    job_id = None
    if create_job:
        job_id = dispatch.create_job(
            tid,
            f"{reason} · room {r['number']}",
            "maintenance",
            r["number"],
            "high",
            "room_board",
            actor,
            room_id=r["id"],
            kind="maintenance",
        )["id"]
    return _set(tid, rid, "out_of_order", actor, job_id=job_id, note=reason)


def back_in_service(tid: str, rid: str, actor: str) -> dict:
    r = _get(tid, rid)
    if r["status"] != "out_of_order":
        raise Conflict("Room is not out of order.")
    return _new_cleaning(tid, r, actor, "Clean after repair")


def on_job_progress(tid: str, job: dict) -> None:
    """Called by dispatch when a room-linked job changes: keeps the board in step with the work."""
    if not job.get("room_id"):
        return
    r = mongo.col("rooms").find_one({"id": job["room_id"], "tenant_id": tid})
    if not r or r["current_job_id"] != job["id"]:
        return
    if job.get("kind") == "cleaning":
        if job["status"] == "in_progress" and r["status"] == "dirty":
            _set(tid, r["id"], "cleaning", job.get("assigned_to") or "system", job_id=job["id"])
        elif job["status"] == "done":
            _set(tid, r["id"], "inspection", job.get("assigned_to") or "system", job_id=job["id"])


def summary(tid: str) -> dict:
    rows = list_rooms(tid)
    return {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES} | {"total": len(rows)}


# ------------------------------------------------------------------ guest portal (public, token-scoped)
def by_token(token: str) -> dict:
    # The only lookup not scoped by tenant: the random token is the credential; everything after uses the room's tenant_id.
    r = mongo.find_one("rooms", {"guest_token": token})
    if not r:
        raise NotFound("This QR code is not valid. Please call the front desk.")
    return r


FRIENDLY = {
    "new": "received",
    "offered": "received",
    "unassigned": "received",
    "accepted": "on the way",
    "in_progress": "on the way",
    "done": "done",
}
STAGE = {"new": "open", "offered": "open", "unassigned": "open", "accepted": "accepted", "in_progress": "in_progress", "done": "done"}


def _stay_start(r: dict):
    """Requests of the current stay: since the last checkout (at most 14 days back), else the last 24 hours."""
    now = mongo.now()
    raw = mongo.col("rooms").find_one({"id": r["id"], "tenant_id": r["tenant_id"]}, {"stay_since": 1}) or {}
    since = raw.get("stay_since")  # the raw UTC datetime (clean() renders it as a local-time string)
    if isinstance(since, datetime):
        since = since if since.tzinfo else since.replace(tzinfo=UTC)
        return max(since, now - timedelta(days=14))
    return now - timedelta(hours=24)


def stay_requests(r: dict) -> list[dict]:
    """This room's own guest requests in the current stay (never other rooms', never staff ids)."""
    raw = (
        mongo.col("jobs")
        .find(
            {"tenant_id": r["tenant_id"], "room_id": r["id"], "kind": "guest", "created_at": {"$gte": _stay_start(r)}},
            {"id": 1, "title": 1, "status": 1, "created_at": 1, "department": 1},
        )
        .sort([("created_at", -1), ("_id", -1)])
        .limit(30)
    )
    return [
        {
            "id": q["id"],
            "title": q["title"].split(" · ")[0],
            "status": FRIENDLY.get(q["status"], q["status"]),
            "stage": STAGE.get(q["status"], "open"),
            "at": mongo.iso(q["created_at"]),
        }
        for q in raw
    ]


def guest_requests(token: str) -> dict:
    r = by_token(token)
    dispatch.sweep(r["tenant_id"])  # settles expired offers and due express checkouts
    return {"room": r["number"], "requests": stay_requests(by_token(token))}


def guest_view(token: str) -> dict:
    from . import guest, profiles  # local import: both depend on rooms

    r = by_token(token)
    dispatch.sweep(r["tenant_id"])
    r = by_token(token)
    t = tenants.get_tenant(r["tenant_id"])
    return {
        "hotel": t["name"],
        "brand_color": t["brand_color"],
        "room": r["number"],
        "menu": [{"key": k, **{x: v[x] for x in ("label", "label_hi")}} for k, v in GUEST_MENU.items()],
        "requests": stay_requests(r),
        "profile": profiles.public(r["tenant_id"], r.get("property_id")),
        "stay": guest.stay_status(r),
        "local_time": guest.local_now().strftime("%H:%M"),
        "today": guest.today(),
        "synthetic": bool(t.get("is_demo")),
        "voice": {"server_tts": config.settings.tts_provider == "sarvam"},  # else the browser speaks the replies
    }


def guest_request(token: str, key: str, note: str = "") -> dict:
    r = by_token(token)
    if key not in GUEST_MENU:
        raise Invalid("Unknown request.")
    since = mongo.now() - timedelta(minutes=GUEST_WINDOW_MIN)
    recent = mongo.col("jobs").count_documents(
        {"tenant_id": r["tenant_id"], "room_id": r["id"], "kind": "guest", "created_at": {"$gte": since}}
    )
    if recent >= GUEST_LIMIT:
        raise Conflict("You have sent several requests. The team is on it; for anything urgent please call the front desk.")
    m = GUEST_MENU[key]
    note = note.strip()[:140]
    title = m["label"] + (f": {note}" if note else "")
    dispatch.create_job(
        r["tenant_id"],
        f"{title} · room {r['number']}",
        m["dept"],
        r["number"],
        m["urgency"],
        "guest",
        "guest",
        room_id=r["id"],
        kind="guest",
    )
    return guest_view(token)
