"""Staff on shift (simple): who is working now, what they have on, and their thank-you points. In homestay mode the
whole small team is shown (no roster) as "Our team". Ids and role titles only; no personal data."""

import streamlit as st

from lib import platform, tenancy, theme, today, ui

ui.setup("pages/19_Staff.py", "Staff on shift")
HOMESTAY = tenancy.is_homestay()
ui.page_head(
    "Our team" if HOMESTAY else "Staff on shift",
    "Everyone in your team and what they are doing now." if HOMESTAY else "Who is working right now and how busy they are.",
)

d = today.gather()
team = d.get("staff") or []
ctx = None if HOMESTAY else (ui.api(platform.get_context, what="load who is on shift") or {})
working = set((ctx or {}).get("working", {})) if not HOMESTAY else {s["employee_id"] for s in team}
load: dict[str, int] = {}
for j in d.get("open_jobs") or []:
    who = j.get("assigned_to") or (j.get("offer_to") if j["status"] == "offered" else None)
    if who:
        load[who] = load.get(who, 0) + 1
rec = ui.api(platform.recognition_summary, what="load recognition points", feature="recognition points")
points = {w["employee_id"]: w for w in (rec or {}).get("workers", [])} if isinstance(rec, dict) else {}

on = [s for s in team if s["employee_id"] in working]
busy = [s for s in on if load.get(s["employee_id"], 0) >= 3]
ui.big_numbers(
    [
        ("Working now", len(on), f"of {len(team)} in the team", "info"),
        (
            "Busy",
            len(busy),
            "3 or more tasks at once: ask if they need a hand" if busy else "Nobody is overloaded",
            "warn" if busy else "ok",
        ),
        (
            "Thank-you points",
            (rec or {}).get("team", {}).get("total_points", "—") if isinstance(rec, dict) else "—",
            "Earned this month",
            "ok",
        ),
    ]
)

show = team if HOMESTAY else (on if st.toggle("Only people on shift", value=True, key="only_on") else team)
if not show:
    ui.empty("Nobody is on shift right now." if not HOMESTAY else "No team members yet. Add them in Settings.")


def card(s: dict) -> str:
    e = s["employee_id"]
    k = load.get(e, 0)
    p = points.get(e, {})
    state = "Working" if e in working else "Off"
    return (
        f'<div class="ss-staff {"on" if e in working else ""}">{ui.avatar_img(s.get("department"), 52)}'
        f"<div><b>{theme.esc(ui.short_name(e))}</b><div class='r'>{theme.esc(s.get('role_title') or theme.dept_label(s.get('department')))}</div>"
        f"<div class='t'><span class='pill'>{state}</span><span>{k} task{'s' if k != 1 else ''}</span>"
        f"<span>★ {p.get('points', 0)} pts</span></div></div></div>"
    )


ui.html('<div class="ss-staffgrid">' + "".join(card(s) for s in show) + "</div>")
st.caption("Points are thank-you points only: never used to punish. Staff see only their own points in their app.")
ui.html("""<style>
.ss-staffgrid { display:grid; grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); gap:12px; }
.ss-staff { background:#fff; border-radius:20px; padding:16px; display:flex; gap:14px; align-items:center; border:2px solid transparent; }
.ss-staff.on { border-color:#bfe8c4; }
.ss-staff b { font-size:1.1rem; } .ss-staff .r { color:var(--ink2); font-size:.9rem; }
.ss-staff .t { display:flex; gap:10px; flex-wrap:wrap; color:var(--muted); font-size:.82rem; margin-top:6px; align-items:center; }
.ss-staff .pill { background:var(--field); border-radius:999px; padding:2px 10px; color:var(--ink); font-weight:600; }
.ss-staff.on .pill { background:#ecfbea; color:#0a6b12; }
.ss-staff .ss-ravatar { border-radius:999px; flex:none; }
</style>""")
ui.footer()
