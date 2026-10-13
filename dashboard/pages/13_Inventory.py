from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import auth, data, dispatch, platform, tenancy, theme, ui

ui.setup("pages/13_Inventory.py", "Inventory")
U = auth.current()
CAN_MANAGE = U["role"] in ("owner", "storekeeper", "platform_admin")
ROOMS = tenancy.rooms()
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


def get(path: str, **params):
    return platform.inv("GET", path, params=params or None)


def act(method: str, path: str, body: dict, ok: str | None = None) -> bool:
    """Run a write; show the API's message on failure, rerun on success."""
    try:
        platform.inv(method, path, json=body)
    except platform.PlatformError as e:
        st.error(e.message)
        return False
    if ok:
        st.toast(ok)
    st.rerun()
    return True


try:
    items, locs, sups = get("/items"), get("/locations"), get("/suppliers")
    stock_payload = get("/stock")
except platform.PlatformError as e:
    ui.html(theme.banner(f"<b>Could not load inventory.</b> {theme.esc(e.message)}", "red", "alert"))
    ui.footer()
    st.stop()
item_by = {i["id"]: i for i in items}
loc_by = {l["id"]: l for l in locs}
sup_by = {s["id"]: s for s in sups}
stk = {(r["item_id"], r["location_id"]): r["qty"] for r in stock_payload["stock"]}
on_hand = stock_payload["on_hand"]

ui.html(
    theme.section(
        "Inventory",
        "Stores & purchasing",
        "Every movement is in one ledger. Reorder quantities follow the same occupancy forecast as the roster.",
    )
)
if not items:
    ui.empty("No items yet. Add items in the Catalog tab" + ("" if CAN_MANAGE else " (ask your storekeeper)") + ".")

tabs = st.tabs(["Overview", "Requests", "Purchasing", "Stock & moves", "Stock count", "Catalog"])

