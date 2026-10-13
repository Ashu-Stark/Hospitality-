import random
from datetime import date

import pandas as pd
import streamlit as st

from lib import data, dispatch, models, platform, tenancy, theme, ui

ui.setup("pages/10_Dispatch.py", "Dispatch")
cfg = tenancy.active_settings()
SECONDS = int(cfg.get("offer_seconds", 30))

ui.page_head("Live jobs", "Requests go to the best free person on shift automatically. You only step in when nobody takes a job.")

ro, working, bands, day0, shift0 = data.ops_inputs()
with st.container(key="card_ops"):
    c1, c2 = st.columns([1.4, 1.3])
    with c1:
        days = ro.dates if ro else []
        day = (
            st.selectbox(
                "Operating day (roster week)",
                days,
                index=days.index(day0) if day0 in days else 0,
                format_func=lambda d: f"{models.DAY_NAMES[date.fromisoformat(d).weekday()]} {d}",
            )
            if days
            else None
        )
    with c2:
        shift = st.segmented_control("Shift", models.SHIFT_ORDER, default=shift0, key="ops_shift") or shift0
    c3, c4 = st.expander("Dispatch settings").columns(2)
    with c3:
        auto = st.toggle(
            "Auto-assign",
            value=cfg.get("assign_mode", "auto") == "auto",
            help="On: every new request is offered immediately. Off: requests wait for a supervisor.",
        )
        if auto != (cfg.get("assign_mode", "auto") == "auto"):
            ui.safe(platform.update_workspace, assign_mode="auto" if auto else "manual", what="save dispatch settings")
            tenancy.refresh()
    with c4:
        secs = st.select_slider(
            "Ping window", [15, 30, 60, 120], value=SECONDS if SECONDS in (15, 30, 60, 120) else 30, format_func=lambda s: f"{s} s"
        )
        if secs != SECONDS:
            ui.safe(platform.update_workspace, offer_seconds=secs, what="save dispatch settings")
            tenancy.refresh()
            SECONDS = secs
ro, working, bands, day, shift = data.ops_inputs(day, shift)
st.session_state["ops_day"], st.session_state["ops_shift_val"] = day, shift
if not working:
    ui.html(
        theme.banner("No one is on shift for this day/shift. Generate a roster (Roster page) or import staff in Setup.", "amber", "alert")
    )

# ------------------------------------------------------------------ new request
SAMPLES = [
    ("Extra towels needed", "housekeeping", "low"),
    ("AC not cooling", "maintenance", "high"),
    ("Room cleaning after checkout", "housekeeping", "medium"),
    ("Geyser not heating", "maintenance", "high"),
    ("Masala tea x2 to room", "fnb_service", "medium"),
    ("Taxi to Jolly Grant airport at 6 am", "front_office", "medium"),
    ("Bulb fused in bathroom", "maintenance", "low"),
    ("Fresh bed linen", "housekeeping", "low"),
]
with st.container(key="card_new"):
    a, b, c, d, e = st.columns([2.4, 0.9, 1.2, 1, 1.2])
    with a:
        title = st.text_input("New request", placeholder="e.g. AC not cooling", key="nr_title")
    with b:
        room = st.text_input("Room", placeholder="204", key="nr_room")
    with c:
        guess = dispatch.guess_department(title) if title else "housekeeping"
        dept = st.selectbox(
            "Department",
            dispatch.DEPARTMENTS,
            index=dispatch.DEPARTMENTS.index(guess),
            format_func=theme.dept_label,
            key=f"nr_dept_{guess}",
        )
    with d:
        urg = st.selectbox("Urgency", ["high", "medium", "low"], index=1)
    with e:
        ui.html('<div style="height:26px"></div>')
        send = st.button("Dispatch", type="primary", icon=":material/bolt:", width="stretch", disabled=not title)
    s1, s2 = st.columns([1.6, 3.4])
    with s1:
        sim = st.button("Simulate incoming request", icon=":material/notifications_active:")
    with s2:
        st.caption("Department is guessed from the words in the request; you can change it before dispatching.")
if send and title:
    if ui.safe(platform.create_job, title, dept, room or None, urg, "manual", what="dispatch the request"):
        st.toast("Request dispatched" if auto else "Request queued for a supervisor", icon=":material/bolt:")
if sim:
    staffed = set(working.values())
    pool = [s for s in SAMPLES if s[1] in staffed] or SAMPLES
    t, dpt, u = random.choice(pool)
    rm = f"{random.randint(1, tenancy.floors())}{random.randint(1, 12):02d}"
    if ui.safe(platform.create_job, t, dpt, rm, u, "simulated", what="simulate a request"):
        st.toast(f"Incoming: {t} · room {rm}", icon=":material/notifications_active:")


