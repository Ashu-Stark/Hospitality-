import base64

import streamlit as st

from lib import auth, data, platform, theme, ui

ui.setup("pages/14_Rooms.py", "Rooms")
IS_OWNER = auth.role() in ("owner", "platform_admin")
STATUS = {  # label, band tone (reuses the reserved status colours), what happens next
    "ready": ("Ready", "low", "Check in a guest"),
    "occupied": ("Occupied", "unknown", "Checkout creates a cleaning job"),
    "dirty": ("Dirty", "high", "Cleaning job offered to housekeeping"),
    "cleaning": ("Cleaning", "watch", "In progress (before photo taken)"),
    "inspection": ("Waiting for check", "watch", "Supervisor checks it: OK or clean again"),
    "out_of_order": ("Out of order", "high", "Maintenance job raised"),
}

ui.page_head("Rooms", "Which rooms are ready, being cleaned or need attention. Checkout creates the cleaning job for you.")
data.ops_inputs()  # make sure the dispatch engine knows who is on shift

payload = ui.safe(platform.rooms, what="load rooms")
if payload is None:
    ui.footer()
    st.stop()
rooms, summary = payload["rooms"], payload["summary"]
if not rooms:
    ui.empty("No rooms yet." + (" Add them below." if IS_OWNER else " Ask the owner to add rooms."))

to_clean = summary.get("dirty", 0) + summary.get("cleaning", 0)
ui.big_numbers(
    [
        ("Ready", summary.get("ready", 0), "Clean and free for the next guest", "ok"),
        ("Guests in", summary.get("occupied", 0), f"of {summary.get('total', 0)} rooms", "info"),
        ("To clean", to_clean, "Someone is on it or will be asked" if to_clean else "All clean", "warn" if to_clean else "ok"),
        (
            "To check",
            summary.get("inspection", 0) + summary.get("out_of_order", 0),
            "Waiting for a check, or out of order",
            "warn" if summary.get("inspection", 0) else "ok",
        ),
    ]
)

# ------------------------------------------------------------------ board
floors_all = sorted({r["floor"] for r in rooms if r["floor"] is not None})
f1, f2 = st.columns([2, 1])
with f1:
    show = st.segmented_control("Show", ["All"] + [v[0] for v in STATUS.values()], default="All", key="room_filter")
with f2:
    floor = st.selectbox("Floor", ["All", *floors_all], key="room_floor") if len(floors_all) > 1 else "All"
visible = [r for r in rooms if (show in (None, "All") or STATUS[r["status"]][0] == show) and (floor == "All" or r["floor"] == floor)]

ui.html(
    '<div class="ss-rooms">'
    + "".join(
        f'<div class="ss-room {r["status"]}"><b>{theme.esc(r["number"])}</b><span>{theme.esc(STATUS[r["status"]][0])}</span></div>'
        for r in visible
    )
    + "</div>"
    + """<style>
.ss-rooms{display:grid;grid-template-columns:repeat(auto-fill,minmax(92px,1fr));gap:8px;margin:12px 0}
.ss-room{border-radius:16px;padding:12px 10px;background:#fff;border:1.5px solid #e6e5e0;display:flex;flex-direction:column;gap:2px}
.ss-room b{font-size:1.15rem;letter-spacing:-.02em}.ss-room span{font-size:.74rem;color:#52514e}
.ss-room.ready{background:#ecfbea;border-color:#62d36b}.ss-room.dirty,.ss-room.out_of_order{background:#fdeceb;border-color:#efa3a1}
.ss-room.cleaning,.ss-room.inspection{background:#fff6df;border-color:#f2cd6f}
</style>"""
)
with st.expander("What the colours mean"):
    ui.html(" ".join(theme.band_chip(tone, f"{label}: {hint}") for label, tone, hint in STATUS.values()))

# ------------------------------------------------------------------ attention queue (most frequent supervisor actions)
waiting = [r for r in rooms if r["status"] == "inspection"]
busy = [r for r in rooms if r["status"] in ("dirty", "cleaning")]
if waiting or busy:
    ui.html('<h3 class="ss-h3">Needs you</h3>')
    try:
        jobs = {j["id"]: j for j in platform.jobs()}
    except platform.PlatformError:
        jobs = {}
    for r in waiting:
        with st.container(key=f"card_insp_{r['id']}"):
            a, b, c = st.columns([3, 1, 1])
            a.markdown(f"**Room {r['number']}** · cleaned, waiting for a check")
            if b.button("OK", key=f"pass_{r['id']}", type="primary", width="stretch"):
                if ui.safe(platform.room_action, r["id"], "inspect", {"passed": True}, what="pass inspection"):
                    st.rerun()
            if c.button("Clean again", key=f"fail_{r['id']}", width="stretch"):
                if ui.safe(platform.room_action, r["id"], "inspect", {"passed": False, "note": ""}, what="send back"):
                    st.rerun()
    for r in busy:
        j = jobs.get(r.get("current_job_id") or "", {})
        who = j.get("assigned_to") or j.get("offer_to")
        state = {
            "offered": f"sent to {who}",
            "accepted": f"taken by {who}",
            "in_progress": f"{who} cleaning now",
            "unassigned": "nobody took it: send it again on the Jobs page",
            "done": "done",
        }.get(j.get("status"), "queued")
        ui.html(
            f'<div class="ss-wrow"><b style="min-width:60px">{theme.esc(r["number"])}</b>'
            f"{theme.band_chip('high' if j.get('status') == 'unassigned' else 'watch', state)}</div>"
        )