# ------------------------------------------------------------------ overview
with tabs[0]:
    occ: list[float] = []
    wk = data.demo_week() or ui.ensure_demo_week()
    if wk:
        d0 = date.fromisoformat(wk)
        fc = ui.safe(data.forecast, d0.isoformat(), (d0 + timedelta(days=6)).isoformat(), what="load the occupancy forecast")
        occ = [d.mean for d in fc.days] if fc else []
    sugg = get("/suggestions", rooms=ROOMS, occ=",".join(f"{x:.3f}" for x in occ))
    analytics = get("/analytics", days=28)
    pending = get("/requests", status="pending,partial")
    open_po = [p for p in get("/pos") if p["status"] in ("draft", "approved", "sent", "partial")]
    cons = analytics["consumption"]
    issue_value = sum(r["value"] or 0 for r in cons)
    occ_nights = ROOMS * 28 * (sum(occ) / len(occ) if occ else 0.7)
    ui.html(
        theme.tiles(
            [
                theme.tile("Stock value", ui.inr(analytics["stock_value"]), f"{len(items)} items · {len(locs)} locations", "rupee"),
                theme.tile("Below reorder point", str(sum(1 for s in sugg if s["low"])), "need ordering", "alert"),
                theme.tile("Open requests", str(len(pending)), "waiting for the store", "flag"),
                theme.tile("Open purchase orders", str(len(open_po)), "draft / approved / sent", "clock"),
                theme.tile(
                    "Cost per occupied room",
                    ui.inr(issue_value / occ_nights if occ_nights else 0),
                    "last 28 days",
                    "bed",
                    assumption="room-nights estimated from forecast",
                ),
            ]
        )
    )
    a, b = st.columns([1.5, 1])
    with a:
        ui.html(
            theme.section(
                "Reorder suggestions",
                "Static par vs forecast-aware",
                f"Forecast-aware = usage per occupied room × {ROOMS} rooms × forecast occupancy over (7 days + lead time).",
            )
        )
        df = pd.DataFrame(
            [
                {
                    "Item": s["name"],
                    "On hand": round(s["on_hand"]),
                    "On order": round(s["on_order"]),
                    "Reorder pt": s["reorder_point"],
                    "Par": s["par"],
                    "Static rule": s["static_qty"],
                    "Forecast-aware": s["forecast_qty"],
                    "Unit": s["unit"],
                    "_id": s["id"],
                    "_sup": s["supplier_id"],
                }
                for s in sugg
                if s["static_qty"] or s["forecast_qty"]
            ]
        )
        if df.empty:
            ui.html(theme.banner("Everything is above its reorder point for the forecast week.", "blue", "check"))
        else:
            caught = df[(df["Static rule"] == 0) & (df["Forecast-aware"] > 0)]
            if len(caught):
                ui.html(
                    theme.banner(
                        f"<b>{len(caught)} item(s) look fine on static par but will run short</b> in the forecast busy week: "
                        + ", ".join(theme.esc(x) for x in caught["Item"].head(5)),
                        "amber",
                        "trend",
                    )
                )
            st.dataframe(df.drop(columns=["_id", "_sup"]), hide_index=True, width="stretch")
            if CAN_MANAGE and st.button(
                "Create draft POs from forecast-aware suggestions", type="primary", icon=":material/shopping_cart:"
            ):
                by_sup: dict[str, dict] = {}
                for _, r in df[df["Forecast-aware"] > 0].iterrows():
                    by_sup.setdefault(r["_sup"], {})[r["_id"]] = float(r["Forecast-aware"])
                for sid, lines in by_sup.items():
                    ui.safe(
                        platform.inv,
                        "POST",
                        "/pos",
                        json={"supplier_id": sid, "lines": lines, "note": "Auto-suggested from forecast"},
                        what="create the purchase order",
                    )
                st.toast(f"{len(by_sup)} draft PO(s) created", icon=":material/shopping_cart:")
                st.rerun()
    with b:
        ui.html(theme.section("Consumption by department", "Last 28 days"))
        if cons:
            cd = pd.DataFrame(cons)
            byd = cd.groupby("department")["value"].sum().sort_values()
            fig = go.Figure(
                go.Bar(
                    x=byd.values,
                    y=[theme.dept_label(x) for x in byd.index],
                    orientation="h",
                    marker=dict(color="#2a78d6", cornerradius=4),
                    text=[ui.inr(v) for v in byd.values],
                    textposition="outside",
                    cliponaxis=False,
                    hovertemplate="%{y}: ₹%{x:,.0f}<extra></extra>",
                )
            )
            st.plotly_chart(theme.style_fig(fig, 260, legend=False), width="stretch", config={"displayModeBar": False})
            daily = cd.groupby("d")["value"].sum()
            fig2 = go.Figure(
                go.Scatter(
                    x=list(daily.index),
                    y=list(daily.values),
                    mode="lines",
                    line=dict(color="#2a78d6", width=2),
                    fill="tozeroy",
                    fillcolor="rgba(42,120,214,.12)",
                    hovertemplate="%{x}: ₹%{y:,.0f}<extra></extra>",
                )
            )
            fig2.update_layout(title="Daily issue value")
            st.plotly_chart(theme.style_fig(fig2, 220, legend=False), width="stretch", config={"displayModeBar": False})
        ui.html(theme.banner(f"Wastage last 28 days: <b>{ui.inr(analytics['wastage_value'])}</b>", "gray", "alert"))
    linen = [s for s in sugg if s["category"] == "Linen"]
    if linen:
        ui.html(
            theme.section(
                "Linen par",
                "Housekeeping",
                f"Pieces on hand per room ({ROOMS} rooms). Hotels commonly plan around 3 par "
                "(one in room, one in laundry, one on the shelf).",
            )
        )
        ui.html(
            '<div class="ss-statusrow">'
            + "".join(
                theme.status_card(
                    s["name"],
                    f"{s['on_hand'] / ROOMS:.1f} par",
                    f"{s['on_hand']:.0f}",
                    "ok" if s["on_hand"] / ROOMS >= 3 else "below 3 par",
                    "low" if s["on_hand"] / ROOMS >= 3 else "watch",
                )
                for s in linen
            )
            + "</div>"
        )

