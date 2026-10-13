"""Inventory: catalog, stock, ledger, requisitions, purchasing, counts, planning and analytics."""

import html

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from ..deps import INVENTORY_MANAGERS, Principal, roles, tenant_of
from ..schemas import (
    CountPostIn,
    CountStartIn,
    FulfilIn,
    ItemIn,
    LocationIn,
    MoveIn,
    POIn,
    POStatusIn,
    ReceiveIn,
    RejectIn,
    RequestIn,
    SupplierIn,
    TransferIn,
)
from ..services import inventory as inv

router = APIRouter(prefix="/inventory", tags=["inventory"])
VIEW = ("owner", "dept_head", "storekeeper")


def _by(p: Principal) -> str:
    return p.employee_id if p.role == "worker" and p.employee_id else p.username


# ------------------------------------------------------------------ catalog
@router.get("/items")
def items(p: Principal = Depends(roles(*VIEW, "worker"))) -> list[dict]:
    return inv.items(tenant_of(p))


@router.get("/locations")
def locations(p: Principal = Depends(roles(*VIEW))) -> list[dict]:
    return inv.locations(tenant_of(p))


@router.get("/suppliers")
def suppliers(p: Principal = Depends(roles(*VIEW))) -> list[dict]:
    return inv.suppliers(tenant_of(p))


@router.post("/items", status_code=201)
def add_item(body: ItemIn, p: Principal = Depends(roles(*INVENTORY_MANAGERS))) -> dict:
    return inv.add_item(tenant_of(p), **body.model_dump(), by=p.username)


@router.post("/locations", status_code=201)
def add_location(body: LocationIn, p: Principal = Depends(roles(*INVENTORY_MANAGERS))) -> dict:
    return inv.add_location(tenant_of(p), body.name, body.kind)


@router.post("/suppliers", status_code=201)
def add_supplier(body: SupplierIn, p: Principal = Depends(roles(*INVENTORY_MANAGERS))) -> dict:
    return inv.add_supplier(tenant_of(p), body.name, body.lead_days, body.gstin, body.interstate)


# ------------------------------------------------------------------ stock & ledger
@router.get("/stock")
def stock(p: Principal = Depends(roles(*VIEW))) -> dict:
    tid = tenant_of(p)
    return {
        "stock": [{"item_id": i, "location_id": l, "qty": q} for (i, l), q in inv.stock(tid).items()],
        "on_hand": inv.on_hand(tid),
        "on_order": inv.on_order(tid),
        "value": inv.stock_value(tid),
    }


@router.get("/moves")
def moves(limit: int = 400, p: Principal = Depends(roles(*VIEW))) -> list[dict]:
    return inv.moves(tenant_of(p), min(limit, 5000))


@router.post("/receive", status_code=201)
def receive(body: MoveIn, p: Principal = Depends(roles(*INVENTORY_MANAGERS))) -> dict:
    inv.receive(tenant_of(p), body.item_id, body.location_id, body.qty, p.username, body.ref)
    return {"ok": True}


@router.post("/issue", status_code=201)
def issue(body: MoveIn, p: Principal = Depends(roles(*INVENTORY_MANAGERS))) -> dict:
    inv.issue(tenant_of(p), body.item_id, body.location_id, body.qty, p.username, body.department, body.room, body.ref, body.reason)
    return {"ok": True}


@router.post("/waste", status_code=201)
def waste(body: MoveIn, p: Principal = Depends(roles(*INVENTORY_MANAGERS))) -> dict:
    inv.waste(tenant_of(p), body.item_id, body.location_id, body.qty, body.reason, p.username)
    return {"ok": True}


@router.post("/transfer", status_code=201)
def transfer(body: TransferIn, p: Principal = Depends(roles(*INVENTORY_MANAGERS))) -> dict:
    inv.transfer(tenant_of(p), body.item_id, body.from_location, body.to_location, body.qty, p.username)
    return {"ok": True}


# ------------------------------------------------------------------ requisitions
@router.get("/requests")
def requests_(status: str | None = None, p: Principal = Depends(roles(*VIEW, "worker"))) -> list[dict]:
    tid = tenant_of(p)
    st = tuple(status.split(",")) if status else None
    return inv.reqs(tid, st, requested_by=_by(p) if p.role == "worker" else None)


@router.post("/requests", status_code=201)
def create_request(body: RequestIn, p: Principal = Depends(roles(*VIEW, "worker"))) -> dict:
    rid = inv.request(tenant_of(p), _by(p), body.department, body.lines, body.location_id, body.room, body.note, body.job_id)
    return {"id": rid}


@router.post("/requests/{rid}/fulfil")
def fulfil(rid: str, body: FulfilIn, p: Principal = Depends(roles(*INVENTORY_MANAGERS))) -> dict:
    return {"status": inv.fulfil(tenant_of(p), rid, body.issued, body.from_location, p.username)}


@router.post("/requests/{rid}/reject")
def reject(rid: str, body: RejectIn, p: Principal = Depends(roles(*INVENTORY_MANAGERS))) -> dict:
    inv.reject(tenant_of(p), rid, p.username, body.note)
    return {"status": "rejected"}


# ------------------------------------------------------------------ purchasing
@router.get("/pos")
def pos(p: Principal = Depends(roles(*VIEW))) -> list[dict]:
    return inv.pos(tenant_of(p))


@router.post("/pos", status_code=201)
def create_po(body: POIn, p: Principal = Depends(roles(*INVENTORY_MANAGERS))) -> dict:
    return {"id": inv.create_po(tenant_of(p), body.supplier_id, body.lines, p.username, body.note)}