# ------------------------------------------------------------------ act on a room
ui.html('<h3 class="ss-h3">Update a room</h3>')
if visible:
    with st.container(key="card_room_act"):
        c1, c2 = st.columns([1, 3])
        # rooms that need an action first: occupied (checkout), inspection, out of order; ready rooms last
        order = {"occupied": 0, "inspection": 1, "out_of_order": 2, "dirty": 3, "cleaning": 4, "ready": 5}
        pick = c1.selectbox(
            "Room",
            [r["id"] for r in sorted(visible, key=lambda x: (order.get(x["status"], 9), x["number"]))],
            format_func=lambda i: next(f"{r['number']} · {STATUS[r['status']][0]}" for r in rooms if r["id"] == i),
            key="act_room",
        )
        r = next(x for x in rooms if x["id"] == pick)
        with c2:
            st.caption(STATUS[r["status"]][2] + (f" · {r['note']}" if r.get("note") else ""))
            b = st.columns(4)

            def go(action: str, body: dict | None = None, ok: str = "Updated") -> None:
                if ui.safe(platform.room_action, r["id"], action, body, what=f"update room {r['number']}"):
                    st.toast(ok, icon=":material/bed:")
                    st.rerun()

            if r["status"] == "occupied" and b[0].button("Checkout", type="primary", width="stretch"):
                go("checkout", ok=f"Room {r['number']}: cleaning job sent")
            if r["status"] == "ready" and b[0].button("Check in", type="primary", width="stretch"):
                go("check-in")
            if r["status"] == "inspection":
                if b[0].button("Check OK", type="primary", width="stretch"):
                    go("inspect", {"passed": True}, f"Room {r['number']} is ready")
                note = b[1].text_input(
                    "What to clean again", key=f"note_{r['id']}", label_visibility="collapsed", placeholder="What needs redoing?"
                )
                if b[2].button("Not OK: clean again", width="stretch"):
                    go("inspect", {"passed": False, "note": note}, "Clean-again job sent")
            if r["status"] == "out_of_order":
                if b[0].button("Back in service", type="primary", width="stretch"):
                    go("back-in-service", ok="Cleaning job sent before the next guest")
            elif r["status"] in ("ready", "occupied", "dirty"):
                with b[3].popover("Out of order", width="stretch"):
                    reason = st.text_input("Reason", key=f"ooo_{r['id']}", placeholder="Leaking pipe, broken AC…")
                    mj = st.toggle("Create a maintenance job", value=True, key=f"ooj_{r['id']}")
                    if st.button("Mark out of order", key=f"ooo_go_{r['id']}") and reason:
                        go("out-of-order", {"reason": reason, "create_job": mj}, "Marked out of order")

# ------------------------------------------------------------------ guest QR codes (secondary)
base = platform.public_url()
qr_box = st.expander("Room QR codes for guests") if IS_OWNER and rooms else None
if qr_box is not None:
    qr_box.caption("Print each room's code. Guests scan it to ask for things; nothing personal is asked.")
    c1, c2 = qr_box.columns([1, 2])
    with c1:
        qr_room = st.selectbox(
            "Room", [r["id"] for r in rooms], format_func=lambda i: next(r["number"] for r in rooms if r["id"] == i), key="qr_room"
        )
        rr = next(r for r in rooms if r["id"] == qr_room)
        svg = ui.safe(platform.room_qr, qr_room, what="make the QR code")
        if svg:
            ui.html(
                f'<img alt="QR code for room {theme.esc(rr["number"])}" style="width:180px;border-radius:12px;background:#fff;padding:6px" '
                f'src="data:image/svg+xml;base64,{base64.b64encode(svg).decode()}">'
            )
            st.download_button("Download QR (SVG)", svg, f"room_{rr['number']}_qr.svg", "image/svg+xml", icon=":material/download:")
    with c2:
        st.markdown(f"**Guest link for room {rr['number']}**")
        st.code(f"{base}/guest/?t={rr['guest_token']}", language=None)
        st.caption(
            "Each room has its own link. Requests go straight to the right team (towels → housekeeping, AC → maintenance, tea → F&B)."
        )
elif not IS_OWNER:
    st.caption("The owner can print room QR codes from this page.")
st.caption(f"Staff use their own app on their phone: {base}/worker/")
ui.footer()
