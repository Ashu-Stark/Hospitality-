"""Inventory: catalog, multi-location stock, an append-only movement ledger, requisitions, purchase
orders with partial receipts, stock counts, wastage, and forecast-aware reorder suggestions.

Invariant: inv_stock always equals the sum of inv_moves per (item, location), and stock is never negative.
MongoDB is used without multi-document transactions, so every change goes through _move():
  1. apply the stock change with one atomic update; a decrement is conditional (`qty >= n` + `$inc`), so two
     concurrent issues can never take the same unit twice and stock can never go below zero;
  2. append the ledger move; if that insert fails, the stock change is reversed (compensating write).
Operations with several steps (transfer, requisition fulfilment, PO receipt, count posting) record an undo for
every step in a _Saga and roll the earlier steps back when a later one fails. Requisition and PO lines are
embedded in their parent document and reserved with conditional `$inc` before stock moves, so partial
receipts/issues can never exceed the ordered quantity even under concurrent requests.
"""

from __future__ import annotations

import logging
import math
import random
from datetime import UTC, datetime, timedelta

from pymongo import DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from .. import mongo
from . import tenants
from .errors import Invalid

log = logging.getLogger("hoi.platform.inventory")
EPS = 1e-9

MOVE_KINDS = {
    "receive": "Received (GRN)",
    "issue": "Issued",
    "transfer_out": "Transfer out",
    "transfer_in": "Transfer in",
    "adjust": "Count adjustment",
    "waste": "Wastage / damage",
    "return": "Returned",
    "opening": "Opening stock",
}
CATEGORIES = ["Linen", "Guest amenities", "Cleaning", "F&B dry store", "Maintenance spares"]


class InventoryError(Invalid):
    """Business-rule violation (negative stock, wrong status, ...). HTTP 422."""


def _since(since: str | datetime | None) -> datetime | None:
    if since is None or isinstance(since, datetime):
        return since
    return datetime.fromisoformat(since).astimezone(UTC)  # API strings are server-local time


# ------------------------------------------------------------------ reads
def items(tid: str) -> list[dict]:
    return mongo.find("inv_items", {"tenant_id": tid, "active": 1}, [("category", 1), ("name", 1)])


def locations(tid: str) -> list[dict]:
    return mongo.find("inv_locations", {"tenant_id": tid}, [("name", 1)])


def suppliers(tid: str) -> list[dict]:
    return mongo.find("inv_suppliers", {"tenant_id": tid}, [("name", 1)])


def stock(tid: str) -> dict[tuple[str, str], float]:
    rows = mongo.col("inv_stock").find({"tenant_id": tid}).sort([("item_id", 1), ("location_id", 1)])
    return {(r["item_id"], r["location_id"]): float(r["qty"]) for r in rows}


def on_hand(tid: str) -> dict[str, float]:
    rows = mongo.col("inv_stock").aggregate(
        [{"$match": {"tenant_id": tid}}, {"$group": {"_id": "$item_id", "q": {"$sum": "$qty"}}}, {"$sort": {"_id": 1}}]
    )
    return {r["_id"]: float(r["q"]) for r in rows}