@router.post("/pos/{pid}/status")
def po_status(pid: str, body: POStatusIn, p: Principal = Depends(roles(*INVENTORY_MANAGERS))) -> dict:
    inv.set_po_status(tenant_of(p), pid, body.status, p.username)
    return {"status": body.status}


@router.get("/pos/{pid}/document", response_class=HTMLResponse)
def po_document(pid: str, p: Principal = Depends(roles(*VIEW))) -> str:
    """Printable purchase order with HSN and GST split (open in a browser, print or save as PDF)."""
    tid = tenant_of(p)
    po = next((x for x in inv.pos(tid) if x["id"] == pid), None)
    if not po:
        raise inv.InventoryError("Purchase order not found.")
    from ..services import tenants

    t = tenants.get_tenant(tid)
    items = {i["id"]: i for i in inv.items(tid)}
    sup = next((s for s in inv.suppliers(tid) if s["id"] == po["supplier_id"]), {})
    e = html.escape
    tot = po["totals"]
    rows = "".join(
        f"<tr><td>{e(items.get(ln['item_id'], {}).get('name', ln['item_id']))}</td><td>{e(tl['hsn'])}</td><td>{ln['qty']:g}</td>"
        f"<td>{ln['unit_cost']:,.2f}</td><td>{tl['taxable']:,.2f}</td><td>{tl['gst_rate']:g}%</td><td>{tl['tax']:,.2f}</td></tr>"
        for ln, tl in zip(po["lines"], tot["lines"])
    )
    split = (
        f"<tr><td colspan=6>IGST</td><td>{tot['igst']:,.2f}</td></tr>"
        if tot["interstate"]
        else f"<tr><td colspan=6>CGST</td><td>{tot['cgst']:,.2f}</td></tr><tr><td colspan=6>SGST</td><td>{tot['sgst']:,.2f}</td></tr>"
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>PO {e(pid)}</title>
<style>body{{font-family:system-ui,sans-serif;margin:32px;color:#0b0b0b}}table{{width:100%;border-collapse:collapse;margin-top:16px}}
td,th{{border-bottom:1px solid #ddd;padding:8px;text-align:left;font-size:14px}}th{{background:#0b0b0b;color:#fff}}
.tot td{{font-weight:600}}.muted{{color:#777;font-size:12px}}</style></head><body>
<h2>Purchase order {e(pid)}</h2><div>{e(t["name"])} · status {e(po["status"])} · created {e(po["created_at"][:10])} · expected {e(po.get("expected_at") or "-")}</div>
<div>Supplier: <b>{e(sup.get("name", "-"))}</b> · GSTIN {e(sup.get("gstin") or "not recorded")} · {"inter-state (IGST)" if tot["interstate"] else "intra-state (CGST + SGST)"}</div>
<table><tr><th>Item</th><th>HSN</th><th>Qty</th><th>Rate ₹</th><th>Taxable ₹</th><th>GST</th><th>Tax ₹</th></tr>{rows}
<tr class=tot><td colspan=6>Taxable value</td><td>{tot["taxable"]:,.2f}</td></tr>{split}
<tr class=tot><td colspan=6>Total</td><td>{tot["total"]:,.2f}</td></tr></table>
<p class=muted>GST rates and HSN codes come from the item catalog as configured by the hotel. Confirm them with your accountant;
this document is not a tax invoice.</p></body></html>"""


@router.post("/pos/{pid}/receive")
def po_receive(pid: str, body: ReceiveIn, p: Principal = Depends(roles(*INVENTORY_MANAGERS))) -> dict:
    return {"status": inv.receive_po(tenant_of(p), pid, body.received, body.location_id, p.username)}


# ------------------------------------------------------------------ counts
@router.get("/counts")
def counts(p: Principal = Depends(roles(*VIEW))) -> list[dict]:
    return inv.open_counts(tenant_of(p))


@router.post("/counts", status_code=201)
def start_count(body: CountStartIn, p: Principal = Depends(roles(*INVENTORY_MANAGERS))) -> dict:
    tid = tenant_of(p)
    if body.location_id not in {l["id"] for l in inv.locations(tid)}:
        raise inv.InventoryError("Unknown location for this hotel.")
    return {"id": inv.start_count(tid, body.location_id, p.username)}


@router.post("/counts/{cid}/post")
def post_count(cid: str, body: CountPostIn, p: Principal = Depends(roles(*INVENTORY_MANAGERS))) -> dict:
    return {"variance_value": inv.post_count(tenant_of(p), cid, body.counted, p.username)}


# ------------------------------------------------------------------ planning & analytics
@router.get("/suggestions")
def suggestions(rooms: int = 45, occ: str = "", p: Principal = Depends(roles(*VIEW))) -> list[dict]:
    """occ: comma-separated forecast occupancy (0-1) for the next days, from the forecast service."""
    occ_list = [min(1.0, max(0.0, float(x))) for x in occ.split(",") if x.strip()]
    return inv.reorder_suggestions(tenant_of(p), max(1, rooms), occ_list)


@router.get("/analytics")
def analytics(days: int = 28, p: Principal = Depends(roles(*VIEW))) -> dict:
    tid = tenant_of(p)
    return {
        "consumption": inv.consumption(tid, days),
        "wastage_value": inv.wastage_value(tid, days),
        "stock_value": inv.stock_value(tid),
        "ledger_errors": inv.check_invariant(tid),
    }
