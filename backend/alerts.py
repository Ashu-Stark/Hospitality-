"""Hotel alerts: plain-language warnings with a severity, the reason (with numbers) and one
suggested action. GET /alerts (POST /alerts to add inventory rows or bookings).

Rules (thresholds in config.yaml `alerts`, every one ASSUMED):
  rush_ahead          forecast for the next days >= rush_occupancy, or a jump against the same
                      weekday last week
  staff_short         the latest shift plan leaves a department below coverage_min or with
                      >= short_hours_min unfilled hours (demand comes from the forecast)
  high_cancellation   expected cancellations / no-shows on peak nights >= cancel_alert_share of
                      the rooms (min 2), from the REAL-data cancellation model's base-rate table
                      or, when bookings are sent, its per-booking probabilities
  weather_risk        heavy rain or snow in the live Open-Meteo forecast for the hotel location
  staff_leaving       more people in the high leaving-risk band than last week
  stock_out           an item runs out before the supplier can deliver (inventory rows sent by
                      the caller: the ops API holds no inventory; the platform API does)

Each rule is a pure function of its inputs (tested one by one). The engine collects inputs,
runs the rules, deduplicates by alert id (one alert per rule and subject) and applies a cooldown:
`notify` is true only when the alert is new, its severity rose, or cooldown_hours passed since
it was last notified (collection alert_log). Data: forecast, roster, staff scores and the demo
calendar are SYNTHETIC; the cancellation model is trained on REAL Portuguese hotel data; the
weather is a REAL live forecast for real calendar days. Staff appear as ids only.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from pymongo.database import Database

from backend.config import AlertsConfig, Settings, hotel_data
from backend.db import EMPLOYEES, NO_ID, ROSTERS, audit, insert, ms, utcnow
from backend.services import NotAvailable, Service
from backend.weather import OpenMeteo, WeatherDay, WeatherUnavailable

ALERT_LOG = "alert_log"
Severity = Literal["high", "medium", "low"]
RANK = {"high": 0, "medium": 1, "low": 2}
DEPT = {"housekeeping": "housekeeping", "front_office": "front desk", "fnb_service": "restaurant",
        "kitchen": "kitchen", "maintenance": "maintenance", "security": "security"}


class Alert(BaseModel):
    id: str  # rule + subject: the deduplication key
    kind: str
    severity: Severity
    title: str  # one plain sentence
    reason: str  # why, with the numbers
    action: str  # one suggested action
    target: str | None = None  # dashboard page for the action
    dates: list[date] = Field(default_factory=list)
    confidence: str = "medium"
    data_note: str = ""
    notify: bool = True  # false while the same alert is in its cooldown


class AlertsResult(BaseModel):
    today: date
    window: list[date]  # first and last day looked at
    alerts: list[Alert]
    not_checked: list[str]  # rules that could not run, and why
    synthetic: bool = True
    note: str = ("Forecast, shift plan, staff and the demo calendar are SYNTHETIC. Cancellation "
                 "rates come from REAL Portuguese hotel data, not this hotel. Weather is a REAL "
                 "live forecast for real calendar days.")


class AlertsRequest(BaseModel):
    today: date | None = None
    inventory: list[dict] | None = None  # platform /inventory/suggestions rows
    bookings: list[dict] | None = None  # bookings on the books (booking fields only)


def day(d: date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def _sev_max(*s: Severity) -> Severity:
    return min(s, key=lambda x: RANK[x])


# ------------------------------------------------------------------ rules (pure functions)
def rush_rule(days: list[dict], rooms: int, last_week: dict[int, tuple[date, int]],
              cfg: AlertsConfig, confidence: str = "medium") -> list[Alert]:
    """days: [{date, mean, low, high}] (occupancy 0..1). last_week: weekday -> (date, rooms)."""
    jump_min = max(cfg.rush_jump_min_rooms, math.ceil(cfg.rush_jump_share * rooms))
    busy = []
    for d in days:
        r = round(d["mean"] * rooms)
        prev = last_week.get(d["date"].weekday())
        jump = r - prev[1] if prev else 0
        if d["mean"] >= cfg.rush_occupancy or jump >= jump_min:
            busy.append({**d, "rooms": r, "lo": round(d["low"] * rooms),
                         "hi": round(d["high"] * rooms), "prev": prev, "jump": jump})
    if not busy:
        return []
    top = max(busy, key=lambda b: (b["rooms"], b["jump"]))
    prev_txt = (f"; last {top['date']:%A} {top['prev'][1]}" if top["prev"] else "")
    others = [b for b in busy if b is not top]
    listed = ", ".join(f"{day(b['date'])} about {b['rooms']}" for b in others[:3])
    tail = f" and {len(others) - 3} more day(s)." if len(others) > 3 else "."
    more = f" Also busy: {listed}{tail}" if others else ""
    sev: Severity = ("high" if top["mean"] >= 0.95 or top["rooms"] >= rooms - 1
                     or top["jump"] >= 2 * jump_min else "medium")
    return [Alert(
        id=f"rush_ahead:{top['date']}", kind="rush_ahead", severity=sev,
        title=f"Busy {day(top['date'])}: about {top['rooms']} of {rooms} rooms expected.",
        reason=(f"{top['date']:%A} about {top['rooms']} of {rooms} rooms (likely "
                f"{top['lo']}-{top['hi']}){prev_txt}.{more}"),
        action=("Check the shift plan for these days and line up extra housekeeping and kitchen "
                "help early."),
        target="pages/5_Roster.py", dates=sorted(b["date"] for b in busy), confidence=confidence,
        data_note="SYNTHETIC forecast")]


def staff_short_rule(roster: dict | None, cfg: AlertsConfig, shift_hours: float = 9.0
                     ) -> list[Alert]:
    """roster: a stored roster document (summary.coverage, summary.violated_soft_goals).
    One alert per week (deduplicated across teams), naming the worst teams first."""
    if not roster:
        return []
    week = date.fromisoformat(roster["week_start"])
    goals = [g for g in roster["summary"].get("violated_soft_goals", [])
             if g.get("goal") == "understaffed"]
    short = []
    for c in roster["summary"].get("coverage", []):
        hours = float(c.get("understaffed_hours", 0))
        if c.get("coverage", 1.0) < cfg.coverage_min or hours >= cfg.short_hours_min:
            short.append((hours, c))
    if not short:
        return []
    short.sort(key=lambda x: -x[0])
    hours0, c0 = short[0]
    dept0 = c0["department"]
    name0 = DEPT.get(dept0, dept0.replace("_", " "))
    cells = sorted((g for g in goals if g["department"] == dept0), key=lambda g: -g["hours_short"])
    days0 = sorted({week + timedelta(days=int(g["day"])) for g in cells})
    worst = ", ".join(f"{day(week + timedelta(days=int(g['day'])))} {g['shift']} "
                      f"{g['hours_short']:.0f} h" for g in cells[:3])
    people = max(1, math.ceil(hours0 / shift_hours / max(1, len(days0))))
    # hours short per team (a team can be over-covered on some shifts and short on others,
    # so its overall coverage share can look high while shifts are still unfilled)
    teams = "; ".join(f"{DEPT.get(c['department'], c['department'])} {h:.0f} h short"
                      for h, c in short[:4])
    total = sum(h for h, _ in short)
    all_days = sorted({week + timedelta(days=int(g["day"])) for g in goals
                       if g["department"] in {c["department"] for _, c in short}})
    return [Alert(
        id=f"staff_short:{week}", kind="staff_short",
        severity="high" if hours0 >= 2 * shift_hours else "medium",
        title=(f"Short of staff in {len(short)} team(s) this week; {name0} is the biggest gap "
               f"({hours0:.0f} h)."),
        reason=(f"The shift plan leaves {total:.0f} of the hours the forecast needs uncovered: "
                f"{teams}" + (f". Worst {name0} shifts: {worst}." if worst else ".")),
        action=f"Ask for about {people} extra {name0} person(s) on the short days, or move "
               "someone from a quieter team.",
        target="pages/20_Extra_Staff.py", dates=all_days, confidence="medium",
        data_note="SYNTHETIC shift plan and forecast")]


def cancellation_rule(nights: list[dict], rooms: int, cfg: AlertsConfig) -> list[Alert]:
    """nights: [{date, mean (forecast occupancy), on_books, adjustment (NightAdjustment dict),
    top_bookings ([refs] when bookings were sent)}]. Only peak nights count."""
    k = max(2, math.ceil(cfg.cancel_alert_share * rooms))
    hit = [n for n in nights if n["mean"] >= cfg.peak_occupancy
           and n["adjustment"]["expected_cancellations"] >= k]
    if not hit:
        return []
    top = max(hit, key=lambda n: n["adjustment"]["expected_cancellations"])
    a = top["adjustment"]
    refs = top.get("top_bookings") or []
    action = ("Reconfirm these bookings first: " + ", ".join(refs[:3]) + "; keep 1-2 guests on a "
              "waitlist instead of overbooking." if refs else
              "Reconfirm bookings for this night by phone or message and keep 1-2 guests on a "
              "waitlist instead of overbooking.")
    return [Alert(
        id=f"high_cancellation:{top['date']}", kind="high_cancellation",
        severity="high" if a["expected_cancellations"] >= 2 * k else "medium",
        title=f"{day(top['date'])}: about {a['expected_cancellations']:.0f} booked room(s) may "
              "cancel or not show.",
        reason=(f"{top['on_books']} rooms booked on a peak night (forecast about "
                f"{round(top['mean'] * rooms)} of {rooms}); expected to really stay "
                f"{a['expected_rooms']:.0f} (likely {a['low']:.0f}-{a['high']:.0f}). Source: "
                f"{a['source'].replace('_', ' ')}."),
        action=action, target="pages/17_Guest_Services.py",
        dates=sorted(n["date"] for n in hit), confidence="low",
        data_note="cancellation rates learned on REAL Portuguese hotel bookings (CC BY 4.0), "
                  "applied to SYNTHETIC bookings")]


def weather_rule(days: list[WeatherDay], cfg: AlertsConfig) -> list[Alert]:
    w = cfg.weather
    bad = [d for d in days if d.rain_mm >= w.rather_heavy_rain_mm or d.snow_cm >= w.snow_cm]
    if not bad:
        return []

    def what(d: WeatherDay) -> str:
        parts = []
        if d.rain_mm >= w.rather_heavy_rain_mm:
            parts.append(f"{'heavy' if d.rain_mm >= w.heavy_rain_mm else 'rather heavy'} rain "
                         f"{d.rain_mm:.0f} mm")
        if d.snow_cm >= w.snow_cm:
            parts.append(f"{'heavy ' if d.snow_cm >= w.heavy_snow_cm else ''}snow "
                         f"{d.snow_cm:.0f} cm")
        return f"{day(d.date)} " + " and ".join(parts)

    severe = any(d.rain_mm >= w.heavy_rain_mm or d.snow_cm >= w.heavy_snow_cm for d in bad)
    return [Alert(
        id=f"weather_risk:{bad[0].date}", kind="weather_risk",
        severity="high" if severe else "medium",
        title=f"{'Heavy ' if severe else ''}rain or snow ahead near {w.location_name} "
              f"({day(bad[0].date)}).",
        reason="Live forecast: " + "; ".join(what(d) for d in bad[:3]) + ". Hill roads can slow "
               "down or close: expect late arrivals and some cancellations.",
        action="Message arriving guests to check the road before they set out, and check "
               "generator diesel and stock of essentials.",
        target="pages/17_Guest_Services.py", dates=[d.date for d in bad], confidence="medium",
        data_note="REAL live forecast (Open-Meteo.com, CC BY 4.0) for real calendar days")]


def leaving_rule(now: list, before: list, cfg: AlertsConfig, confidence: str = "medium"
                 ) -> list[Alert]:
    """now / before: AttritionScore lists of this week and the week before (ids only)."""
    def high(xs: list) -> set[str]:
        return {s.employee_id for s in xs if s.band == "high" and not s.is_demo_hero}

    h_now, h_before = high(now), high(before)
    up = len(h_now) - len(h_before)
    if up < cfg.leaving_min_increase:
        return []
    new = sorted(h_now - h_before)
    week = now[0].week_start if now else None
    return [Alert(
        id=f"staff_leaving:{week}", kind="staff_leaving",
        severity="high" if up >= 3 else "medium",
        title=f"{len(h_now)} staff now at high risk of leaving (last week {len(h_before)}).",
        reason=(f"{up} more in the high band this week" + (f"; new: {', '.join(new[:5])}"
                                                          if new else "") + "."),
        action="Have a short, friendly check-in with them this week. It is support, not a "
               "warning.",
        target="pages/2_Risk_List.py", dates=[week] if week else [], confidence=confidence,
        data_note="SYNTHETIC staff data; ids only")]


def stock_rule(items: list[dict], occupancy: list[float], rooms: int, cfg: AlertsConfig
               ) -> list[Alert]:
    """items: platform /inventory/suggestions rows (name, on_hand, on_order, per_occ_room,
    lead_days). occupancy: forecast occupancy per day from today (0..1)."""
    mean = sum(occupancy) / len(occupancy) if occupancy else 0.7
    short = []
    for it in items:
        per = float(it.get("per_occ_room") or 0)
        if per <= 0:
            continue  # not used per occupied room: the Today page's reorder-point rule covers it
        stock = float(it.get("on_hand") or 0) + float(it.get("on_order") or 0)
        lead = int(it.get("lead_days") or 0)
        need = lead + cfg.stock_buffer_days
        used, out_day = 0.0, None
        for i in range(max(need, len(occupancy))):
            used += per * rooms * (occupancy[i] if i < len(occupancy) else mean)
            if used > stock:
                out_day = i
                break
        if out_day is not None and out_day < need:
            short.append((out_day, lead, it))
    if not short:
        return []
    short.sort(key=lambda x: x[0])
    d0, lead0, it0 = short[0]
    names = ", ".join(f"{it.get('name', it.get('id'))} (about {d} day(s) left, supplier "
                      f"{lead} day(s))" for d, lead, it in short[:3])
    return [Alert(
        id="stock_out:" + ",".join(sorted(str(it.get("id", it.get("name"))) for _, _, it in short)),
        kind="stock_out", severity="high" if d0 < lead0 else "medium",
        title=f"{it0.get('name', 'An item')} may run out in about {d0} day(s).",
        reason=f"At the forecast occupancy: {names}.",
        action="Order now (the Supplies page suggests quantities).",
        target="pages/13_Inventory.py", confidence="medium",
        data_note="SYNTHETIC forecast; stock from the hotel's inventory")]


# ------------------------------------------------------------------ cooldown / dedup
def dedupe(alerts: list[Alert]) -> list[Alert]:
    best: dict[str, Alert] = {}
    for a in alerts:
        if a.id not in best or RANK[a.severity] < RANK[best[a.id].severity]:
            best[a.id] = a
    return sorted(best.values(), key=lambda a: (RANK[a.severity], a.kind, a.id))


def apply_cooldown(db: Database, alerts: list[Alert], cooldown_hours: float, now: datetime,
                   source: str) -> list[Alert]:
    """notify = new, severity rose, or the cooldown passed; logs every notified alert."""
    out = []
    for a in alerts:
        last = db[ALERT_LOG].find_one({"alert_id": a.id}, NO_ID)
        fresh = last is None
        rose = last is not None and RANK[a.severity] < RANK[last["severity"]]
        lt = last["last_notified"] if last else None
        if lt is not None and lt.tzinfo is None:
            lt = lt.replace(tzinfo=UTC)
        expired = lt is not None and now - lt >= timedelta(hours=cooldown_hours)
        notify = fresh or rose or expired
        if fresh:
            insert(db, ALERT_LOG, {"alert_id": a.id, "kind": a.kind, "severity": a.severity,
                                   "last_notified": ms(now), "times_notified": 1}, source)
        elif notify:
            db[ALERT_LOG].update_one({"alert_id": a.id}, {
                "$set": {"severity": a.severity, "last_notified": ms(now)},
                "$inc": {"times_notified": 1}})
        out.append(a.model_copy(update={"notify": notify}))
    return out


# ------------------------------------------------------------------ engine
def today_of(db: Database) -> date:
    """The demo's 'today': the Monday of the SYNTHETIC snapshot week."""
    row = db[EMPLOYEES].find_one({}, {"_id": 0, "week_start": 1})
    if row is None:
        raise ValueError("no employee snapshot: POST /demo/reset first")
    return date.fromisoformat(row["week_start"])