# ------------------------------------------------------------------ requests
with tabs[1]:
    st.markdown("**New request**")
    with st.form("newreq", clear_on_submit=True):
        c1, c2, c3 = st.columns([1.2, 1, 1])
        dept = c1.selectbox("Department", dispatch.DEPARTMENTS, format_func=theme.dept_label)
        to_loc = c2.selectbox(
            "Deliver to", [None] + [l["id"] for l in locs], format_func=lambda i: "Requester" if i is None else loc_by[i]["name"]
        )
        room = c3.text_input("Room (optional)")
        pick = st.multiselect("Items", [i["id"] for i in items], format_func=lambda i: f"{item_by[i]['name']} ({item_by[i]['unit']})")
        qty = {i: st.number_input(f"Qty · {item_by[i]['name']}", 1.0, 10000.0, 1.0, key=f"rq_{i}") for i in pick}
        note = st.text_input("Note")
        send = st.form_submit_button("Submit request", type="primary")
    if send:
        act(
            "POST",
            "/requests",
            {"department": dept, "lines": qty, "location_id": to_loc, "room": room or None, "note": note},
            "Request submitted",
        )
    st.divider()
    flt = st.segmented_control("Show", ["Open", "All"], default="Open", key="req_filter")
    for r in get("/requests", **({"status": "pending,partial"} if flt == "Open" else {})):
        tone = {"pending": "watch", "partial": "watch", "issued": "low", "rejected": "high"}.get(r["status"], "unknown")
        with st.container(key=f"card_req_{r['id']}"):
            ui.html(
                f'<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><b>{theme.esc(r["id"])}</b>{theme.band_chip(tone, r["status"])}'
                f'<span class="ss-tag">{theme.esc(theme.dept_label(r["department"]))}</span><span class="ss-tag">by {theme.esc(ui.short_name(r["requested_by"]))}</span>'
                + (f'<span class="ss-tag">room {theme.esc(r["room"])}</span>' if r.get("room") else "")
                + f'<span style="color:#6b6a65;font-size:.78rem">{r["created_at"][:16].replace("T", " ")} · {theme.esc(r.get("note") or "")}</span></div>'
            )
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Item": item_by.get(l["item_id"], {}).get("name", l["item_id"]),
                            "Requested": l["qty"],
                            "Issued": l["qty_issued"],
                            "Store stock": round(on_hand.get(l["item_id"], 0)),
                        }
                        for l in r["lines"]
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
            if CAN_MANAGE and r["status"] in ("pending", "partial"):
                c1, c2, c3, c4 = st.columns([1.4, 1, 1, 1])
                src = c1.selectbox("Issue from", [l["id"] for l in locs], format_func=lambda i: loc_by[i]["name"], key=f"src_{r['id']}")
                if c2.button("Issue all", key=f"iss_{r['id']}", type="primary", width="stretch"):
                    act(
                        "POST",
                        f"/requests/{r['id']}/fulfil",
                        {"issued": {l["item_id"]: l["qty"] - l["qty_issued"] for l in r["lines"]}, "from_location": src},
                    )
                if c3.button("Issue what's in stock", key=f"isp_{r['id']}", width="stretch"):
                    part = {l["item_id"]: min(l["qty"] - l["qty_issued"], stk.get((l["item_id"], src), 0)) for l in r["lines"]}
                    act("POST", f"/requests/{r['id']}/fulfil", {"issued": part, "from_location": src})
                if c4.button("Reject", key=f"rej_{r['id']}", width="stretch"):
                    act("POST", f"/requests/{r['id']}/reject", {"note": "not approved"})

