"""Officials' analytics: chart-ready JSON. Every response carries `synthetic: true` and a `note`.

`district=None` means state-wide (state admin); routers force the officer's own district.
Workforce figures are aggregated only, never per business or per person, and a group is shown only when at least
K_MIN businesses contribute (k-anonymity); otherwise it is suppressed with a reason.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta

from .. import catalog, mongo
from ..seed.destinations import BY_ID_DEST, DESTINATIONS
from ..seed.districts import BY_ID as DISTRICTS
from ..seed.districts import DISTRICTS as DISTRICT_LIST
from . import crowd, grievances, registry

K_MIN = 5
NOTE = catalog.SYNTHETIC_NOTE
YEARS = list(range(2019, 2027))


def _envelope(district: str | None, **body) -> dict:
    return {
        "synthetic": True,
        "note": NOTE,
        "scope": {"district": district, "district_name": DISTRICTS[district]["name"] if district else "All districts (state)"},
        "generated_at": mongo.iso(mongo.now()),
        **body,
    }


def _dests(district: str | None) -> list[str]:
    return [d["id"] for d in DESTINATIONS if not district or d["district"] == district]


def _yoy(cur: float | None, prev: float | None) -> float | None:
    if not cur or not prev:
        return None
    return round(100.0 * (cur - prev) / prev, 1)


def _occ_pct(data: dict, dest_ids: list[str], days: list[date], types=catalog.STAY_TYPES) -> float | None:
    a = o = 0
    for dest in dest_ids:
        for t in types:
            series = data.get((dest, t), {})
            for d in days:
                v = series.get(d)
                if v:
                    a, o = a + v[0], o + v[1]
    return round(100.0 * o / a, 1) if a else None


# ------------------------------------------------------------------ KPIs
def kpis(district: str | None) -> dict:
    db = mongo.db()
    f = {"district": district} if district else {}
    biz = [mongo.clean(b) for b in db.businesses.find(f, {"_id": 0, "status": 1, "valid_until": 1, "type": 1, "capacity": 1, "beds": 1})]
    statuses = Counter(registry.effective_status(b) for b in biz)
    active_stays = [b for b in biz if b["type"] in catalog.STAY_TYPES and registry.effective_status(b) == "active"]
    g = [mongo.clean(x) for x in db.grievances.find(f)]
    open_g = [x for x in g if x["status"] in catalog.GRIEVANCE_OPEN]
    overdue = [x for x in open_g if mongo.now() > mongo.aware(x["sla_due_at"])]
    today = date.today()
    ctx = crowd.Context()
    last30 = [today - timedelta(days=i) for i in range(1, 31)]
    occ30 = _occ_pct(ctx.data, _dests(district), last30)
    alerts = []
    for dest in _dests(district):
        look = crowd.outlook(ctx, dest, today, 14)
        peak = max(look, key=lambda x: x["index"])
        if peak["index"] >= crowd.ALERT_AT:
            alerts.append(
                {"destination_id": dest, "name": BY_ID_DEST[dest]["name"], "peak_index": peak["index"], "peak_date": peak["date"]}
            )
    pending = db.applications.count_documents({**f, "status": "submitted"})
    tiles = [
        {"key": "registered_businesses", "label": "Registered businesses (active)", "value": statuses.get("active", 0)},
        {"key": "active_rooms", "label": "Active rooms", "value": sum(b["capacity"] for b in active_stays)},
        {"key": "active_beds", "label": "Active beds", "value": sum(b.get("beds") or 0 for b in active_stays)},
        {"key": "applications_pending", "label": "Applications pending review", "value": pending},
        {"key": "grievances_open", "label": "Grievances open", "value": len(open_g)},
        {"key": "grievances_overdue", "label": f"Grievances past {catalog.GRIEVANCE_SLA_DAYS}-day SLA", "value": len(overdue)},
        {"key": "avg_occupancy_30d", "label": "Average occupancy, last 30 days", "value": occ30, "unit": "%"},
        {"key": "crowd_alerts", "label": "Destinations with very high crowd outlook (14 days)", "value": len(alerts)},
    ]
    return _envelope(
        district,
        kpis=tiles,
        businesses_by_status={s: statuses.get(s, 0) for s in catalog.BUSINESS_STATUSES},
        crowd_alerts=sorted(alerts, key=lambda a: -a["peak_index"]),
    )


# ------------------------------------------------------------------ rush
def rush(district: str | None, top_n: int = 10) -> dict:
    ctx = crowd.Context()
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    weeks = [monday + timedelta(weeks=w) for w in range(-8, 8)]
    rows, top, alerts = [], [], []
    for dest in _dests(district):
        values = []
        for w in weeks:
            days = [crowd.day_index(ctx, dest, w + timedelta(days=i)) for i in range(7)]
            values.append(round(sum(x["index"] for x in days) / 7))
        rows.append({"destination_id": dest, "name": BY_ID_DEST[dest]["name"], "district": BY_ID_DEST[dest]["district"], "values": values})
        look = crowd.outlook(ctx, dest, today, 14)
        avg = round(sum(x["index"] for x in look) / len(look))
        peak = max(look, key=lambda x: x["index"])
        top.append(
            {
                "destination_id": dest,
                "name": BY_ID_DEST[dest]["name"],
                "avg_index_14d": avg,
                "band": crowd.band(avg),
                "peak_index": peak["index"],
                "peak_date": peak["date"],
            }
        )
        for x in look:
            if x["index"] >= crowd.ALERT_AT:
                alerts.append(
                    {
                        "destination_id": dest,
                        "name": BY_ID_DEST[dest]["name"],
                        "date": x["date"],
                        "index": x["index"],
                        "events": x["events"],
                    }
                )
    top.sort(key=lambda x: -x["avg_index_14d"])
    return _envelope(
        district,
        label="estimate",
        bands=crowd.BANDS,
        heatmap={
            "weeks": [w.isoformat() for w in weeks],
            "week_kind": ["past" if w + timedelta(days=6) < today else "current" if w <= today else "outlook" for w in weeks],
            "rows": rows,
        },
        top=top[:top_n],
        alerts=sorted(alerts, key=lambda a: (a["date"], -a["index"])),
        alert_threshold=crowd.ALERT_AT,
    )


# ------------------------------------------------------------------ occupancy trend
def occupancy_trend(district: str | None, btype: str | None, days: int = 365, granularity: str = "daily") -> dict:
    data = crowd.occupancy_data()
    today = date.today()
    days = max(7, min(days, 730))
    all_days = [today - timedelta(days=i) for i in range(days, 0, -1)]
    if granularity == "weekly":
        buckets = [all_days[i : i + 7] for i in range(0, len(all_days), 7)]
    elif granularity == "monthly":
        grouped: dict = defaultdict(list)
        for d in all_days:
            grouped[d.strftime("%Y-%m")].append(d)
        buckets = list(grouped.values())
    else:
        buckets = [[d] for d in all_days]
    types = (btype,) if btype in catalog.STAY_TYPES else catalog.STAY_TYPES
    dests = _dests(district)

    def series(dest_ids, tps):
        return [_occ_pct(data, dest_ids, b, tps) for b in buckets]

    overall = {"key": district or "state", "label": DISTRICTS[district]["name"] if district else "State", "values": series(dests, types)}
    by_district = []
    for dd in DISTRICT_LIST:
        if district and dd["id"] != district:
            continue
        by_district.append({"key": dd["id"], "label": dd["name"], "values": series(_dests(dd["id"]), types)})
    by_type = [{"key": t, "label": catalog.BUSINESS_TYPES[t][0], "values": series(dests, (t,))} for t in catalog.STAY_TYPES]
    return _envelope(
        district,
        unit="%",
        granularity=granularity,
        type=btype,
        dates=[b[0].isoformat() for b in buckets],
        overall=overall,
        by_district=by_district,
        by_type=by_type,
    )


# ------------------------------------------------------------------ market growth
def market(district: str | None) -> dict:
    db = mongo.db()
    f = {"district": district} if district else {}
    arr = [mongo.clean(a) for a in db.arrivals.find(f)]
    regs = Counter()
    regs_by_district: dict = defaultdict(Counter)
    for b in db.businesses.find(f, {"registered_on": 1, "district": 1}):
        y = int(b["registered_on"][:4])
        regs[y] += 1
        regs_by_district[b["district"]][y] += 1
    totals = []
    prev = prev_reg = None
    for y in YEARS:
        rows = [a for a in arr if a["year"] == y]
        dom, fgn = sum(a["domestic"] for a in rows), sum(a["foreign"] for a in rows)
        partial = any(a.get("partial_year") for a in rows)
        total = dom + fgn
        totals.append(
            {
                "year": y,
                "domestic": dom,
                "foreign": fgn,
                "total": total,
                "yoy_pct": None if partial else _yoy(total, prev),
                "partial_year": partial,
                "registrations": regs.get(y, 0),
                "registrations_yoy_pct": None if partial else _yoy(regs.get(y, 0), prev_reg),
            }
        )
        prev, prev_reg = total, regs.get(y, 0)
    by_district = []
    for dd in DISTRICT_LIST:
        if district and dd["id"] != district:
            continue
        rows = sorted((a for a in arr if a["district"] == dd["id"]), key=lambda a: a["year"])
        values = [a["domestic"] + a["foreign"] for a in rows]
        full = [r for r in rows if not r.get("partial_year")]
        last_yoy = _yoy(full[-1]["domestic"] + full[-1]["foreign"], full[-2]["domestic"] + full[-2]["foreign"]) if len(full) >= 2 else None
        by_district.append(
            {
                "key": dd["id"],
                "label": dd["name"],
                "arrivals": values,
                "registrations": [regs_by_district[dd["id"]].get(y, 0) for y in YEARS],
                "latest_full_year_yoy_pct": last_yoy,
            }
        )
    return _envelope(
        district,
        label="SYNTHETIC",
        years=YEARS,
        totals=totals,
        by_district=by_district,
        partial_year_note="The current year is partial (months to date); YoY is not computed for it.",
    )


# ------------------------------------------------------------------ registrations per month
def registrations_monthly(district: str | None, months: int = 24) -> dict:
    db = mongo.db()
    f = {"district": district} if district else {}
    today = date.today()
    keys = []
    y, m = today.year, today.month
    for _ in range(max(1, min(months, 60))):
        keys.append(f"{y:04d}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    keys.reverse()
    regs = Counter(b["registered_on"][:7] for b in db.businesses.find(f, {"registered_on": 1}))
    subs = Counter(mongo.aware(a["submitted_at"]).strftime("%Y-%m") for a in db.applications.find(f, {"submitted_at": 1}))
    return _envelope(
        district,
        months=keys,
        series=[
            {"key": "new_registrations", "label": "New registrations", "values": [regs.get(k, 0) for k in keys]},
            {"key": "applications_submitted", "label": "Applications submitted", "values": [subs.get(k, 0) for k in keys]},
        ],
    )


# ------------------------------------------------------------------ grievances
def grievance_stats(district: str | None) -> dict:
    f = {"district": district} if district else {}
    docs = [mongo.clean(g) for g in mongo.db().grievances.find(f)]
    pubs = [grievances.public(g) for g in docs]
    by_cat = Counter(g["category"] for g in docs)
    by_dist = Counter(g["district"] for g in docs)
    by_status = Counter(g["status"] for g in docs)
    breached = sum(1 for p in pubs if p["overdue"])
    res_days = [
        (mongo.aware(g["resolved_at"]) - mongo.aware(g["created_at"])).total_seconds() / 86400
        for g in docs
        if g.get("resolved_at") and g["status"] in ("resolved", "closed")
    ]
    return _envelope(
        district,
        total=len(docs),
        by_category=[{"key": k, "label": v, "count": by_cat.get(k, 0)} for k, v in catalog.GRIEVANCE_CATEGORIES.items()],
        by_district=[
            {"key": d["id"], "label": d["name"], "count": by_dist.get(d["id"], 0)}
            for d in DISTRICT_LIST
            if not district or d["id"] == district
        ],
        by_status=[{"key": s, "count": by_status.get(s, 0)} for s in catalog.GRIEVANCE_STATUSES],
        sla_days=catalog.GRIEVANCE_SLA_DAYS,
        sla_breach_rate_pct=round(100.0 * breached / len(docs), 1) if docs else None,
        sla_breached=breached,
        median_resolution_days=round(statistics.median(res_days), 1) if res_days else None,
        resolved_count=len(res_days),
    )


# ------------------------------------------------------------------ workforce (k-anonymity)
def workforce(district: str | None, group_by: str = "district") -> dict:
    if group_by not in ("district", "type"):
        group_by = "district"
    db = mongo.db()
    f = {"district": district} if district else {}
    months = sorted(db.workforce.distinct("month", f))
    if not months:
        return _envelope(district, k_min=K_MIN, group_by=group_by, month=None, groups=[], overall=None)
    # Latest COMPLETE month (the current month is still filling up from HOI ingest).
    current = date.today().strftime("%Y-%m")
    complete = [m for m in months if m < current] or months
    latest = complete[-1]
    window = complete[-12:]
    docs = [mongo.clean(x) for x in db.workforce.find({**f, "month": {"$in": window}})]
    labels = (
        {d["id"]: d["name"] for d in DISTRICT_LIST}
        if group_by == "district"
        else {t: catalog.BUSINESS_TYPES[t][0] for t in catalog.STAY_TYPES}
    )

    def summarise(rows: list[dict]) -> dict:
        cur = [r for r in rows if r["month"] == latest]
        contributors = {r["business_id"] for r in cur}
        if len(contributors) < K_MIN:
            return {
                "suppressed": True,
                "reason": f"Fewer than {K_MIN} businesses contribute to this group, so figures are hidden to protect privacy (k-anonymity).",
            }
        staff = sum(r["staff_count"] for r in cur)
        roles = Counter()
        for r in cur:
            roles.update(r.get("roles") or {})
        seps = sum(r.get("separations", 0) for r in rows)
        months_n = len({r["month"] for r in rows}) or 1
        avg_staff = sum(r["staff_count"] for r in rows) / months_n
        return {
            "suppressed": False,
            "businesses": len(contributors),
            "staff_total": staff,
            "roles": dict(roles),
            "flagged_share_pct": round(100.0 * sum(r.get("flagged", 0) for r in cur) / staff, 1) if staff else None,
            "turnover_pct_12m": round(100.0 * seps / avg_staff, 1) if avg_staff else None,
        }

    grouped: dict = defaultdict(list)
    for r in docs:
        grouped[r[group_by]].append(r)
    keys = [k for k in labels if not (group_by == "district" and district and k != district)]
    groups = [{"key": k, "label": labels[k], **summarise(grouped.get(k, []))} for k in keys]
    return _envelope(
        district,
        k_min=K_MIN,
        group_by=group_by,
        month=latest,
        months_in_turnover=len(window),
        source="HOI-connected stays (aggregated). Never per person or per business.",
        overall=summarise(docs),
        groups=groups,
    )