def on_order(tid: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for p in mongo.col("inv_pos").find({"tenant_id": tid, "status": {"$in": ["approved", "sent", "partial"]}}, {"lines": 1}):
        for ln in p.get("lines") or []:
            out[ln["item_id"]] = out.get(ln["item_id"], 0.0) + ln["qty"] - ln["qty_received"]
    return {k: max(0.0, v) for k, v in out.items()}


def moves(tid: str, limit: int = 300, since: str | None = None) -> list[dict]:
    flt: dict = {"tenant_id": tid}
    if since:
        flt["at"] = {"$gte": _since(since)}
    return mongo.find("inv_moves", flt, [("id", DESCENDING)], limit)


DEPT_LABEL = {  # same words as the dashboard and the staff app
    "housekeeping": "Housekeeping",
    "fnb_service": "F&B service",
    "kitchen": "Kitchen",
    "front_office": "Front office",
    "maintenance": "Maintenance",
    "security": "Security",
}
TITLE_MAX_LINES = 3  # items named in a request title; the rest become "+N more"


def request_title(lines: list[tuple[str, float]], department: str | None, room: str | None = None) -> str:
    """Plain title for a stock request, e.g. "Towels ×2, Soap ×4 for Housekeeping · room 204" (no ids, no usernames)."""
    named = [f"{name} ×{qty:g}" for name, qty in lines[:TITLE_MAX_LINES]]
    if len(lines) > TITLE_MAX_LINES:
        named.append(f"+{len(lines) - TITLE_MAX_LINES} more")
    dept = DEPT_LABEL.get(str(department), str(department or "").replace("_", " ").capitalize())
    title = (", ".join(named) or "Stock request") + (f" for {dept}" if dept else "")
    return title + (f" · room {room}" if room else "")


def main_store(locs: list[dict]) -> str | None:
    """The hotel's main store: a location named "Main ...", else the first store, else the first location."""
    for pick in (lambda l: "main" in str(l.get("name", "")).casefold(), lambda l: l.get("kind") == "store", lambda l: True):
        hit = next((l["id"] for l in locs if pick(l)), None)
        if hit:
            return hit
    return None


def choose_source(need: dict[str, float], stock_map: dict[tuple[str, str], float], locs: list[dict]) -> str | None:
    """Where "Give all" should take from: a location that has enough of every item still owed (the main store first,
    then the one with the most of these items); when no single location has enough, the main store."""
    main = main_store(locs)
    need = {i: q for i, q in need.items() if q > EPS}
    if need:
        able = [l["id"] for l in locs if all(stock_map.get((i, l["id"]), 0.0) >= q - EPS for i, q in need.items())]
        if able:
            return main if main in able else max(able, key=lambda lid: sum(stock_map.get((i, lid), 0.0) for i in need))
    return main


def _req_out(r: dict, names: dict[str, str] | None = None) -> dict:
    out = mongo.clean(r)
    out["lines"] = [{"req_id": r["id"], **ln} for ln in r.get("lines") or []]
    if names is not None:
        named = [(names.get(ln["item_id"], "item"), float(ln["qty"])) for ln in out["lines"]]
        out["title"] = request_title(named, r.get("department"), r.get("room"))
    return out


def reqs(tid: str, status: tuple[str, ...] | None = None, requested_by: str | None = None) -> list[dict]:
    """Requests, newest first, each with a plain `title` and `give_from`: the location suggested for "Give all"."""
    flt: dict = {"tenant_id": tid}
    if status:
        flt["status"] = {"$in": list(status)}
    if requested_by:
        flt["requested_by"] = requested_by
    rows = list(mongo.col("inv_reqs").find(flt).sort([("created_at", DESCENDING), ("_id", DESCENDING)]))
    if not rows:
        return []
    names = {i["id"]: i.get("name") or "item" for i in mongo.col("inv_items").find({"tenant_id": tid}, {"id": 1, "name": 1})}
    stock_map, locs = stock(tid), locations(tid)
    out = []
    for r in rows:
        o = _req_out(r, names)
        need = {ln["item_id"]: float(ln["qty"]) - float(ln["qty_issued"]) for ln in r.get("lines") or []}
        o["give_from"] = choose_source(need, stock_map, locs)
        out.append(o)
    return out


def pos(tid: str) -> list[dict]:
    gst = {i["id"]: (i.get("gst_rate") or 0, i.get("hsn") or "") for i in mongo.col("inv_items").find({"tenant_id": tid})}
    inter = {s["id"]: bool(s.get("interstate")) for s in mongo.col("inv_suppliers").find({"tenant_id": tid})}
    rows = []
    for p in mongo.col("inv_pos").find({"tenant_id": tid}).sort([("created_at", DESCENDING), ("_id", DESCENDING)]):
        r = mongo.clean(p)
        r["lines"] = [{"po_id": p["id"], **ln} for ln in p.get("lines") or []]
        r["totals"] = po_totals(r["lines"], gst, inter.get(r["supplier_id"], False))
        rows.append(r)
    return rows


# ------------------------------------------------------------------ the one write path
class _Saga:
    """Undo log for multi-step writes without transactions: on an exception the recorded undos run in reverse order."""

    def __init__(self) -> None:
        self.undo: list = []

    def __enter__(self) -> _Saga:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            for fn in reversed(self.undo):
                try:
                    fn()
                except Exception:  # noqa: BLE001 - keep compensating the remaining steps; ledger_errors will show any drift
                    log.exception("inventory compensation step failed")
        return False


def _key(tid: str, item_id: str, loc_id: str) -> dict:
    return {"tenant_id": tid, "item_id": item_id, "location_id": loc_id}


def _apply_stock(tid: str, item_id: str, loc_id: str, qty: float, name: str) -> None:
    st = mongo.col("inv_stock")
    if qty < 0:  # conditional atomic decrement: never below zero
        if st.find_one_and_update({**_key(tid, item_id, loc_id), "qty": {"$gte": -qty - EPS}}, {"$inc": {"qty": qty}}) is None:
            cur = st.find_one(_key(tid, item_id, loc_id), {"qty": 1})
            have = float(cur["qty"]) if cur else 0.0
            raise InventoryError(f"Not enough {name} at this location: have {have:g}, need {-qty:g}.")
        return
    try:
        st.update_one(_key(tid, item_id, loc_id), {"$inc": {"qty": qty}}, upsert=True)
    except DuplicateKeyError:  # two first-ever receipts raced on the upsert: the row exists now
        st.update_one(_key(tid, item_id, loc_id), {"$inc": {"qty": qty}})


def _move(
    tid: str,
    item_id: str,
    loc_id: str,
    qty: float,
    kind: str,
    *,
    saga: _Saga | None = None,
    ref: str = "",
    reason: str = "",
    by: str = "",
    department: str | None = None,
    room: str | None = None,
    unit_cost: float | None = None,
    at: datetime | None = None,
) -> None:
    if qty == 0:
        return
    item = mongo.col("inv_items").find_one({"id": item_id, "tenant_id": tid}, {"name": 1, "unit_cost": 1})
    if not item:
        raise InventoryError("Unknown item for this hotel.")
    if not mongo.col("inv_locations").find_one({"id": loc_id, "tenant_id": tid}, {"id": 1}):
        raise InventoryError("Unknown location for this hotel.")
    qty = float(qty)
    _apply_stock(tid, item_id, loc_id, qty, item.get("name") or item_id)
    st = mongo.col("inv_stock")
    try:
        mid = mongo.next_id("inv_moves")
        mongo.col("inv_moves").insert_one(
            {
                "id": mid,
                "tenant_id": tid,
                "item_id": item_id,
                "location_id": loc_id,
                "qty": qty,
                "kind": kind,
                "ref": ref,
                "reason": reason,
                "department": department,
                "room": room,
                "unit_cost": float(item.get("unit_cost") or 0) if unit_cost is None else float(unit_cost),
                "by_user": by,
                "at": at or mongo.now(),
            }
        )
    except Exception:
        st.update_one(_key(tid, item_id, loc_id), {"$inc": {"qty": -qty}})  # compensate: ledger write failed
        raise
    if saga is not None:

        def undo(mid=mid, qty=qty) -> None:
            mongo.col("inv_moves").delete_one({"id": mid, "tenant_id": tid})
            st.update_one(_key(tid, item_id, loc_id), {"$inc": {"qty": -qty}})

        saga.undo.append(undo)


def issue(
    tid: str,
    item_id: str,
    loc_id: str,
    qty: float,
    by: str,
    department: str | None = None,
    room: str | None = None,
    ref: str = "",
    reason: str = "",
) -> None:
    _move(tid, item_id, loc_id, -abs(qty), "issue", ref=ref, reason=reason, by=by, department=department, room=room)


def receive(tid: str, item_id: str, loc_id: str, qty: float, by: str, ref: str = "", unit_cost: float | None = None) -> None:
    _move(tid, item_id, loc_id, abs(qty), "receive", ref=ref, by=by, unit_cost=unit_cost)


def transfer(tid: str, item_id: str, from_loc: str, to_loc: str, qty: float, by: str) -> None:
    if from_loc == to_loc:
        raise InventoryError("Pick two different locations.")
    if not mongo.col("inv_locations").find_one({"id": to_loc, "tenant_id": tid}, {"id": 1}):
        raise InventoryError("Unknown location for this hotel.")
    ref = mongo.new_id("trf")
    with _Saga() as saga:  # the decrement (which can fail) goes first; a failed transfer_in undoes it
        _move(tid, item_id, from_loc, -abs(qty), "transfer_out", saga=saga, ref=ref, by=by)
        _move(tid, item_id, to_loc, abs(qty), "transfer_in", saga=saga, ref=ref, by=by)


def waste(tid: str, item_id: str, loc_id: str, qty: float, reason: str, by: str) -> None:
    if not reason.strip():
        raise InventoryError("Give a reason for wastage.")
    _move(tid, item_id, loc_id, -abs(qty), "waste", reason=reason, by=by)


def _own_items(tid: str, ids) -> None:
    known = {r["id"] for r in mongo.col("inv_items").find({"tenant_id": tid}, {"id": 1})}
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise InventoryError(f"Unknown item(s) for this hotel: {unknown[:3]}")


def _require_location(tid: str, loc_id: str) -> None:
    if not mongo.col("inv_locations").find_one({"id": loc_id, "tenant_id": tid}, {"id": 1}):
        raise InventoryError("Unknown location for this hotel.")


# ------------------------------------------------------------------ requisitions
def request(
    tid: str,
    by: str,
    department: str,
    lines: dict[str, float],
    location_id: str | None = None,
    room: str | None = None,
    note: str = "",
    job_id: str | None = None,
) -> str:
    lines = {k: float(v) for k, v in lines.items() if v and v > 0}
    if not lines:
        raise InventoryError("Add at least one item.")
    _own_items(tid, lines)
    rid = mongo.new_id("req")
    mongo.col("inv_reqs").insert_one(  # header and lines in one document: written atomically
        {
            "id": rid,
            "tenant_id": tid,
            "requested_by": by,
            "department": department,
            "location_id": location_id,
            "status": "pending",
            "room": room,
            "job_id": job_id,
            "note": note,
            "created_at": mongo.now(),
            "decided_by": None,
            "decided_at": None,
            "lines": [{"item_id": i, "qty": q, "qty_issued": 0.0} for i, q in lines.items()],
        }
    )
    tenants.audit(tid, by, "inv.request", f"{rid} {len(lines)} lines")
    return rid


def _reserve_line(coll: str, tid: str, doc_id: str, statuses: list[str], item_id: str, field: str, ordered: float, q: float) -> bool:
    """Atomically add q to an embedded line's issued/received quantity unless that would exceed the ordered quantity."""
    res = mongo.col(coll).update_one(
        {
            "id": doc_id,
            "tenant_id": tid,
            "status": {"$in": statuses},
            "lines": {"$elemMatch": {"item_id": item_id, field: {"$lte": ordered - q + EPS}}},
        },
        {"$inc": {f"lines.$.{field}": q}},
    )
    return res.modified_count == 1


def _unreserve_line(coll: str, tid: str, doc_id: str, item_id: str, field: str, q: float) -> None:
    mongo.col(coll).update_one({"id": doc_id, "tenant_id": tid, "lines.item_id": item_id}, {"$inc": {f"lines.$.{field}": -q}})


def fulfil(tid: str, rid: str, issued: dict[str, float], from_loc: str, by: str) -> str:
    """Issue (fully or partly) against a requisition. Returns the new status."""
    r = mongo.col("inv_reqs").find_one({"id": rid, "tenant_id": tid})
    if not r or r["status"] not in ("pending", "partial"):
        raise InventoryError("This request is not open.")
    _require_location(tid, from_loc)
    with _Saga() as saga:
        for line in r["lines"]:
            q = min(float(issued.get(line["item_id"], 0)), line["qty"] - line["qty_issued"])
            if q > 0:
                if not _reserve_line("inv_reqs", tid, rid, ["pending", "partial"], line["item_id"], "qty_issued", line["qty"], q):
                    raise InventoryError("This request changed meanwhile. Refresh and try again.")
                saga.undo.append(lambda i=line["item_id"], q=q: _unreserve_line("inv_reqs", tid, rid, i, "qty_issued", q))
                _move(tid, line["item_id"], from_loc, -q, "issue", saga=saga, ref=rid, by=by, department=r["department"], room=r["room"])
        cur = mongo.col("inv_reqs").find_one({"id": rid, "tenant_id": tid}, {"lines": 1})
        left = sum(ln["qty"] - ln["qty_issued"] for ln in cur["lines"])
        any_issued = sum(ln["qty_issued"] for ln in cur["lines"])
        status = "issued" if left <= EPS else "partial" if any_issued > 0 else "pending"
        mongo.col("inv_reqs").update_one(
            {"id": rid, "tenant_id": tid}, {"$set": {"status": status, "decided_by": by, "decided_at": mongo.now()}}
        )
    tenants.audit(tid, by, "inv.issue", f"{rid} → {status}")
    return status


def reject(tid: str, rid: str, by: str, note: str) -> None:
    r = mongo.col("inv_reqs").find_one({"id": rid, "tenant_id": tid}, {"note": 1})
    if r:
        mongo.col("inv_reqs").update_one(
            {"id": rid, "tenant_id": tid},
            {
                "$set": {
                    "status": "rejected",
                    "decided_by": by,
                    "decided_at": mongo.now(),
                    "note": (r.get("note") or "") + f" | rejected: {note}",
                }
            },
        )
    tenants.audit(tid, by, "inv.reject", rid)


# ------------------------------------------------------------------ purchasing
def create_po(tid: str, supplier_id: str, lines: dict[str, float], by: str, note: str = "") -> str:
    lines = {k: float(v) for k, v in lines.items() if v and v > 0}
    if not lines:
        raise InventoryError("A purchase order needs at least one line.")
    _own_items(tid, lines)
    sup = mongo.col("inv_suppliers").find_one({"id": supplier_id, "tenant_id": tid}, {"lead_days": 1})
    if not sup:
        raise InventoryError("Unknown supplier for this hotel.")
    pid = mongo.new_id("po")
    cost = {i["id"]: i["unit_cost"] for i in items(tid)}
    lead = sup.get("lead_days", 3)
    mongo.col("inv_pos").insert_one(
        {
            "id": pid,
            "tenant_id": tid,
            "supplier_id": supplier_id,
            "status": "draft",
            "created_at": mongo.now(),
            "created_by": by,
            "approved_by": None,
            "expected_at": (datetime.now() + timedelta(days=lead)).date().isoformat(),
            "note": note,
            "lines": [{"item_id": i, "qty": q, "qty_received": 0.0, "unit_cost": float(cost.get(i, 0))} for i, q in lines.items()],
        }
    )
    tenants.audit(tid, by, "po.created", pid)
    return pid


def set_po_status(tid: str, pid: str, status: str, by: str) -> None:
    allowed = {"draft": {"approved", "cancelled"}, "approved": {"sent", "cancelled"}, "sent": {"cancelled"}, "partial": set()}
    cur = mongo.col("inv_pos").find_one({"id": pid, "tenant_id": tid}, {"status": 1})
    if not cur or status not in allowed.get(cur["status"], set()):
        raise InventoryError(f"Cannot move a {cur['status'] if cur else 'missing'} PO to {status}.")
    fields = {"status": status} | ({"approved_by": by} if status == "approved" else {})
    res = mongo.col("inv_pos").update_one({"id": pid, "tenant_id": tid, "status": cur["status"]}, {"$set": fields})
    if res.matched_count != 1:  # changed by someone else between the read and the write
        raise InventoryError(f"Cannot move a {cur['status']} PO to {status}.")
    tenants.audit(tid, by, f"po.{status}", pid)


def receive_po(tid: str, pid: str, received: dict[str, float], loc_id: str, by: str) -> str:
    receivable = ["approved", "sent", "partial"]
    po = mongo.col("inv_pos").find_one({"id": pid, "tenant_id": tid})
    if not po or po["status"] not in receivable:
        raise InventoryError("Only approved or sent POs can be received.")
    _require_location(tid, loc_id)
    with _Saga() as saga:
        for line in po["lines"]:
            q = min(float(received.get(line["item_id"], 0)), line["qty"] - line["qty_received"])
            if q > 0:
                if not _reserve_line("inv_pos", tid, pid, receivable, line["item_id"], "qty_received", line["qty"], q):
                    raise InventoryError("This purchase order changed meanwhile. Refresh and try again.")
                saga.undo.append(lambda i=line["item_id"], q=q: _unreserve_line("inv_pos", tid, pid, i, "qty_received", q))
                _move(tid, line["item_id"], loc_id, q, "receive", saga=saga, ref=pid, by=by, unit_cost=line["unit_cost"])
        cur = mongo.col("inv_pos").find_one({"id": pid, "tenant_id": tid}, {"lines": 1})
        left = sum(ln["qty"] - ln["qty_received"] for ln in cur["lines"])
        status = "received" if left <= EPS else "partial"
        mongo.col("inv_pos").update_one({"id": pid, "tenant_id": tid}, {"$set": {"status": status}})
    tenants.audit(tid, by, "po.received", f"{pid} → {status}")
    return status


# ------------------------------------------------------------------ counts
def start_count(tid: str, loc_id: str, by: str) -> str:
    cid = mongo.new_id("cnt")
    st_ = stock(tid)
    mongo.col("inv_counts").insert_one(
        {
            "id": cid,
            "tenant_id": tid,
            "location_id": loc_id,
            "status": "open",
            "created_at": mongo.now(),
            "by_user": by,
            "posted_at": None,
            "lines": [{"item_id": it["id"], "system_qty": float(st_.get((it["id"], loc_id), 0)), "counted_qty": None} for it in items(tid)],
        }
    )
    return cid


def _count_out(c: dict) -> dict:
    out = mongo.clean(c)
    out["lines"] = [{"count_id": c["id"], **ln} for ln in c.get("lines") or []]
    return out


def open_counts(tid: str) -> list[dict]:
    rows = mongo.col("inv_counts").find({"tenant_id": tid, "status": "open"}).sort([("created_at", DESCENDING), ("_id", DESCENDING)])
    return [_count_out(c) for c in rows]


def post_count(tid: str, cid: str, counted: dict[str, float], by: str) -> float:
    """Post variances as adjustments (against the system qty captured at count start). Returns the variance value in ₹."""
    counts = mongo.col("inv_counts")
    # Claim the count (open -> posting) so it can be posted only once, even by two concurrent requests.
    cnt = counts.find_one_and_update(
        {"id": cid, "tenant_id": tid, "status": "open"}, {"$set": {"status": "posting"}}, return_document=ReturnDocument.AFTER
    )
    if not cnt:
        raise InventoryError("Count is not open.")
    cost = {i["id"]: i["unit_cost"] for i in items(tid)}
    value = 0.0
    lines = [dict(ln) for ln in cnt["lines"]]
    with _Saga() as saga:
        saga.undo.append(lambda: counts.update_one({"id": cid, "tenant_id": tid}, {"$set": {"status": "open"}}))
        for line in lines:
            if line["item_id"] not in counted:
                continue
            var = float(counted[line["item_id"]]) - line["system_qty"]
            line["counted_qty"] = float(counted[line["item_id"]])
            if abs(var) > EPS:
                _move(tid, line["item_id"], cnt["location_id"], var, "adjust", saga=saga, ref=cid, reason="stock count", by=by)
                value += var * cost.get(line["item_id"], 0)
        counts.update_one({"id": cid, "tenant_id": tid}, {"$set": {"status": "posted", "posted_at": mongo.now(), "lines": lines}})
    tenants.audit(tid, by, "count.posted", f"{cid} variance ₹{value:,.0f}")
    return value


# ------------------------------------------------------------------ planning
def reorder_suggestions(tid: str, rooms: int, occ_next: list[float]) -> list[dict]:
    """Static par rule vs forecast-aware rule, side by side.

    static:   if on_hand <= reorder_point → order up to par
    forecast: usage over (7 + lead) days = per_occ_room × rooms × Σ forecast occupancy (days beyond the forecast reuse its mean),
              target = max(par, forecast usage), order = target − on_hand − on_order
    """
    oh, oo = on_hand(tid), on_order(tid)
    mean_occ = sum(occ_next) / len(occ_next) if occ_next else 0.7
    out = []
    for it in items(tid):
        have, coming = oh.get(it["id"], 0.0), oo.get(it["id"], 0.0)
        static = max(0.0, it["par"] - have - coming) if have <= it["reorder_point"] else 0.0
        horizon = 7 + int(it["lead_days"])
        occ = (occ_next + [mean_occ] * horizon)[:horizon]
        usage = it["per_occ_room"] * rooms * sum(occ)
        target = max(it["par"], usage) if it["per_occ_room"] else it["par"]
        fc = (
            max(0.0, target - have - coming)
            if (have <= it["reorder_point"] or (it["per_occ_room"] and have - usage < it["reorder_point"]))
            else 0.0
        )
        out.append(
            {
                **it,
                "on_hand": have,
                "on_order": coming,
                "forecast_usage": usage,
                "static_qty": math.ceil(static),
                "forecast_qty": math.ceil(fc),
                "low": have <= it["reorder_point"],
            }
        )
    return out


def consumption(tid: str, days: int = 28) -> list[dict]:
    since = mongo.now() - timedelta(days=days)
    names = {i["id"]: i for i in mongo.col("inv_items").find({"tenant_id": tid}, {"id": 1, "name": 1, "category": 1})}
    groups: dict[tuple, dict] = {}
    for m in mongo.col("inv_moves").find({"tenant_id": tid, "kind": "issue", "at": {"$gte": since}}):
        it = names.get(m["item_id"])
        if not it:
            continue
        d = mongo.iso(m["at"])[:10]  # server-local calendar day, as before
        g = groups.setdefault(
            (m["item_id"], m.get("department"), d),
            {
                "name": it["name"],
                "category": it["category"],
                "department": m.get("department"),
                "item_id": m["item_id"],
                "qty": 0.0,
                "value": 0.0,
                "d": d,
            },
        )
        g["qty"] += -m["qty"]
        g["value"] += -m["qty"] * (m.get("unit_cost") or 0)
    return [groups[k] for k in sorted(groups, key=lambda k: (k[0], k[1] is not None, k[1] or "", k[2]))]


def wastage_value(tid: str, days: int = 28) -> float:
    since = mongo.now() - timedelta(days=days)
    rows = mongo.col("inv_moves").find({"tenant_id": tid, "kind": "waste", "at": {"$gte": since}}, {"qty": 1, "unit_cost": 1})
    return float(sum(-r["qty"] * (r.get("unit_cost") or 0) for r in rows))


def stock_value(tid: str) -> float:
    cost = {i["id"]: i.get("unit_cost") or 0 for i in mongo.col("inv_items").find({"tenant_id": tid}, {"id": 1, "unit_cost": 1})}
    return float(sum(q * cost[i] for (i, _l), q in stock(tid).items() if i in cost))


def check_invariant(tid: str) -> list[str]:
    """Return any (item, location) where stock != sum of ledger. Empty list = consistent."""
    rows = mongo.col("inv_moves").aggregate(
        [{"$match": {"tenant_id": tid}}, {"$group": {"_id": {"i": "$item_id", "l": "$location_id"}, "q": {"$sum": "$qty"}}}]
    )
    led = {(r["_id"]["i"], r["_id"]["l"]): r["q"] for r in rows}
    bad = []
    for k, v in stock(tid).items():
        if abs(led.get(k, 0) - v) > 1e-6:
            bad.append(f"{k}: stock {v} vs ledger {led.get(k, 0)}")
    return bad


# ------------------------------------------------------------------ demo seed (synthetic)
SEED_ITEMS = [
    # sku, name, category, unit, cost ₹, par, reorder, supplier#, lead, per occupied room-night, department
    ("LIN-BT", "Bath towel", "Linen", "pc", 420, 180, 90, 0, 7, 0.0, "housekeeping"),
    ("LIN-HT", "Hand towel", "Linen", "pc", 160, 180, 90, 0, 7, 0.0, "housekeeping"),
    ("LIN-BS", "Bedsheet (double)", "Linen", "pc", 650, 140, 70, 0, 7, 0.0, "housekeeping"),
    ("LIN-PC", "Pillow cover", "Linen", "pc", 120, 280, 140, 0, 7, 0.0, "housekeeping"),
    ("AMN-SH", "Shampoo 30 ml", "Guest amenities", "pc", 9, 900, 400, 1, 4, 1.6, "housekeeping"),
    ("AMN-SP", "Soap 25 g", "Guest amenities", "pc", 7, 900, 400, 1, 4, 1.7, "housekeeping"),
    ("AMN-DK", "Dental kit", "Guest amenities", "pc", 11, 600, 250, 1, 4, 1.1, "housekeeping"),
    ("AMN-SL", "Slippers (pair)", "Guest amenities", "pair", 28, 300, 120, 1, 4, 0.55, "housekeeping"),
    ("AMN-TP", "Toilet roll", "Guest amenities", "roll", 18, 700, 300, 1, 4, 1.2, "housekeeping"),
    ("AMN-WB", "Mineral water 1 L", "Guest amenities", "bottle", 14, 900, 400, 2, 2, 2.0, "housekeeping"),
    ("CLN-FC", "Floor cleaner 5 L", "Cleaning", "can", 520, 24, 10, 1, 5, 0.012, "housekeeping"),
    ("CLN-GC", "Glass cleaner 500 ml", "Cleaning", "bottle", 140, 40, 15, 1, 5, 0.02, "housekeeping"),
    ("CLN-GB", "Garbage bags (roll of 30)", "Cleaning", "roll", 95, 60, 25, 1, 5, 0.03, "housekeeping"),
    ("FNB-TB", "Tea bags (box of 100)", "F&B dry store", "box", 210, 30, 12, 2, 3, 0.02, "fnb_service"),
    ("FNB-CF", "Coffee sachets (box of 50)", "F&B dry store", "box", 260, 24, 10, 2, 3, 0.018, "fnb_service"),
    ("FNB-SG", "Sugar sachets (box of 200)", "F&B dry store", "box", 180, 20, 8, 2, 3, 0.01, "fnb_service"),
    ("FNB-RC", "Basmati rice 25 kg", "F&B dry store", "bag", 2400, 8, 3, 2, 3, 0.004, "kitchen"),
    ("FNB-OL", "Cooking oil 15 L", "F&B dry store", "tin", 2350, 6, 2, 2, 3, 0.003, "kitchen"),
    ("MNT-BL", "LED bulb 9 W", "Maintenance spares", "pc", 85, 60, 20, 3, 5, 0.0, "maintenance"),
    ("MNT-AF", "AC filter", "Maintenance spares", "pc", 350, 20, 8, 3, 7, 0.0, "maintenance"),
    ("MNT-GE", "Geyser heating element", "Maintenance spares", "pc", 650, 6, 2, 3, 7, 0.0, "maintenance"),
    ("MNT-BA", "Batteries AA (pack of 4)", "Maintenance spares", "pack", 120, 30, 10, 3, 5, 0.0, "maintenance"),
]


SEED_ROOMS = 45  # SEED_ITEMS par / reorder levels are sized for this many rooms and scaled to the hotel


def seed_demo(tid: str, rooms: int = 24) -> None:
    """Four weeks of synthetic history. Built in memory and written with a few bulk inserts (fast against a remote cluster).
    Items are written last: they are the "already seeded" marker, so an interrupted seed is cleaned up and redone.
    Par and reorder levels scale with the room count (ASSUMED linear)."""
    d = mongo.db()
    if d.inv_items.count_documents({"tenant_id": tid}, limit=1):
        return
    for name in ("inv_suppliers", "inv_locations", "inv_stock", "inv_moves", "inv_reqs", "inv_pos", "inv_counts"):
        d[name].delete_many({"tenant_id": tid})  # leftovers of an interrupted seed (this tenant has no items yet)
    rng = random.Random(7)
    sup_docs = [
        {
            "id": mongo.new_id("sup"),
            "tenant_id": tid,
            "name": name,
            "lead_days": lead,
            "gstin": None,
            "interstate": int(name.startswith("Electrical")),
        }
        for name, lead in (
            ("Linen supplier (demo)", 7),
            ("Amenities & cleaning supplier (demo)", 4),
            ("Dry-goods wholesaler (demo)", 3),
            ("Electrical & spares supplier (demo)", 5),
        )
    ]
    sup_ids = [s["id"] for s in sup_docs]
    loc_docs = [
        {"id": mongo.new_id("loc"), "tenant_id": tid, "name": name, "kind": kind}
        for name, kind in (
            ("Main store", "store"),
            ("Housekeeping pantry (floor 2)", "pantry"),  # one pantry serves floors 1-3 (ASSUMED)
            ("Kitchen store", "store"),
            ("Maintenance store", "store"),
        )
    ]
    locs = {x["name"]: x["id"] for x in loc_docs}
    start = mongo.now() - timedelta(days=28)
    item_docs: list[dict] = []
    move_docs: list[dict] = []
    level: dict[tuple[str, str], float] = {}

    def mv(iid: str, cost: float, loc: str, qty: float, kind: str, at: datetime, **kw) -> None:
        if qty == 0:
            return
        level[(iid, loc)] = level.get((iid, loc), 0.0) + qty
        move_docs.append(
            {
                "id": 0,  # assigned from a reserved counter block below
                "tenant_id": tid,
                "item_id": iid,
                "location_id": loc,
                "qty": float(qty),
                "kind": kind,
                "ref": kw.get("ref", ""),
                "reason": kw.get("reason", ""),
                "department": kw.get("department"),
                "room": None,
                "unit_cost": float(cost),
                "by_user": "seed",
                "at": at,
            }
        )

    scale = rooms / SEED_ROOMS
    for sku, name, cat, unit, cost, par0, rop0, sup, lead, poc, dept in SEED_ITEMS:
        par, rop = max(2, round(par0 * scale)), max(1, round(rop0 * scale))
        iid = mongo.new_id("itm")
        hsn, rate = DEMO_GST.get(sku) or DEMO_GST.get(sku.split("-")[0], ("", 0))
        item_docs.append(_item_doc(iid, tid, sku, name, cat, unit, cost, par, rop, sup_ids[sup], lead, poc, dept, hsn or None, rate))
        home = locs["Kitchen store"] if dept == "kitchen" else locs["Maintenance store"] if dept == "maintenance" else locs["Main store"]
        mv(iid, cost, home, par * rng.uniform(1.05, 1.5), "opening", start)
        if cat in ("Guest amenities", "Cleaning"):
            mv(iid, cost, home, -par * 0.15, "transfer_out", start, ref="seed")
            mv(iid, cost, locs["Housekeeping pantry (floor 2)"], par * 0.15, "transfer_in", start, ref="seed")
        for day in range(28):  # four weeks of synthetic consumption
            occ = 0.68 + 0.15 * ((start + timedelta(days=day)).weekday() >= 5) + rng.uniform(-0.06, 0.06)
            use = poc * rooms * occ if poc else (rng.random() < 0.15) * rng.randint(1, 2)
            cur = level[(iid, home)]
            if cur < rop and day < 25:  # synthetic weekly-style restock so the history looks like a running hotel
                mv(iid, cost, home, par, "receive", start + timedelta(days=day, hours=8), ref="seed-grn")
                cur += par
            use = min(round(use), max(0, int(cur) - 1))
            if use > 0:
                mv(iid, cost, home, -use, "issue", start + timedelta(days=day, hours=10), department=dept)
        if sku in ("CLN-GC", "AMN-WB"):
            mv(iid, cost, home, -3, "waste", start + timedelta(days=20), reason="damaged in transit")
    first = mongo.next_id("inv_moves", len(move_docs))  # reserve a block of ledger ids
    for k, m in enumerate(move_docs):
        m["id"] = first + k
    d.inv_suppliers.insert_many(sup_docs)
    d.inv_locations.insert_many(loc_docs)
    d.inv_moves.insert_many(move_docs)
    d.inv_stock.insert_many([{"tenant_id": tid, "item_id": i, "location_id": loc, "qty": q} for (i, loc), q in level.items()])
    d.inv_items.insert_many(item_docs)
    ids = {r["sku"]: r["id"] for r in item_docs}
    request(
        tid,
        "HS05",
        "housekeeping",
        {ids["AMN-SH"]: 40, ids["AMN-SP"]: 40, ids["AMN-TP"]: 24},
        locs["Housekeeping pantry (floor 2)"],
        room=None,
        note="Floor 2 pantry top-up",
    )
    request(tid, "demo.housekeeping", "maintenance", {ids["MNT-BL"]: 6, ids["MNT-AF"]: 2}, None, room="204", note="Room 204 AC service")
    po = create_po(tid, sup_ids[0], {ids["LIN-BT"]: 30, ids["LIN-BS"]: 20}, "demo.store", "Winter-peak linen top-up")
    set_po_status(tid, po, "approved", "demo.owner")
    set_po_status(tid, po, "sent", "demo.store")


# HSN codes and GST rates as configured for the demo: placeholders to confirm with the hotel's accountant.
DEMO_GST = {
    "LIN": ("6302", 12),
    "AMN-SH": ("3305", 18),
    "AMN-SP": ("3401", 18),
    "AMN-DK": ("9603", 18),
    "AMN-SL": ("6402", 12),
    "AMN-TP": ("4818", 18),
    "AMN-WB": ("2201", 18),
    "CLN": ("3402", 18),
    "CLN-GB": ("3923", 18),
    "FNB-TB": ("0902", 5),
    "FNB-CF": ("2101", 18),
    "FNB-SG": ("1701", 5),
    "FNB-RC": ("1006", 5),
    "FNB-OL": ("1512", 5),
    "MNT": ("8539", 18),
    "MNT-AF": ("8421", 18),
    "MNT-GE": ("8516", 18),
    "MNT-BA": ("8506", 18),
}


# ------------------------------------------------------------------ GST
def po_totals(lines: list[dict], gst: dict[str, tuple[float, str]], interstate: bool) -> dict:
    """Taxable value and GST split: CGST+SGST for an intra-state supplier, IGST for inter-state. Rates come from the
    item catalog (set them with your accountant; HOI does not give tax advice)."""
    taxable = tax = 0.0
    out_lines = []
    for ln in lines:
        rate, hsn = gst.get(ln["item_id"], (0.0, ""))
        value = ln["qty"] * ln["unit_cost"]
        t = value * rate / 100
        taxable += value
        tax += t
        out_lines.append({"item_id": ln["item_id"], "hsn": hsn, "gst_rate": rate, "taxable": round(value, 2), "tax": round(t, 2)})
    half = round(tax / 2, 2)
    return {
        "taxable": round(taxable, 2),
        "cgst": 0.0 if interstate else half,
        "sgst": 0.0 if interstate else round(tax - half, 2),
        "igst": round(tax, 2) if interstate else 0.0,
        "total": round(taxable + tax, 2),
        "interstate": interstate,
        "lines": out_lines,
    }


# ------------------------------------------------------------------ catalog
def _item_doc(
    iid: str,
    tid: str,
    sku: str,
    name: str,
    category: str,
    unit: str,
    unit_cost: float,
    par: float,
    reorder_point: float,
    supplier_id: str | None,
    lead_days: int,
    per_occ_room: float,
    department: str | None,
    hsn: str | None,
    gst_rate: float,
) -> dict:
    return {
        "id": iid,
        "tenant_id": tid,
        "sku": sku,
        "_sku_lc": sku.lower(),
        "name": name,
        "category": category,
        "unit": unit,
        "unit_cost": float(unit_cost),
        "par": float(par),
        "reorder_point": float(reorder_point),
        "supplier_id": supplier_id,
        "lead_days": int(lead_days),
        "per_occ_room": float(per_occ_room),
        "department": department,
        "active": 1,
        "hsn": hsn,
        "gst_rate": float(gst_rate),
    }


def add_item(
    tid: str,
    sku: str,
    name: str,
    category: str,
    unit: str,
    unit_cost: float,
    par: float,
    reorder_point: float,
    supplier_id: str | None,
    per_occ_room: float = 0.0,
    department: str | None = None,
    hsn: str | None = None,
    gst_rate: float = 0.0,
    by: str = "",
) -> dict:
    if gst_rate not in (0, 0.25, 3, 5, 12, 18, 28, 40):
        raise InventoryError("GST rate must be one of the GST slabs (0, 0.25, 3, 5, 12, 18, 28, 40).")
    if not sku.strip() or not name.strip():
        raise InventoryError("SKU and name are required.")
    if mongo.col("inv_items").find_one({"tenant_id": tid, "_sku_lc": sku.strip().lower()}, {"id": 1}):
        raise InventoryError(f"SKU {sku} already exists.")
    if reorder_point > par:
        raise InventoryError("Reorder point should be at or below the par level.")
    lead = 3
    if supplier_id:
        sup = mongo.col("inv_suppliers").find_one({"id": supplier_id, "tenant_id": tid}, {"lead_days": 1})
        if not sup:
            raise InventoryError("Unknown supplier for this hotel.")
        lead = sup["lead_days"]
    doc = _item_doc(
        mongo.new_id("itm"),
        tid,
        sku.strip(),
        name.strip(),
        category,
        unit,
        unit_cost,
        par,
        reorder_point,
        supplier_id,
        lead,
        per_occ_room,
        department,
        (hsn or "").strip() or None,
        gst_rate,
    )
    try:
        mongo.col("inv_items").insert_one(doc)  # unique (tenant_id, sku lower-case)
    except DuplicateKeyError:
        raise InventoryError(f"SKU {sku} already exists.") from None
    tenants.audit(tid, by, "inv.item_added", sku)
    return mongo.clean(doc)


def add_location(tid: str, name: str, kind: str = "store") -> dict:
    if not name.strip():
        raise InventoryError("Location name is required.")
    doc = {"id": mongo.new_id("loc"), "tenant_id": tid, "name": name.strip(), "kind": kind}
    mongo.col("inv_locations").insert_one(doc)
    return mongo.clean(doc)


GSTIN_RE = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"


def add_supplier(tid: str, name: str, lead_days: int = 3, gstin: str | None = None, interstate: bool = False) -> dict:
    import re

    if not name.strip() or lead_days < 0:
        raise InventoryError("Supplier needs a name and a non-negative lead time.")
    gstin = (gstin or "").strip().upper() or None
    if gstin and not re.match(GSTIN_RE, gstin):
        raise InventoryError("GSTIN format looks wrong (15 characters, e.g. 05ABCDE1234F1Z5).")
    doc = {
        "id": mongo.new_id("sup"),
        "tenant_id": tid,
        "name": name.strip(),
        "lead_days": int(lead_days),
        "gstin": gstin,
        "interstate": int(interstate),
    }
    mongo.col("inv_suppliers").insert_one(doc)
    return mongo.clean(doc)