# ------------------------------------------------------------------ purchasing
with tabs[2]:
    pos = get("/pos")
    flow = ["draft", "approved", "sent", "partial", "received"]
    ui.html(
        '<div class="ss-stepper">'
        + "".join(f'<div class="s"><span>{sum(1 for p in pos if p["status"] == s)}</span>{s}</div>' for s in flow)
        + "</div>"
    )
    if CAN_MANAGE and sups:
        with st.expander("New purchase order"):
            with st.form("newpo", clear_on_submit=True):
                sid = st.selectbox(
                    "Supplier", [s["id"] for s in sups], format_func=lambda i: f"{sup_by[i]['name']} · {sup_by[i]['lead_days']} d lead"
                )
                pick = st.multiselect("Items", [i["id"] for i in items], format_func=lambda i: item_by[i]["name"])
                qty = {i: st.number_input(f"Qty · {item_by[i]['name']}", 1.0, 100000.0, 10.0, key=f"poq_{i}") for i in pick}
                note = st.text_input("Note")
                if st.form_submit_button("Create draft PO", type="primary"):
                    act("POST", "/pos", {"supplier_id": sid, "lines": qty, "note": note}, "Draft PO created")
    for p in pos:
        tone = {"draft": "unknown", "approved": "watch", "sent": "watch", "partial": "watch", "received": "low", "cancelled": "high"}[
            p["status"]
        ]
        tot = p.get("totals") or {}
        total = tot.get("total", sum(l["qty"] * l["unit_cost"] for l in p["lines"]))
        with st.container(key=f"card_po_{p['id']}"):
            ui.html(
                f'<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><b>{theme.esc(p["id"])}</b>{theme.band_chip(tone, p["status"])}'
                f'<span class="ss-tag">{theme.esc(sup_by.get(p["supplier_id"], {}).get("name", "?"))}</span><span class="ss-tag">{ui.inr(total)} incl. GST</span>'
                f'<span class="ss-tag">expected {theme.esc(p.get("expected_at") or "—")}</span>'
                f'<span style="color:#6b6a65;font-size:.78rem">{theme.esc(p.get("note") or "")}</span></div>'
            )
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Item": item_by.get(l["item_id"], {}).get("name", l["item_id"]),
                            "Ordered": l["qty"],
                            "Received": l["qty_received"],
                            "Unit ₹": l["unit_cost"],
                            "Line ₹": l["qty"] * l["unit_cost"],
                        }
                        for l in p["lines"]
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
            if tot:
                split = (
                    f"IGST {ui.inr(tot['igst'])}" if tot.get("interstate") else f"CGST {ui.inr(tot['cgst'])} + SGST {ui.inr(tot['sgst'])}"
                )
                g1, g2 = st.columns([3, 1])
                g1.caption(
                    f"Taxable {ui.inr(tot['taxable'])} · {split} · total {ui.inr(tot['total'])} "
                    "(rates from the item catalog; confirm with your accountant)"
                )
                try:
                    doc = platform.inv("GET", f"/pos/{p['id']}/document", raw=True)
                    g2.download_button(
                        "PO document", doc, f"{p['id']}.html", "text/html", key=f"doc_{p['id']}", icon=":material/description:"
                    )
                except platform.PlatformError:
                    pass
            if CAN_MANAGE:
                b1, b2, b3, b4 = st.columns(4)
                if p["status"] == "draft" and b1.button("Approve", key=f"ap_{p['id']}", type="primary", width="stretch"):
                    act("POST", f"/pos/{p['id']}/status", {"status": "approved"})
                if p["status"] == "approved" and b1.button("Mark sent", key=f"se_{p['id']}", type="primary", width="stretch"):
                    act("POST", f"/pos/{p['id']}/status", {"status": "sent"})
                if p["status"] in ("approved", "sent", "partial"):
                    loc = b2.selectbox(
                        "Receive into",
                        [l["id"] for l in locs],
                        format_func=lambda i: loc_by[i]["name"],
                        key=f"rl_{p['id']}",
                        label_visibility="collapsed",
                    )
                    if b3.button("Receive all (GRN)", key=f"rc_{p['id']}", width="stretch"):
                        act(
                            "POST",
                            f"/pos/{p['id']}/receive",
                            {"received": {l["item_id"]: l["qty"] for l in p["lines"]}, "location_id": loc},
                        )
                    with st.popover("Partial receipt"):
                        got = {
                            l["item_id"]: st.number_input(
                                item_by.get(l["item_id"], {}).get("name", l["item_id"]),
                                0.0,
                                float(l["qty"] - l["qty_received"]),
                                0.0,
                                key=f"pr_{p['id']}_{l['item_id']}",
                            )
                            for l in p["lines"]
                            if l["qty"] > l["qty_received"]
                        }
                        if st.button("Post GRN", key=f"grn_{p['id']}"):
                            act("POST", f"/pos/{p['id']}/receive", {"received": got, "location_id": loc})
                if p["status"] in ("draft", "approved", "sent") and b4.button("Cancel", key=f"cx_{p['id']}", width="stretch"):
                    act("POST", f"/pos/{p['id']}/status", {"status": "cancelled"})

