"""Live shift context: who is on shift follows the published roster and the clock (hotel local time), the roster week
repeats by weekday, PUT /dispatch/context is a manual override until the end of the current shift. Offline, SYNTHETIC.

The clock is moved by replacing mongo.now (as the scenario simulator does); the demo tenant's context and roster are
saved and restored around every test.
"""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from hoi_platform import mongo
from hoi_platform.services import dispatch, shifts

IST = timezone(timedelta(hours=5, minutes=30))
TID = "org_demo"
WEEK = "2029-12-24"  # Monday of the demo roster week
# Real days used below: Wed 2026-10-14 -> roster Wed 2029-12-26; its early hours belong to Tue's night (2029-12-25)
ROSTER = [
    {"employee_id": "HS05", "date": "2029-12-26", "shift": "morning", "hours": 8},
    {"employee_id": "HS06", "date": "2029-12-26", "shift": "evening", "hours": 8},
    {"employee_id": "HS19", "date": "2029-12-25", "shift": "night", "hours": 9},
    {"employee_id": "HS20", "date": "2029-12-26", "shift": "night", "hours": 9},
]


def at(hhmm: str, d: str = "2026-10-14") -> datetime:
    h, m = map(int, hhmm.split(":"))
    y, mo, dd = map(int, d.split("-"))
    return datetime(y, mo, dd, h, m, tzinfo=IST).astimezone(UTC)


@pytest.fixture
def clock(monkeypatch):
    state = {"t": at("10:00")}
    monkeypatch.setattr(mongo, "now", lambda: state["t"])

    def set_(hhmm: str, d: str = "2026-10-14") -> None:
        state["t"] = at(hhmm, d)

    return set_


@pytest.fixture(autouse=True)
def _saved():
    ctx = mongo.col("dispatch_context").find_one({"tenant_id": TID}, {"_id": 0})
    snap = mongo.col("roster_snapshots").find_one({"tenant_id": TID}, {"_id": 0})
    mongo.col("dispatch_context").delete_many({"tenant_id": TID})
    mongo.col("roster_snapshots").delete_many({"tenant_id": TID})
    yield
    mongo.col("dispatch_context").delete_many({"tenant_id": TID})
    mongo.col("roster_snapshots").delete_many({"tenant_id": TID})
    mongo.col("jobs").delete_many({"tenant_id": TID, "title": {"$regex": "^Live:"}})
    if ctx:
        mongo.col("dispatch_context").insert_one(ctx)
    if snap:
        mongo.col("roster_snapshots").insert_one(snap)


def _publish(client, owner):
    assert client.put("/dispatch/roster", json={"week_start": WEEK, "assignments": ROSTER}, headers=owner).status_code == 200


# ------------------------------------------------------------------ pure shift clock
@pytest.mark.parametrize(
    ("hhmm", "expect"),
    [
        ("05:59", [("night", "2026-10-13")]),
        ("06:30", [("morning", "2026-10-14"), ("night", "2026-10-13")]),  # hand-over hour: both teams
        ("07:00", [("morning", "2026-10-14")]),  # the night shift ended at 07:00
        ("10:00", [("morning", "2026-10-14")]),
        ("14:30", [("evening", "2026-10-14"), ("morning", "2026-10-14")]),
        ("15:00", [("evening", "2026-10-14")]),
        ("18:00", [("evening", "2026-10-14")]),
        ("22:30", [("night", "2026-10-14"), ("evening", "2026-10-14")]),
        ("23:59", [("night", "2026-10-14")]),
        ("00:00", [("night", "2026-10-13")]),  # after midnight: still the previous date's night shift
        ("02:00", [("night", "2026-10-13")]),
    ],
)
def test_running_shifts(hhmm, expect):
    run = shifts.running(at(hhmm).astimezone(IST), shifts.windows())
    assert [(r["shift"], r["date"].isoformat()) for r in run] == expect


def test_hotel_shift_windows_override():
    w = shifts.windows({"shift_windows": {"day": ["08:00", "20:00"], "night": ["20:00", "08:00"]}})
    assert w == {"day": (480, 720), "night": (1200, 720)}
    assert [r["shift"] for r in shifts.running(at("21:00").astimezone(IST), w)] == ["night"]


@pytest.mark.parametrize(
    ("real", "roster_day"),
    [
        ("2029-12-26", "2029-12-26"),  # inside the published week: itself
        ("2026-10-14", "2029-12-26"),  # Wednesday, published week in the future
        ("2020-01-06", "2029-12-24"),  # Monday, an old date
        ("2031-03-02", "2029-12-30"),  # Sunday, after the published week
    ],
)
def test_week_mapping(real, roster_day):
    dates = sorted({a["date"] for a in ROSTER})
    assert shifts.map_to_week(date.fromisoformat(real), WEEK, dates) == roster_day