def render_job(j: dict, w: dict) -> None:
    tone, label = {
        "offered": ("watch", "pinging"),
        "accepted": ("low", "accepted"),
        "in_progress": ("low", "in progress"),
        "done": ("low", "done"),
        "unassigned": ("high", "needs supervisor"),
        "new": ("unknown", "queued"),
    }[j["status"]]
    who = j.get("offer_to") if j["status"] == "offered" else j.get("assigned_to")
    secs = j.get("seconds_left", 0)
    with st.container(key=f"card_job_{j['id']}"):
        a, b = st.columns([3, 1.3])
        with a:
            ping = (
                (
                    f'<div class="ss-ping">{ui.avatar_img(j["department"], 34, "ping")}'
                    f"Pinging <b>{theme.esc(ui.short_name(who))}</b> · {secs}s left"
                    f'<div class="ss-countdown"><i style="width:{100 * secs / max(1, SECONDS):.0f}%"></i></div></div>'
                )
                if j["status"] == "offered"
                else ""
            )
            ui.html(
                f'<div class="ss-anim"><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">'
                f'<b style="font-size:1.05rem">{theme.esc(j["title"])}</b>{theme.band_chip(tone, label)}'
                f'<span class="ss-tag">{theme.esc(theme.dept_label(j["department"]))}</span>'
                + (f'<span class="ss-tag">room {theme.esc(j["room"])}</span>' if j.get("room") else "")
                + f'<span class="ss-tag">{theme.esc(j["urgency"])}</span></div>'
                f'<div style="color:#6b6a65;font-size:.78rem;margin-top:4px">{theme.esc(j["source"])} · {j["created_at"][11:16]}'
                + (
                    f" · assigned to <b>{theme.esc(ui.short_name(who))}</b>"
                    if j["status"] in ("accepted", "in_progress", "done") and who
                    else ""
                )
                + (f" · task #{theme.esc(j['backend_task_id'])}" if j.get("backend_task_id") else "")
                + f"</div>{ping}"
                + (f'<div style="color:#a32020;font-size:.8rem;margin-top:4px">{theme.esc(j["note"])}</div>' if j.get("note") else "")
                + "</div>"
            )
        with b:
            if j["status"] in ("unassigned", "new"):
                opts = [e for e, d in w.items() if d == j["department"]]
                if opts:
                    pick = st.selectbox("Assign to", opts, key=f"pick_{j['id']}", format_func=ui.short_name, label_visibility="collapsed")
                    if st.button("Offer", key=f"offer_{j['id']}", width="stretch"):
                        ui.safe(platform.job_action, j["id"], "offer", pick, what="offer the job")
                        st.rerun(scope="fragment")
                if st.button("Retry auto", key=f"retry_{j['id']}", width="stretch"):
                    ui.safe(platform.retry, j["id"], what="retry")
                    st.rerun(scope="fragment")
        if j.get("ranking"):
            with st.expander("Why this worker?"):
                for i, r in enumerate(j["ranking"][:5], 1):
                    p = r["parts"]
                    st.caption(
                        f"{i}. {ui.short_name(r['employee_id'])}: score {r['score']} = 100 "
                        f"{p['open_jobs']:+d} open jobs {p['done_this_shift']:+d} fairness {p['distance']:+d} distance (floor {r['floor']}) "
                        f"{p['retention_guard']:+d} retention guard ({r['band']})"
                    )
                tried = [f"{ui.short_name(a['employee_id'])}: {a['outcome']}" for a in j.get("attempts", [])]
                if tried:
                    st.caption("Offer history: " + " → ".join(tried))
        if j["status"] in ("in_progress", "done"):
            ph = platform.job_photos(j["id"])
            if ph:
                cols = st.columns(2)
                for col, kind in zip(cols, ("before", "after")):
                    with col:
                        if kind in ph:
                            st.image(
                                platform.photo_bytes(ph[kind]["id"]), caption=f"{kind} · {ph[kind]['server_ts'][11:19]}", width="stretch"
                            )