# ------------------------------------------------------------------ stock & moves
with tabs[3]:
    grid = pd.DataFrame(
        [
            {
                "Item": i["name"],
                "Category": i["category"],
                **{l["name"]: round(stk.get((i["id"], l["id"]), 0), 1) for l in locs},
                "Total": round(sum(stk.get((i["id"], l["id"]), 0) for l in locs), 1),
                "Reorder pt": i["reorder_point"],
            }
            for i in items
        ]
    )
    if not grid.empty:

        def low_style(row):
            return [
                "background-color:#fdeceb;color:#a32020;font-weight:600" if c == "Total" and row["Total"] <= row["Reorder pt"] else ""
                for c in row.index
            ]

        st.dataframe(grid.style.apply(low_style, axis=1), hide_index=True, width="stretch", height=420)
    if CAN_MANAGE and items and locs:
        c1, c2, c3 = st.columns(3)
        with c1.popover("Transfer between locations", width="stretch"):
            it = st.selectbox("Item", [i["id"] for i in items], format_func=lambda i: item_by[i]["name"], key="tr_it")
            fr = st.selectbox("From", [l["id"] for l in locs], format_func=lambda i: loc_by[i]["name"], key="tr_fr")
            to = st.selectbox(
                "To", [l["id"] for l in locs], format_func=lambda i: loc_by[i]["name"], key="tr_to", index=min(1, len(locs) - 1)
            )
            q = st.number_input("Qty", 1.0, 100000.0, 10.0, key="tr_q")
            if st.button("Transfer", key="tr_go", type="primary"):
                act("POST", "/transfer", {"item_id": it, "from_location": fr, "to_location": to, "qty": q})
        with c2.popover("Record wastage / damage", width="stretch"):
            it = st.selectbox("Item", [i["id"] for i in items], format_func=lambda i: item_by[i]["name"], key="ws_it")
            lo = st.selectbox("Location", [l["id"] for l in locs], format_func=lambda i: loc_by[i]["name"], key="ws_lo")
            q = st.number_input("Qty", 1.0, 100000.0, 1.0, key="ws_q")
            why = st.text_input("Reason", key="ws_r", placeholder="torn, expired, damaged in transit…")
            if st.button("Record", key="ws_go", type="primary"):
                act("POST", "/waste", {"item_id": it, "location_id": lo, "qty": q, "reason": why})
        with c3.popover("Receive without PO", width="stretch"):
            it = st.selectbox("Item", [i["id"] for i in items], format_func=lambda i: item_by[i]["name"], key="rv_it")
            lo = st.selectbox("Into", [l["id"] for l in locs], format_func=lambda i: loc_by[i]["name"], key="rv_lo")
            q = st.number_input("Qty", 1.0, 100000.0, 10.0, key="rv_q")
            ref = st.text_input("Invoice / delivery ref", key="rv_ref")
            if st.button("Receive", key="rv_go", type="primary"):
                act("POST", "/receive", {"item_id": it, "location_id": lo, "qty": q, "ref": ref})
    ui.html(theme.section("Ledger", "Every movement"))
    mv = get("/moves", limit=400)
    if mv:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "When": m["at"][:16].replace("T", " "),
                        "Item": item_by.get(m["item_id"], {}).get("name", m["item_id"]),
                        "Location": loc_by.get(m["location_id"], {}).get("name", ""),
                        "Qty": m["qty"],
                        "Type": MOVE_KINDS.get(m["kind"], m["kind"]),
                        "Dept": theme.dept_label(m["department"]) if m["department"] else "",
                        "Room": m["room"] or "",
                        "Ref": m["ref"] or "",
                        "Reason": m["reason"] or "",
                        "By": ui.short_name(m["by_user"]),
                    }
                    for m in mv
                ]
            ),
            hide_index=True,
            width="stretch",
            height=360,
        )
    errs = get("/analytics", days=1)["ledger_errors"]
    st.caption(
        "Ledger check: stock equals the sum of movements for every item and location." if not errs else f"Ledger mismatch: {errs[:3]}"
    )

