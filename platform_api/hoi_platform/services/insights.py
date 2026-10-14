"""Super-admin insights (docs/HOSPITALITY_SUITE.md section 5): per hotel group (tenant) and property, plus portfolio totals.

Aggregates are MongoDB queries (count_documents / aggregate with $match + $group); medians are taken in Python over
values projected by the database, because $median/$percentile need MongoDB 7 and mongomock lacks them.
Jobs and requests carry no property id, so job/request figures are per tenant (a tenant's properties are listed with
their own room counts). The average worker performance score is suppressed when fewer than K_MIN workers have a score
(k-anonymity: a small team's average would reveal individuals). All demo data is SYNTHETIC.
"""

from __future__ import annotations

from datetime import UTC, timedelta
from statistics import median

from .. import mongo
from . import performance, tenants

K_MIN = 5
TARGET_SWITCH = {
    "$switch": {
        "branches": [{"case": {"$eq": ["$urgency", u]}, "then": m} for u, m in performance.TARGET_MINUTES.items()],
        "default": performance.TARGET_MINUTES["medium"],
    }
}


def _jobs(tid: str, since) -> dict:  # noqa: ANN001
    c = mongo.col("jobs")
    total = c.count_documents({"tenant_id": tid, "created_at": {"$gte": since}})
    rows = list(
        c.aggregate(
            [
                {"$match": {"tenant_id": tid, "status": "done", "done_at": {"$gte": since}, "accepted_at": {"$ne": None}}},
                {
                    "$project": {
                        "mins": {"$divide": [{"$subtract": ["$done_at", "$accepted_at"]}, 60000]},
                        "target": {"$ifNull": ["$target_minutes", TARGET_SWITCH]},
                    }
                },
                {"$project": {"mins": 1, "on_time": {"$cond": [{"$lte": ["$mins", "$target"]}, 1, 0]}}},
                {"$group": {"_id": None, "n": {"$sum": 1}, "on_time": {"$sum": "$on_time"}, "mins": {"$push": "$mins"}}},
            ]
        )
    )
    g = rows[0] if rows else {"n": 0, "on_time": 0, "mins": []}
    return {
        "count": total,
        "done": g["n"],
        "on_time_pct": round(100 * g["on_time"] / g["n"], 1) if g["n"] else None,
        "median_completion_min": round(median(g["mins"]), 1) if g["mins"] else None,
    }


def _guest_requests(tid: str, since) -> dict:  # noqa: ANN001
    rows = list(
        mongo.col("jobs").aggregate(
            [
                {"$match": {"tenant_id": tid, "kind": "guest", "created_at": {"$gte": since}}},
                {
                    "$project": {
                        "wait": {
                            "$cond": [
                                {"$ifNull": ["$accepted_at", False]},
                                {"$divide": [{"$subtract": ["$accepted_at", "$created_at"]}, 60000]},
                                None,
                            ]
                        }
                    }
                },
                {"$group": {"_id": None, "n": {"$sum": 1}, "waits": {"$push": "$wait"}}},
            ]
        )
    )
    g = rows[0] if rows else {"n": 0, "waits": []}
    waits = [w for w in g["waits"] if w is not None]
    return {"count": g["n"], "median_response_min": round(median(waits), 1) if waits else None}


def _feedback(tid: str, since) -> dict:  # noqa: ANN001
    flt = {"tenant_id": tid, "created_at": {"$gte": since}}
    g = list(
        mongo.col("guest_feedback").aggregate([{"$match": flt}, {"$group": {"_id": None, "n": {"$sum": 1}, "avg": {"$avg": "$rating"}}}])
    )
    last = (
        mongo.col("guest_feedback")
        .find({**flt, "comment": {"$nin": ["", None]}}, {"comment": 1, "rating": 1, "date": 1})
        .sort([("created_at", -1), ("_id", -1)])
        .limit(5)
    )
    by_day = mongo.col("guest_feedback").aggregate(
        [{"$match": flt}, {"$group": {"_id": "$date", "n": {"$sum": 1}, "avg": {"$avg": "$rating"}}}, {"$sort": {"_id": 1}}]
    )
    n = g[0]["n"] if g else 0
    return {
        "count": n,
        "average": round(g[0]["avg"], 2) if n else None,
        "last_comments": [{"rating": d["rating"], "comment": d["comment"][:140], "date": d.get("date")} for d in last],
        "by_day": [{"date": b["_id"], "count": b["n"], "average": round(b["avg"], 2)} for b in by_day],
    }


def _checkouts(tid: str, since) -> dict:  # noqa: ANN001
    flt = {"tenant_id": tid, "created_at": {"$gte": since}}
    late = {
        r["_id"]: r["n"] for r in mongo.col("late_checkouts").aggregate([{"$match": flt}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}])
    }
    return {
        "express": mongo.col("guest_checkouts").count_documents({**flt, "status": {"$ne": "cancelled"}}),
        "late_requested": sum(late.values()),
        "late_approved": late.get("approved", 0),
        "late_pending": late.get("pending", 0),
    }