@st.fragment(run_every=1)
def live() -> None:
    try:
        all_jobs = platform.jobs()
    except platform.PlatformError as e:
        ui.html(theme.banner(theme.esc(e.message), "red", "alert"))
        return
    by = {s: [j for j in all_jobs if j["status"] == s] for s in ("offered", "accepted", "in_progress", "done", "unassigned", "new")}
    ui.html(
        theme.tiles(
            [
                theme.tile("Pinging now", str(len(by["offered"])), "waiting for a worker to accept", "alert"),
                theme.tile("Assigned", str(len(by["accepted"]) + len(by["in_progress"])), "accepted or in progress", "user"),
                theme.tile("Done", str(len(by["done"])), "with before/after photo", "check"),
                theme.tile("Needs supervisor", str(len(by["unassigned"]) + len(by["new"])), "no one accepted / manual mode", "flag"),
            ]
        )
    )
    left, right = st.columns([1.55, 1])
    with left:
        ui.html(theme.section("Requests", "Live"))
        if not all_jobs:
            ui.empty("No requests yet. Type one above or press Simulate incoming request.")
        order = ["offered", "unassigned", "new", "accepted", "in_progress", "done"]
        for j in sorted(all_jobs, key=lambda j: (order.index(j["status"]), j["created_at"]))[:25]:
            render_job(j, working)
    with right:
        ui.html(theme.section(f"On shift · {len(working)}", "Workers", "Open jobs and risk band per worker."))
        load: dict[str, int] = {}
        for j in all_jobs:
            who = (
                j.get("assigned_to")
                if j["status"] in ("accepted", "in_progress")
                else j.get("offer_to")
                if j["status"] == "offered"
                else None
            )
            if who:
                load[who] = load.get(who, 0) + 1
        rows = []
        for emp, dpt in sorted(working.items(), key=lambda kv: (kv[1], kv[0]))[:40]:
            pinging = any(j["status"] == "offered" and j.get("offer_to") == emp for j in all_jobs)
            rows.append(
                f'<div class="ss-wrow">{ui.avatar_img(dpt, 34, "ping" if pinging else "")}'
                f'<div style="flex:1"><b>{theme.esc(ui.short_name(emp))}</b><div class="m">{theme.esc(theme.dept_label(dpt))}</div></div>'
                f'{theme.band_chip(bands.get(emp, "low"))}<span class="ss-tag">{load.get(emp, 0)} open</span></div>'
            )
        if rows:
            ui.html('<div class="ss-card" style="padding:10px 14px">' + "".join(rows) + "</div>")


live()


def performance_section() -> None:
    """Performance score per worker (plan 4.1) from the platform API: own-baseline delta, parts, reasons."""
    st.caption("A coaching aid compared with each person's own baseline; not for disciplinary use.")
    days = st.selectbox("Period", [7, 14, 28], index=1, format_func=lambda d: f"Last {d} days", key="perf_days")
    try:
        out = platform.performance(days)
    except platform.PlatformError as e:
        ui.html(theme.banner(theme.esc(e.message), "red", "alert"))
        return
    if not out["workers"]:
        ui.empty("No completed or offered jobs in this period yet.")
        return
    pct = lambda c: None if c.get("value") is None else round(c["value"] * 100)  # noqa: E731
    rows = [
        {
            "Role": ui.avatar_uri(w.get("department")),
            "Employee": ui.short_name(w["employee_id"]),
            "Department": theme.dept_label(w.get("department")),
            "Score": w["score"],
            "Δ vs own baseline": w["delta"],
            "On time %": pct(w["components"]["on_time"]),
            "Speed %": pct(w["components"]["speed"]),
            "Quality %": pct(w["components"]["quality"]),
            "Responsiveness %": pct(w["components"]["responsiveness"]),
            "Reliability %": pct(w["components"]["reliability"]),
            "Jobs": w["completed_jobs"],
            "Reasons": " ".join(w["reasons"]),
            "_ok": w["status"] == "ok",
        }
        for w in out["workers"]
    ]
    df = pd.DataFrame(rows)
    ok = df.pop("_ok")
    grey = lambda r: [("" if ok[r.name] else "color:#9b9a96;background:#f6f6f4")] * len(r)  # noqa: E731
    main = ["Role", "Employee", "Score", "Δ vs own baseline", "Reasons"]
    if not st.toggle("Details", key="perf_details", help="Show each part of the score"):
        df = df[main]
    st.dataframe(
        df.style.apply(grey, axis=1).format(
            {
                "Score": lambda v: "insufficient data" if pd.isna(v) else f"{v:.1f}",
                "Δ vs own baseline": lambda v: "" if pd.isna(v) else f"{v:+.1f}",
            },
            na_rep="",
        ),
        hide_index=True,
        width="stretch",
        column_config={"Role": st.column_config.ImageColumn("Role", width="small"), "Reasons": st.column_config.TextColumn(width="large")},
    )
    w = out["weights"]
    st.caption(
        f"Weights: on-time {w['on_time']:.0%}, speed {w['speed']:.0%}, quality {w['quality']:.0%}, responsiveness "
        f"{w['responsiveness']:.0%}, reliability {w['reliability']:.0%}. Quality is left out (weights re-normalised) when no "
        f"cleaning job was inspected. Fewer than {out['min_jobs']} completed jobs = insufficient data (greyed). Thresholds are "
        "ASSUMED starting points. SYNTHETIC demo data."
    )


with st.expander("Performance (coaching aid)"):
    performance_section()
ui.footer()