# ------------------------------------------------------------------ stock count
with tabs[4]:
    oc = get("/counts")
    if not oc:
        if CAN_MANAGE and locs:
            c1, c2 = st.columns([2, 1])
            lo = c1.selectbox("Location to count", [l["id"] for l in locs], format_func=lambda i: loc_by[i]["name"])
            if c2.button("Start count", type="primary", width="stretch"):
                act("POST", "/counts", {"location_id": lo})
        ui.empty("No count in progress. A count freezes the system quantity now; enter what is physically on the shelf, then post.")
    for cnt in oc:
        ui.html(
            f"<b>Counting {theme.esc(loc_by.get(cnt['location_id'], {}).get('name', ''))}</b> · started {cnt['created_at'][:16].replace('T', ' ')}"
        )
        df = pd.DataFrame(
            [
                {
                    "item_id": l["item_id"],
                    "Item": item_by.get(l["item_id"], {}).get("name", ""),
                    "System": l["system_qty"],
                    "Counted": l["system_qty"],
                }
                for l in cnt["lines"]
            ]
        )
        ed = st.data_editor(
            df,
            hide_index=True,
            width="stretch",
            disabled=["item_id", "Item", "System"],
            column_config={"item_id": None},
            key=f"ed_{cnt['id']}",
        )
        ed["Variance"] = ed["Counted"] - ed["System"]
        val = sum(r["Variance"] * item_by.get(r["item_id"], {}).get("unit_cost", 0) for _, r in ed.iterrows())
        st.caption(f"Variance value: {ui.inr(val)} across {int((ed['Variance'] != 0).sum())} item(s)")
        if CAN_MANAGE and st.button("Post count adjustments", type="primary", key=f"post_{cnt['id']}"):
            act(
                "POST",
                f"/counts/{cnt['id']}/post",
                {"counted": {r["item_id"]: float(r["Counted"]) for _, r in ed.iterrows()}},
                "Count posted",
            )

# ------------------------------------------------------------------ catalog
with tabs[5]:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "SKU": i["sku"],
                    "Item": i["name"],
                    "Category": i["category"],
                    "Unit": i["unit"],
                    "Unit ₹": i["unit_cost"],
                    "Par": i["par"],
                    "Reorder pt": i["reorder_point"],
                    "Lead days": i["lead_days"],
                    "Use / occupied room": i["per_occ_room"],
                    "Supplier": sup_by.get(i["supplier_id"], {}).get("name", ""),
                }
                for i in items
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    if CAN_MANAGE:
        c1, c2, c3 = st.columns(3)
        with c1.popover("Add item", width="stretch"):
            with st.form("newitem", clear_on_submit=True):
                name = st.text_input("Name")
                sku = st.text_input("SKU")
                cat = st.selectbox("Category", CATEGORIES)
                unit = st.text_input("Unit", "pc")
                cost = st.number_input("Unit cost ₹", 0.0, 1e6, 10.0)
                par = st.number_input("Par level", 0.0, 1e6, 50.0)
                rop = st.number_input("Reorder point", 0.0, 1e6, 20.0)
                poc = st.number_input("Usage per occupied room-night (0 if not room-driven)", 0.0, 50.0, 0.0, step=0.01)
                g1, g2 = st.columns(2)
                hsn = g1.text_input("HSN code", placeholder="6302")
                gst = g2.selectbox("GST rate %", [0, 5, 12, 18, 28, 0.25, 3, 40], index=3, help="Confirm the rate with your accountant.")
                sid = st.selectbox("Supplier", [s["id"] for s in sups], format_func=lambda i: sup_by[i]["name"]) if sups else None
                if st.form_submit_button("Add", type="primary"):
                    act(
                        "POST",
                        "/items",
                        {
                            "sku": sku,
                            "name": name,
                            "category": cat,
                            "unit": unit,
                            "unit_cost": cost,
                            "par": par,
                            "reorder_point": rop,
                            "supplier_id": sid,
                            "per_occ_room": poc,
                            "hsn": hsn or None,
                            "gst_rate": gst,
                        },
                        "Item added",
                    )
        with c2.popover("Add location", width="stretch"):
            ln = st.text_input("Location name", key="nl_name")
            if st.button("Add location", key="nl_go") and ln:
                act("POST", "/locations", {"name": ln})
        with c3.popover("Add supplier", width="stretch"):
            sn = st.text_input("Supplier name", key="ns_name")
            sl = st.number_input("Lead time (days)", 1, 60, 3, key="ns_lead")
            gstin = st.text_input("GSTIN (optional)", key="ns_gstin", placeholder="05ABCDE1234F1Z5", max_chars=15)
            inter = st.toggle("Supplier is in another state (IGST)", key="ns_inter")
            if st.button("Add supplier", key="ns_go") and sn:
                act("POST", "/suppliers", {"name": sn, "lead_days": int(sl), "gstin": gstin or None, "interstate": inter})

ui.footer()