def past_occupancy(data_dir) -> pd.DataFrame:  # noqa: ANN001 - Path
    df = pd.read_csv(data_dir / "occupancy_daily.csv", usecols=["date", "occupancy_pct",
                                                                "rooms_sold", "booking_pace_7d"])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df.set_index("date")


def build(db: Database, service: Service, settings: Settings,
          weather: Callable[[], list[WeatherDay]] | None, body: AlertsRequest,
          now: datetime | None = None, source: str = "api") -> AlertsResult:
    from ml.realdata.hotel_alerts import api as cancellation

    cfg = settings.config.alerts
    hotel = hotel_data(settings.hotel)
    rooms = hotel.rooms
    today = body.today or today_of(db)
    as_of = today - timedelta(days=1)
    occ = past_occupancy(hotel.data_dir)
    end = min(today + timedelta(days=cfg.horizon_days - 1), max(occ.index))
    alerts: list[Alert] = []
    skipped: list[str] = []
    if end < today:
        raise ValueError(f"today {today} is after the end of the SYNTHETIC data")
    if end < today + timedelta(days=cfg.horizon_days - 1):
        skipped.append(f"forecast stops at {end} (end of the SYNTHETIC data), not "
                       f"{cfg.horizon_days} days ahead")

    # forecast (guarded) -> rush + cancellation + stock
    fc = service.forecast(today, end, as_of)
    conf = getattr(fc, "confidence", "medium")
    days = [{"date": d.date, "mean": d.mean, "low": d.low, "high": d.high} for d in fc.days]
    last_week = {}
    for i in range(1, 8):
        d = as_of - timedelta(days=i - 1)
        if d in occ.index:
            last_week.setdefault(d.weekday(), (d, int(occ.loc[d, "rooms_sold"])))
    alerts += rush_rule(days, rooms, last_week, cfg, conf)

    # staff short: the latest stored shift plan
    roster = db[ROSTERS].find_one({}, NO_ID, sort=[("id", -1)])
    if roster is None:
        skipped.append("staff short: no shift plan made yet (make one on the Shift plan page)")
    else:
        hours = settings.config.roster.shifts
        alerts += staff_short_rule(roster, cfg, float(next(iter(hours.values())).hours))

    # cancellations: rooms on the books a week before each night (known by as_of)
    probs_by_night: dict[date, list[tuple[str, float]]] = {}
    if body.bookings:
        scored = service.cancellation(body.bookings, as_of)
        for b, raw in zip(scored.bookings, body.bookings, strict=True):
            n = int(raw.get("nights") or 1)
            for k in range(n):
                # a cancelled booking frees every night of the stay
                probs_by_night.setdefault(b.arrival + timedelta(days=k), []).append(
                    (b.booking_ref, b.p_cancel))
    nights = []
    for d in days:
        dt, ahead = d["date"], (d["date"] - as_of).days
        given = probs_by_night.get(dt)
        if given:
            adj = cancellation.night_adjustment(len(given), ahead, rooms, [p for _, p in given])
            top = [r for r, p in sorted(given, key=lambda x: -x[1]) if p > 0][:3]
            nights.append({"date": dt, "mean": d["mean"], "on_books": len(given),
                           "adjustment": adj.model_dump(), "top_bookings": top})
        elif dt - timedelta(days=7) <= as_of and dt in occ.index:
            ob = int(occ.loc[dt, "booking_pace_7d"])
            adj = cancellation.night_adjustment(ob, ahead, rooms)
            nights.append({"date": dt, "mean": d["mean"], "on_books": ob,
                           "adjustment": adj.model_dump()})
    alerts += cancellation_rule(nights, rooms, cfg)

    # weather
    if weather is None:
        skipped.append("weather: no forecast source configured")
    else:
        try:
            alerts += weather_rule(weather(), cfg)
        except WeatherUnavailable as e:
            skipped.append(f"weather: {e}")

    # staff leaving: this week vs last week
    try:
        week = service.latest_week()
        now_s = service.score(week, None)
        before = service.score(week - timedelta(days=7), None)
        lconf = min((getattr(s, "confidence", "medium") for s in now_s),
                    key=lambda c: {"low": 0, "medium": 1, "high": 2}.get(c, 1), default="medium")
        alerts += leaving_rule(now_s, before, cfg, lconf)
    except (NotAvailable, ValueError) as e:
        skipped.append(f"staff leaving: {e}")

    # stock
    if body.inventory is None:
        skipped.append("stock-out: inventory not sent (POST /alerts with the platform's "
                       "/inventory/suggestions rows)")
    else:
        alerts += stock_rule(body.inventory, [d["mean"] for d in days], rooms, cfg)

    final = apply_cooldown(db, dedupe(alerts), cfg.cooldown_hours, now or utcnow(), source)
    audit(db, "alerts.build", {"today": today, "alerts": [a.id for a in final],
                               "notified": [a.id for a in final if a.notify],
                               "not_checked": len(skipped)}, source)
    return AlertsResult(today=today, window=[today, end], alerts=final, not_checked=skipped)


def default_weather(settings: Settings) -> Callable[[], list[WeatherDay]] | None:
    w = settings.config.alerts.weather
    return OpenMeteo(w) if w.enabled else None


def router(get_db, get_service, source_of) -> APIRouter:  # noqa: ANN001
    from backend.main import _guard

    r = APIRouter()

    @r.get("/alerts", response_model=AlertsResult)
    def alerts_get(request: Request, today: date | None = Query(default=None),
                   db: Database = Depends(get_db),
                   service: Service = Depends(get_service)) -> AlertsResult:
        return _guard(lambda: build(db, service, request.app.state.settings,
                                    request.app.state.weather, AlertsRequest(today=today),
                                    source=source_of(request)))

    @r.post("/alerts", response_model=AlertsResult)
    def alerts_post(body: AlertsRequest, request: Request, db: Database = Depends(get_db),
                    service: Service = Depends(get_service)) -> AlertsResult:
        return _guard(lambda: build(db, service, request.app.state.settings,
                                    request.app.state.weather, body,
                                    source=source_of(request)))

    return r