def _inventory(tid: str) -> dict:
    value = list(
        mongo.col("inv_stock").aggregate(
            [
                {"$match": {"tenant_id": tid}},
                {"$lookup": {"from": "inv_items", "localField": "item_id", "foreignField": "id", "as": "it"}},
                {"$unwind": "$it"},
                {"$match": {"it.tenant_id": tid}},
                {"$group": {"_id": None, "v": {"$sum": {"$multiply": ["$qty", "$it.unit_cost"]}}}},
            ]
        )
    )
    per_item = mongo.col("inv_stock").aggregate([{"$match": {"tenant_id": tid}}, {"$group": {"_id": "$item_id", "q": {"$sum": "$qty"}}}])
    have = {r["_id"]: r["q"] for r in per_item}
    below = sum(
        1
        for it in mongo.col("inv_items").find({"tenant_id": tid}, {"id": 1, "reorder_point": 1})
        if have.get(it["id"], 0) <= (it.get("reorder_point") or 0)
    )
    return {"stock_value": round(value[0]["v"], 2) if value else 0.0, "items_below_reorder": below}


def _performance(tid: str, days: int) -> dict:
    try:
        rows = performance.compute(tid, min(max(days, 1), 90))["workers"]
    except Exception:  # noqa: BLE001 - insights must not fail because one tenant's data is odd
        rows = []
    scores = [w["score"] for w in rows if w.get("status") == "ok" and w.get("score") is not None]
    if len(scores) < K_MIN:
        return {
            "workers_scored": len(scores),
            "average_score": None,
            "suppressed": True,
            "reason": f"fewer than {K_MIN} workers with a score",
        }
    return {"workers_scored": len(scores), "average_score": round(sum(scores) / len(scores), 1), "suppressed": False}


def _last_activity(tid: str) -> str | None:
    d = mongo.col("audit_log").find_one({"tenant_id": tid}, {"at": 1}, sort=[("id", -1)])
    return mongo.iso(d["at"]) if d else None


def _requests_per_day(tid: str, since) -> list[dict]:  # noqa: ANN001
    rows = mongo.col("jobs").aggregate(
        [
            {"$match": {"tenant_id": tid, "kind": "guest", "created_at": {"$gte": since}}},
            {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}}, "n": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
        ]
    )
    return [{"date": r["_id"], "count": r["n"]} for r in rows]


def hotel(t: dict, days: int) -> dict:
    tid = t["id"]
    since = mongo.now() - timedelta(days=days)
    rooms = {
        r["_id"]: r
        for r in mongo.col("rooms").aggregate(
            [
                {"$match": {"tenant_id": tid}},
                {"$group": {"_id": "$property_id", "n": {"$sum": 1}, "occ": {"$sum": {"$cond": [{"$eq": ["$status", "occupied"]}, 1, 0]}}}},
            ]
        )
    }
    props = tenants.properties(tid)
    unassigned = rooms.get(None, {"n": 0, "occ": 0})
    prop_rows = []
    for i, p in enumerate(props):
        r = rooms.get(p["id"], {"n": 0, "occ": 0})
        n, occ = r["n"], r["occ"]
        if i == 0:  # rooms created without a property belong to the first property
            n, occ = n + unassigned["n"], occ + unassigned["occ"]
        prop_rows.append({"id": p["id"], "name": p["name"], "region": p.get("region"), "rooms": n, "occupied_now": occ})
    total_rooms = sum(r["n"] for r in rooms.values())
    occupied = sum(r["occ"] for r in rooms.values())
    return {
        "tenant_id": tid,
        "name": t["name"],
        "plan": t["plan"],
        "status": t["status"],
        "is_demo": t["is_demo"],
        "properties": prop_rows,
        "rooms": total_rooms,
        "occupied_now": occupied,
        "occupancy_pct": round(100 * occupied / total_rooms, 1) if total_rooms else None,
        "staff": mongo.col("staff").count_documents({"tenant_id": tid}),
        "active_users": mongo.col("users").count_documents({"tenant_id": tid, "active": 1, "last_login": {"$gte": since}}),
        "jobs": _jobs(tid, since),
        "guest_requests": _guest_requests(tid, since),
        "requests_per_day": _requests_per_day(tid, since),
        "checkouts": _checkouts(tid, since),
        "feedback": _feedback(tid, since),
        "inventory": _inventory(tid),
        "performance": _performance(tid, days),
        "last_activity": _last_activity(tid),
    }


def compute(days: int = 30) -> dict:
    hotels = [hotel(t, days) for t in tenants.list_tenants()]
    fb_n = sum(h["feedback"]["count"] for h in hotels)
    fb_sum = sum((h["feedback"]["average"] or 0) * h["feedback"]["count"] for h in hotels)
    totals = {
        "hotels": len(hotels),
        "active_hotels": sum(1 for h in hotels if h["status"] == "active"),
        "properties": sum(len(h["properties"]) for h in hotels),
        "rooms": sum(h["rooms"] for h in hotels),
        "occupied_now": sum(h["occupied_now"] for h in hotels),
        "staff": sum(h["staff"] for h in hotels),
        "active_users": sum(h["active_users"] for h in hotels),
        "jobs": sum(h["jobs"]["count"] for h in hotels),
        "guest_requests": sum(h["guest_requests"]["count"] for h in hotels),
        "express_checkouts": sum(h["checkouts"]["express"] for h in hotels),
        "late_checkouts": sum(h["checkouts"]["late_requested"] for h in hotels),
        "feedback": fb_n,
        "feedback_average": round(fb_sum / fb_n, 2) if fb_n else None,
        "stock_value": round(sum(h["inventory"]["stock_value"] for h in hotels), 2),
    }
    return {
        "days": days,
        "generated_at": mongo.iso(mongo.now().astimezone(UTC)),
        "k_min_workers": K_MIN,
        "totals": totals,
        "hotels": hotels,
        "note": "SYNTHETIC demo data. Performance averages are hidden for teams with fewer than 5 scored workers.",
    }