# ------------------------------------------------------------------ live context through the API
def test_live_context_follows_the_clock(client, owner, clock):
    _publish(client, owner)
    clock("10:00")
    c = client.get("/dispatch/context", headers=owner).json()
    assert c["source"] == "live roster (auto)" and c["override_until"] is None
    assert (c["day"], c["shift"], c["working"]) == ("2029-12-26", "morning", {"HS05": "housekeeping"})
    assert c["roster_week_mapped"] is True and c["shift_window"] == {"start": "06:00", "end": "15:00"}
    clock("18:00")
    c = client.get("/dispatch/context", headers=owner).json()
    assert (c["shift"], c["working"]) == ("evening", {"HS06": "housekeeping"})
    clock("02:00")
    c = client.get("/dispatch/context", headers=owner).json()
    assert (c["day"], c["shift"], c["working"]) == ("2029-12-25", "night", {"HS19": "security"})
    clock("22:30")  # hand-over: the evening housekeeper and the night guard
    assert client.get("/dispatch/context", headers=owner).json()["working"] == {"HS06": "housekeeping", "HS20": "security"}


def test_override_lasts_until_the_end_of_the_shift(client, owner, clock):
    _publish(client, owner)
    clock("10:00")
    body = {"day": "2029-12-25", "shift": "night", "working": {"HS18": "maintenance"}, "bands": {"HS18": "watch"}}
    c = client.put("/dispatch/context", json=body, headers=owner).json()
    assert c["source"] == "manual override until 15:00" and c["working"] == {"HS18": "maintenance"}
    clock("14:59")
    assert client.get("/dispatch/context", headers=owner).json()["working"] == {"HS18": "maintenance"}
    clock("15:00")
    c = client.get("/dispatch/context", headers=owner).json()
    assert c["source"] == "live roster (auto)" and c["working"] == {"HS06": "housekeeping"}
    assert c["bands"] == {"HS18": "watch"}  # bands are kept from the stored context

    clock("16:00")  # an override set in the evening lasts until 23:00; clearing it returns to the live roster at once
    c = client.put("/dispatch/context", json=body, headers=owner).json()
    assert c["source"] == "manual override until 23:00"
    c = client.delete("/dispatch/context/override", headers=owner).json()
    assert c["source"] == "live roster (auto)" and c["working"] == {"HS06": "housekeeping"}


def test_bands_only_update_keeps_the_live_roster(client, owner, clock):
    _publish(client, owner)
    clock("10:00")
    c = client.put("/dispatch/context", json={"override": False, "bands": {"HS05": "high"}, "floors": 3}, headers=owner).json()
    assert c["source"] == "live roster (auto)" and c["working"] == {"HS05": "housekeeping"}
    assert c["bands"] == {"HS05": "high"} and c["floors"] == 3


def test_job_at_ten_goes_to_the_morning_housekeeper(client, owner, clock):
    _publish(client, owner)
    clock("10:00")
    job = client.post("/dispatch/jobs", json={"title": "Live: extra towels", "department": "housekeeping", "urgency": "low"}, headers=owner)
    assert job.json()["status"] == "offered" and job.json()["offer_to"] == "HS05"
    clock("18:00")
    job = client.post("/dispatch/jobs", json={"title": "Live: fresh linen", "department": "housekeeping", "urgency": "low"}, headers=owner)
    assert job.json()["offer_to"] == "HS06"


def test_me_shifts_use_the_same_live_context(client, owner, worker, clock):
    _publish(client, owner)
    clock("10:00")
    me = client.get("/me/shifts", headers=worker).json()
    assert me["on_shift_now"] is True and me["current_shift"]["shift"] == "morning" and me["current_shift"]["day"] == "2029-12-26"
    assert me["current_shift"]["source"] == "live roster (auto)"
    # the real date of that shift, so the app shows today's date instead of the SYNTHETIC roster week's
    real = date.fromisoformat(me["current_shift"]["local_date"])
    assert real.year < 2029 and real.weekday() == date(2029, 12, 26).weekday() and me["current_shift"]["roster_week_mapped"]
    clock("18:00")
    me = client.get("/me/shifts", headers=worker).json()
    assert me["on_shift_now"] is False and me["current_shift"]["shift"] == "evening"


def test_no_roster_falls_back_to_all_staff(client, owner, clock):
    clock("10:00")
    c = dispatch.get_context(TID)
    staff = {s["employee_id"] for s in dispatch.tenants.staff(TID)}
    assert c["source"].startswith("imported staff") and set(c["working"]) == staff and c["day"] is None
