import streamlit as st

from lib import employee_ctx, platform, theme, ui

ui.setup("employee/3_Supplies.py", "Supplies", employee=True)
ctx = employee_ctx.context()
employee_ctx.header(ctx, "Supplies")
items = ui.safe(platform.inv, "GET", "/items", what="load the item list") or []
mine = [i for i in items if i.get("department") in (ctx["dept"], None)] or items
by = {i["id"]: i for i in items}

ui.html(theme.section("Request supplies", "To the store"))
with st.form("ereq", clear_on_submit=True):
    pick = st.multiselect("What do you need?", [i["id"] for i in mine], format_func=lambda i: f"{by[i]['name']} ({by[i]['unit']})")
    qty = {i: st.number_input(by[i]["name"], 1.0, 500.0, 1.0, key=f"eq_{i}") for i in pick}
    room = st.text_input("Room (optional)")
    note = st.text_input("Note (optional)")
    send = st.form_submit_button("Send request", type="primary", width="stretch")
if send:
    body = {"department": ctx["dept"] or "housekeeping", "lines": qty, "room": room or None, "note": note}
    if ui.safe(platform.inv, "POST", "/requests", json=body, what="send the request"):
        st.toast("Request sent to the store", icon=":material/inventory_2:")

ui.html(theme.section("My requests", "Status"))
reqs = ui.safe(platform.inv, "GET", "/requests", what="load your requests") or []
if not reqs:
    ui.empty("No requests yet.")
for r in reqs[:15]:
    tone = {"pending": "watch", "partial": "watch", "issued": "low", "rejected": "high"}.get(r["status"], "unknown")
    lines = ", ".join(f"{by.get(l['item_id'], {}).get('name', '?')} {l['qty_issued']:g}/{l['qty']:g}" for l in r["lines"])
    ui.html(
        f'<div class="ss-task"><div style="display:flex;justify-content:space-between;gap:8px"><b>{theme.esc(lines)}</b>'
        f'{theme.band_chip(tone, r["status"])}</div><div class="m">{r["created_at"][:16].replace("T", " ")}'
        + (f" · room {theme.esc(r['room'])}" if r.get("room") else "")
        + "</div></div>"
    )
ui.footer()
