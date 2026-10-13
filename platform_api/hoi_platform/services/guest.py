"""Guest stay services behind the QR page: express checkout, late checkout, feedback, bill placeholder, and the hotel's
guest-services views (docs/HOSPITALITY_SUITE.md sections 2 and 4).

Stay: a room's `stay` counter goes up at every checkout (rooms.checkout). Express checkout, late checkout and feedback
are keyed by (tenant_id, room_id, stay): one express checkout and one feedback per stay (unique indexes).

Express checkout (documented behaviour):
- POST creates a front-office dispatch job at once ("Express checkout at 10:30 (luggage help)") so the desk can prepare.
- The room is NOT vacated then. The checkout is stored as `scheduled` with `due_at` (next occurrence of the time in hotel
  local time). The first read after `due_at` (dispatch.sweep runs on every job list / guest page / guest-services read)
  claims it atomically and runs the normal room checkout: room -> dirty, a housekeeping cleaning job is offered, stay + 1.
- If staff already checked the room out on the room board, the scheduled checkout simply closes (`already_checked_out`).
- A time after the profile's checkout time needs an approved late checkout covering it.

Times are "HH:MM" in hotel local time (config.hotel_utc_offset_minutes, default IST). No personal data is stored:
free-text reasons and comments are length-capped and phone numbers / e-mail addresses are masked.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone
from statistics import median

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from .. import config, mongo
from . import dispatch, profiles, rooms, tenants
from .errors import Conflict, Invalid, NotFound

HHMM = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\+?\d[\d\s-]{7,}\d")
FRONT = "front_office"


# ------------------------------------------------------------------ time + privacy helpers
def tz() -> timezone:
    return timezone(timedelta(minutes=config.settings.hotel_utc_offset_minutes))


def local_now() -> datetime:
    return datetime.now(UTC).astimezone(tz())


def today() -> str:
    return local_now().date().isoformat()


def parse_hhmm(v: str) -> str:
    v = str(v or "").strip()
    if len(v) == 4 and v[1] == ":":  # "9:30" -> "09:30"
        v = "0" + v
    if not HHMM.match(v):
        raise Invalid("Use a time like 10:30.")
    return v


def next_occurrence(hhmm: str, now: datetime | None = None) -> datetime:
    """The next time the clock shows hh:mm in hotel local time (today, or tomorrow if it passed more than 30 min ago), in UTC."""
    now = (now or datetime.now(UTC)).astimezone(tz())
    h, m = (int(x) for x in hhmm.split(":"))
    at = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if at < now - timedelta(minutes=30):
        at += timedelta(days=1)
    return at.astimezone(UTC)


def scrub(text: str, limit: int) -> str:
    """Length-capped free text with phone numbers and e-mail addresses masked (guests should not share them)."""
    t = " ".join(str(text or "").split())[:limit]
    return _PHONE.sub("[number removed]", _EMAIL.sub("[e-mail removed]", t))


def _stay(room: dict) -> int:
    return int(room.get("stay") or 0)


def _local(dt: datetime | None) -> str | None:
    if not dt:
        return None
    dt = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return dt.astimezone(tz()).strftime("%Y-%m-%d %H:%M")


# ------------------------------------------------------------------ status for the guest page
def _checkout_out(d: dict | None) -> dict | None:
    if not d:
        return None
    return {
        "id": d["id"],
        "time": d["time"],
        "date": d["date"],
        "luggage_help": bool(d.get("luggage_help")),
        "status": d["status"],
        "due_local": _local(d.get("due_at")),
    }


def _late_out(d: dict | None) -> dict:
    if not d:
        return {"status": "none"}
    return {
        "id": d["id"],
        "status": d["status"],
        "until": d["until"],
        "note": d.get("note") or "",
        "requested_at": mongo.iso(d.get("created_at")),
        "decided_at": mongo.iso(d.get("decided_at")),
    }


def stay_status(room: dict) -> dict:
    tid, rid, stay = room["tenant_id"], room["id"], _stay(room)
    co = mongo.col("guest_checkouts").find_one({"tenant_id": tid, "room_id": rid, "stay": stay})
    late = mongo.col("late_checkouts").find_one({"tenant_id": tid, "room_id": rid, "stay": stay}, sort=[("created_at", -1), ("_id", -1)])
    fb = mongo.col("guest_feedback").find_one({"tenant_id": tid, "room_id": rid, "stay": stay}, {"rating": 1})
    return {
        "checkout": _checkout_out(co),
        "late_checkout": _late_out(late),
        "feedback_given": bool(fb),
        "feedback_rating": fb["rating"] if fb else None,
    }


def late_status(token: str) -> dict:
    r = rooms.by_token(token)
    return stay_status(r)["late_checkout"]


# ------------------------------------------------------------------ express checkout
def _profile(room: dict) -> dict:
    return profiles.public(room["tenant_id"], room.get("property_id"))


def express_checkout(token: str, time: str, luggage_help: bool) -> dict:
    r = rooms.by_token(token)
    tid = r["tenant_id"]
    time = parse_hhmm(time)
    if r["status"] != "occupied":
        raise Conflict("This room is not checked in on our system. Please call the front desk.")
    prof = _profile(r)
    stay = _stay(r)
    if time > prof["checkout_time"]:
        late = mongo.col("late_checkouts").find_one({"tenant_id": tid, "room_id": r["id"], "stay": stay, "status": "approved"})
        if not late or late["until"] < time:
            raise Invalid(f"Checkout time is {prof['checkout_time']}. For a later time, please request a late checkout first.")
    due = next_occurrence(time)
    doc = {
        "id": mongo.new_id("xco"),
        "tenant_id": tid,
        "property_id": r.get("property_id"),
        "room_id": r["id"],
        "room": r["number"],
        "stay": stay,
        "time": time,
        "date": due.astimezone(tz()).date().isoformat(),
        "due_at": due,
        "luggage_help": bool(luggage_help),
        "status": "scheduled",
        "front_job_id": None,
        "cleaning_job_id": None,
        "outcome": None,
        "created_at": mongo.now(),
    }
    try:
        mongo.col("guest_checkouts").insert_one(doc)
    except DuplicateKeyError:
        old = mongo.col("guest_checkouts").find_one({"tenant_id": tid, "room_id": r["id"], "stay": stay})
        raise Conflict(
            f"Express checkout is already booked for {old['time'] if old else 'this stay'}. Call the front desk to change it."
        ) from None
    title = f"Express checkout at {time}" + (" (luggage help)" if luggage_help else "")
    try:
        job = dispatch.create_job(
            tid,
            f"{title} · room {r['number']}",
            FRONT,
            r["number"],
            "medium" if luggage_help else "low",
            "guest",
            "guest",
            room_id=r["id"],
            kind="guest_checkout",
        )
    except Exception:
        mongo.col("guest_checkouts").delete_one({"id": doc["id"]})  # compensating write
        raise
    mongo.col("guest_checkouts").update_one({"id": doc["id"]}, {"$set": {"front_job_id": job["id"]}})
    tenants.audit(tid, "guest", "guest.express_checkout", f"room {r['number']} at {time}{' luggage' if luggage_help else ''}")
    return {"ok": True, **stay_status(rooms.by_token(token))}


def release_due(tid: str, now: datetime | None = None) -> int:
    """Run the room checkout for express checkouts whose time has come (called lazily on reads). Returns how many."""
    now = now or mongo.now()
    n = 0
    for d in list(mongo.col("guest_checkouts").find({"tenant_id": tid, "status": "scheduled", "due_at": {"$lte": now}}, {"id": 1})):
        claimed = mongo.col("guest_checkouts").find_one_and_update(
            {"id": d["id"], "tenant_id": tid, "status": "scheduled"},
            {"$set": {"status": "processing"}},
            return_document=ReturnDocument.AFTER,
        )
        if not claimed:  # another request got it first
            continue
        room = mongo.col("rooms").find_one({"id": claimed["room_id"], "tenant_id": tid})
        fields: dict = {"status": "done", "done_at": mongo.now()}
        if not room or _stay(room) != claimed["stay"] or room["status"] not in ("occupied", "ready"):
            fields["outcome"] = "already_checked_out"
        else:
            try:
                out = rooms.checkout(tid, room["id"], "guest-express")
                fields.update(outcome="room_checked_out", cleaning_job_id=out.get("current_job_id"))
            except Exception:  # noqa: BLE001 - leave a visible failure for the front desk instead of retrying forever
                fields.update(status="failed", outcome="room checkout failed; front desk to check out manually")
        mongo.col("guest_checkouts").update_one({"id": claimed["id"]}, {"$set": fields})
        tenants.audit(tid, "system", "guest.express_checkout_released", f"room {claimed['room']} {fields['outcome']}")
        n += 1
    return n


# ------------------------------------------------------------------ late checkout
def request_late(token: str, until: str, reason: str = "") -> dict:
    r = rooms.by_token(token)
    tid = r["tenant_id"]
    until = parse_hhmm(until)
    prof = _profile(r)
    lc = prof.get("late_checkout") or {}
    if not lc.get("allowed"):
        raise Invalid("Late checkout is not offered here. Please speak to the front desk.")
    if until <= prof["checkout_time"]:
        raise Invalid(f"That is within the normal checkout time ({prof['checkout_time']}); no request is needed.")
    if until > lc.get("latest", "14:00"):
        raise Invalid(f"Late checkout is possible until {lc.get('latest')} at the latest.")
    if r["status"] != "occupied":
        raise Conflict("This room is not checked in on our system. Please call the front desk.")
    stay = _stay(r)
    open_ = mongo.col("late_checkouts").find_one(
        {"tenant_id": tid, "room_id": r["id"], "stay": stay, "status": {"$in": ["pending", "approved"]}}
    )
    if open_:
        raise Conflict(f"You already have a late checkout request until {open_['until']} ({open_['status']}).")
    doc = {
        "id": mongo.new_id("late"),
        "tenant_id": tid,
        "property_id": r.get("property_id"),
        "room_id": r["id"],
        "room": r["number"],
        "stay": stay,
        "until": until,
        "reason": scrub(reason, 200),
        "status": "pending",
        "note": "",
        "decided_by": None,
        "decided_at": None,
        "date": today(),
        "created_at": mongo.now(),
    }
    mongo.col("late_checkouts").insert_one(doc)
    tenants.audit(tid, "guest", "guest.late_checkout_requested", f"room {r['number']} until {until}")
    return _late_out(doc)


def _late_staff(d: dict) -> dict:
    return {
        "id": d["id"],
        "room": d["room"],
        "until": d["until"],
        "reason": d.get("reason") or "",
        "status": d["status"],
        "note": d.get("note") or "",
        "decided_by": d.get("decided_by"),
        "decided_at": mongo.iso(d.get("decided_at")),
        "created_at": mongo.iso(d.get("created_at")),
        "date": d.get("date"),
    }


def late_checkouts(tid: str, status: str | None = None, limit: int = 200) -> list[dict]:
    flt: dict = {"tenant_id": tid}
    if status:
        flt["status"] = {"$in": status.split(",")}
    return [_late_staff(d) for d in mongo.col("late_checkouts").find(flt).sort([("created_at", -1), ("_id", -1)]).limit(limit)]


def decide_late(tid: str, lid: str, approve: bool, note: str, actor: str) -> dict:
    d = mongo.col("late_checkouts").find_one_and_update(
        {"id": lid, "tenant_id": tid, "status": "pending"},
        {
            "$set": {
                "status": "approved" if approve else "declined",
                "note": scrub(note, 200),
                "decided_by": actor,
                "decided_at": mongo.now(),
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if not d:
        if mongo.col("late_checkouts").count_documents({"id": lid, "tenant_id": tid}, limit=1):
            raise Conflict("This request was already decided.")
        raise NotFound("Late checkout request not found.")
    tenants.audit(tid, actor, "guest.late_checkout_" + d["status"], f"room {d['room']} until {d['until']}")
    return _late_staff(d)


# ------------------------------------------------------------------ feedback
def give_feedback(token: str, rating: int, comment: str = "", lang: str = "en") -> dict:
    r = rooms.by_token(token)
    tid = r["tenant_id"]
    if not 1 <= int(rating) <= 5:
        raise Invalid("Rating must be 1 to 5 stars.")
    doc = {
        "id": mongo.new_id("fb"),
        "tenant_id": tid,
        "property_id": r.get("property_id"),
        "room_id": r["id"],
        "room": r["number"],
        "stay": _stay(r),
        "rating": int(rating),
        "comment": scrub(comment, config.settings.feedback_max_chars),
        "lang": lang if lang in ("en", "hi", "hinglish") else "en",
        "date": today(),
        "created_at": mongo.now(),
    }
    try:
        mongo.col("guest_feedback").insert_one(doc)
    except DuplicateKeyError:
        raise Conflict("Thank you, we already have your feedback for this stay.") from None
    tenants.audit(tid, "guest", "guest.feedback", f"room {r['number']} rating {doc['rating']}")
    return {"ok": True, "rating": doc["rating"]}


# ------------------------------------------------------------------ bill placeholder
BILL_NOTE = "Bills and payment come from the hotel's PMS; not connected in this prototype"


def bill(token: str) -> dict:
    r = rooms.by_token(token)
    prof = _profile(r)
    priced = [d for d in prof.get("dining") or [] if d.get("price_inr") is not None]
    rows = []
    for q in rooms.stay_requests(r):
        t = q["title"].lower()
        for d in priced:
            if d["item"].lower() in t or (len(d["item"]) > 5 and d["item"].lower().split(" with ")[0] in t):
                rows.append({"request": q["title"], "item": d["item"], "price_inr": d["price_inr"], "estimate": True, "at": q["at"]})
                break
    return {
        "available": False,
        "note": BILL_NOTE,
        "requests_with_charges": rows,
        "estimate_total_inr": sum(x["price_inr"] for x in rows),
        "estimate_note": "Estimate from the hotel's listed prices; the final bill comes from the front desk.",
    }


# ------------------------------------------------------------------ hotel views (guest services page)
STAGE = {"new": "open", "offered": "open", "unassigned": "open", "accepted": "accepted", "in_progress": "in_progress", "done": "done"}


def _day_bounds(date: str) -> tuple[datetime, datetime]:
    d = datetime.fromisoformat(date).replace(tzinfo=tz())
    return d.astimezone(UTC), (d + timedelta(days=1)).astimezone(UTC)


def summary(tid: str) -> dict:
    release_due(tid)
    dispatch.sweep(tid)
    day = today()
    start, end = _day_bounds(day)
    now = mongo.now()
    open_rows = []
    for j in (
        mongo.col("jobs")
        .find({"tenant_id": tid, "kind": {"$in": ["guest", "guest_checkout"]}, "status": {"$ne": "done"}})
        .sort([("created_at", 1)])
        .limit(200)
    ):
        created = j["created_at"] if j["created_at"].tzinfo else j["created_at"].replace(tzinfo=UTC)
        open_rows.append(
            {
                "id": j["id"],
                "room": j.get("room"),
                "title": j["title"].split(" · ")[0],
                "department": j["department"],
                "status": j["status"],
                "stage": STAGE.get(j["status"], j["status"]),
                "kind": j.get("kind"),
                "urgency": j.get("urgency"),
                "created_at": mongo.iso(created),
                "minutes_open": int((now - created).total_seconds() // 60),
            }
        )
    # safety / medical alerts for the duty manager (owner, department heads): one row per room and alert
    urgent: dict[tuple, dict] = {}
    for q in open_rows:
        if q.get("urgency") == "urgent":
            urgent.setdefault((q["room"], q["title"]), q)
    today_jobs = list(
        mongo.col("jobs").find(
            {"tenant_id": tid, "kind": "guest", "created_at": {"$gte": start, "$lt": end}}, {"created_at": 1, "accepted_at": 1}
        )
    )
    waits = [(j["accepted_at"] - j["created_at"]).total_seconds() / 60 for j in today_jobs if j.get("accepted_at")]
    co = checkouts(tid, day)["items"]
    fb = feedback(tid, 30)
    return {
        "urgent_alerts": list(urgent.values()),
        "date": day,
        "open_requests": open_rows,
        "requests_today": len(today_jobs),
        "median_response_min": round(median(waits), 1) if waits else None,
        "checkouts_today": {"count": len(co), "luggage_help": sum(1 for c in co if c["luggage_help"]), "items": co},
        "late_checkouts_pending": mongo.col("late_checkouts").count_documents({"tenant_id": tid, "status": "pending"}),
        "feedback_30d": {"count": fb["count"], "average": fb["average"]},
        "synthetic": bool(tenants.get_tenant(tid).get("is_demo")),
    }


def checkouts(tid: str, date: str | None = None) -> dict:
    release_due(tid)
    date = date or today()
    try:
        datetime.fromisoformat(date)
    except ValueError:
        raise Invalid("date must be YYYY-MM-DD") from None
    rows = mongo.col("guest_checkouts").find({"tenant_id": tid, "date": date}).sort([("time", 1), ("room", 1)])
    items = [
        {
            "id": d["id"],
            "room": d["room"],
            "time": d["time"],
            "luggage_help": bool(d.get("luggage_help")),
            "status": d["status"],
            "outcome": d.get("outcome"),
            "front_job_id": d.get("front_job_id"),
            "cleaning_job_id": d.get("cleaning_job_id"),
            "created_at": mongo.iso(d.get("created_at")),
        }
        for d in rows
    ]
    return {"date": date, "items": items}


def feedback(tid: str, days: int = 30) -> dict:
    since = mongo.now() - timedelta(days=days)
    flt = {"tenant_id": tid, "created_at": {"$gte": since}}
    agg = list(
        mongo.col("guest_feedback").aggregate([{"$match": flt}, {"$group": {"_id": None, "n": {"$sum": 1}, "avg": {"$avg": "$rating"}}}])
    )
    by_day = list(
        mongo.col("guest_feedback").aggregate(
            [{"$match": flt}, {"$group": {"_id": "$date", "n": {"$sum": 1}, "avg": {"$avg": "$rating"}}}, {"$sort": {"_id": 1}}]
        )
    )
    items = [
        {
            "id": d["id"],
            "room": d["room"],
            "rating": d["rating"],
            "comment": d.get("comment") or "",
            "lang": d.get("lang"),
            "date": d.get("date"),
            "created_at": mongo.iso(d["created_at"]),
        }
        for d in mongo.col("guest_feedback").find(flt).sort([("created_at", -1), ("_id", -1)]).limit(300)
    ]
    n = agg[0]["n"] if agg else 0
    return {
        "days": days,
        "count": n,
        "average": round(agg[0]["avg"], 2) if n else None,
        "by_day": [{"date": b["_id"], "count": b["n"], "average": round(b["avg"], 2)} for b in by_day],
        "items": items,
    }
