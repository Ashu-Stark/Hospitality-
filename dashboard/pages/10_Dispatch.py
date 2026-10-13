import random
from datetime import date

import pandas as pd
import streamlit as st

from lib import data, dispatch, models, platform, tenancy, theme, ui

ui.setup("pages/10_Dispatch.py", "Jobs")
cfg = tenancy.active_settings()
SECONDS = int(cfg.get("offer_seconds", 30))

ui.page_head("Jobs", "Each job goes to the best free person on shift. You only step in when nobody takes it.")

ro, working, bands, day0, shift0 = data.ops_inputs()
with st.container(key="card_ops"):
    c1, c2 = st.columns([1.4, 1.3])
    with c1:
        days = ro.dates if ro else []
        day = (
            st.selectbox(
                "Day",
                days,
                index=days.index(day0) if day0 in days else 0,
                format_func=lambda d: f"{models.DAY_NAMES[date.fromisoformat(d).weekday()]} {d}",
            )
            if days
            else None
        )
    with c2:
        shift = st.segmented_control("Shift", models.SHIFT_ORDER, default=shift0, key="ops_shift") or shift0
    c3, c4 = st.expander("Job settings").columns(2)
    with c3:
        auto = st.toggle(
            "Send jobs by themselves",
            value=cfg.get("assign_mode", "auto") == "auto",
            help="On: every new job is sent to someone at once. Off: jobs wait for a supervisor.",
        )
        if auto != (cfg.get("assign_mode", "auto") == "auto"):
            ui.safe(platform.update_workspace, assign_mode="auto" if auto else "manual", what="save job settings")
            tenancy.refresh()
    with c4:
        secs = st.select_slider(
            "Time to say yes", [15, 30, 60, 120], value=SECONDS if SECONDS in (15, 30, 60, 120) else 30, format_func=lambda s: f"{s} s"
        )
        if secs != SECONDS:
            ui.safe(platform.update_workspace, offer_seconds=secs, what="save job settings")
            tenancy.refresh()
            SECONDS = secs
ro, working, bands, day, shift = data.ops_inputs(day, shift)
st.session_state["ops_day"], st.session_state["ops_shift_val"] = day, shift
if not working:
    ui.html(theme.banner("No one is on shift for this day and shift. Make a shift plan, or add staff in Settings.", "amber", "alert"))

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
        title = st.text_input("New job", placeholder="e.g. AC not cooling", key="nr_title")
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
        send = st.button("Send", type="primary", icon=":material/bolt:", width="stretch", disabled=not title)
    s1, s2 = st.columns([1.6, 3.4])
    with s1:
        sim = st.button("Try a guest request", icon=":material/notifications_active:")
    with s2:
        st.caption("We guess the department from the words. You can change it before you send.")
if send and title:
    if ui.safe(platform.create_job, title, dept, room or None, urg, "manual", what="send the job"):
        st.toast("Job sent" if auto else "Job waiting for a supervisor", icon=":material/bolt:")
if sim:
    staffed = set(working.values())
    pool = [s for s in SAMPLES if s[1] in staffed] or SAMPLES
    t, dpt, u = random.choice(pool)
    rm = f"{random.randint(1, tenancy.floors())}{random.randint(1, 12):02d}"
    if ui.safe(platform.create_job, t, dpt, rm, u, "simulated", what="make a practice request"):
        st.toast(f"New: {t} · room {rm}", icon=":material/notifications_active:")


def render_job(j: dict, w: dict) -> None:
    tone, label = {
        "offered": ("watch", "waiting for a yes"),
        "accepted": ("low", "taken"),
        "in_progress": ("low", "in progress"),
        "done": ("low", "done"),
        "unassigned": ("high", "needs supervisor"),
        "new": ("unknown", "waiting"),
    }[j["status"]]
    who = j.get("offer_to") if j["status"] == "offered" else j.get("assigned_to")
    secs = j.get("seconds_left", 0)
    with st.container(key=f"card_job_{j['id']}"):
        a, b = st.columns([3, 1.3])
        with a:
            ping = (
                (
                    f'<div class="ss-ping">{ui.avatar_img(j["department"], 34, "ping")}'
                    f"Sent to <b>{theme.esc(ui.short_name(who))}</b> · {secs} s left"
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
                    f" · done by <b>{theme.esc(ui.short_name(who))}</b>"
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
                    pick = st.selectbox("Send to", opts, key=f"pick_{j['id']}", format_func=ui.short_name, label_visibility="collapsed")
                    if st.button("Send to them", key=f"offer_{j['id']}", width="stretch"):
                        ui.safe(platform.job_action, j["id"], "offer", pick, what="send the job")
                        st.rerun(scope="fragment")
                if st.button("Try again", key=f"retry_{j['id']}", width="stretch"):
                    ui.safe(platform.retry, j["id"], what="try again")
                    st.rerun(scope="fragment")
        if j.get("ranking"):
            with st.expander("Why this person?"):
                st.caption("Fewer open jobs, fewer jobs already done this shift, nearer the room, and not overloaded = picked first.")
                for i, r in enumerate(j["ranking"][:5], 1):
                    p = r["parts"]
                    st.caption(
                        f"{i}. {ui.short_name(r['employee_id'])}: {r['score']} points · open jobs {p['open_jobs']:+d} · "
                        f"fair share {p['done_this_shift']:+d} · distance {p['distance']:+d} (floor {r['floor']}) · "
                        f"go easy {p['retention_guard']:+d}"
                    )
                tried = [f"{ui.short_name(a['employee_id'])}: {a['outcome']}" for a in j.get("attempts", [])]
                if tried:
                    st.caption("Sent to: " + " → ".join(tried))
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
                theme.tile("Waiting for a yes", str(len(by["offered"])), "sent to someone, not taken yet", "alert"),
                theme.tile("Being done", str(len(by["accepted"]) + len(by["in_progress"])), "someone took it", "user"),
                theme.tile("Done", str(len(by["done"])), "with before and after photo", "check"),
                theme.tile("Needs supervisor", str(len(by["unassigned"]) + len(by["new"])), "nobody took it, or sending is off", "flag"),
            ]
        )
    )
    left, right = st.columns([1.55, 1])
    with left:
        ui.html(theme.section("Jobs", "Live"))
        if not all_jobs:
            ui.empty("No jobs yet. Type one above or press Try a guest request.")
        order = ["offered", "unassigned", "new", "accepted", "in_progress", "done"]
        for j in sorted(all_jobs, key=lambda j: (order.index(j["status"]), j["created_at"]))[:25]:
            render_job(j, working)
    with right:
        ui.html(theme.section(f"On shift · {len(working)}", "Workers", "Open jobs for each person."))
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
                f'<span class="ss-tag">{load.get(emp, 0)} open</span></div>'
            )
        if rows:
            ui.html('<div class="ss-card" style="padding:10px 14px">' + "".join(rows) + "</div>")


live()


def performance_section() -> None:
    """Performance score per worker (plan 4.1) from the platform API: own-baseline delta, parts, reasons."""
    st.caption("To help people improve, compared with their own usual work. Not for punishment.")
    days = st.selectbox("Period", [7, 14, 28], index=1, format_func=lambda d: f"Last {d} days", key="perf_days")
    try:
        out = platform.performance(days)
    except platform.PlatformError as e:
        ui.html(theme.banner(theme.esc(e.message), "red", "alert"))
        return
    if not out["workers"]:
        ui.empty("No jobs in this period yet.")
        return
    pct = lambda c: None if c.get("value") is None else round(c["value"] * 100)  # noqa: E731
    rows = [
        {
            "Role": ui.avatar_uri(w.get("department")),
            "Employee": ui.short_name(w["employee_id"]),
            "Department": theme.dept_label(w.get("department")),
            "Score": w["score"],
            "Change vs their usual": w["delta"],
            "On time %": pct(w["components"]["on_time"]),
            "Speed %": pct(w["components"]["speed"]),
            "Room check passed %": pct(w["components"]["quality"]),
            "Says yes quickly %": pct(w["components"]["responsiveness"]),
            "Turns up and finishes %": pct(w["components"]["reliability"]),
            "Jobs": w["completed_jobs"],
            "Why": " ".join(w["reasons"]),
            "_ok": w["status"] == "ok",
        }
        for w in out["workers"]
    ]
    df = pd.DataFrame(rows)
    ok = df.pop("_ok")
    grey = lambda r: [("" if ok[r.name] else "color:#9b9a96;background:#f6f6f4")] * len(r)  # noqa: E731
    main = ["Role", "Employee", "Score", "Change vs their usual", "Why"]
    if not st.toggle("More columns", key="perf_details", help="Show each part of the score"):
        df = df[main]
    st.dataframe(
        df.style.apply(grey, axis=1).format(
            {
                "Score": lambda v: "not enough jobs yet" if pd.isna(v) else f"{v:.1f}",
                "Change vs their usual": lambda v: "" if pd.isna(v) else f"{v:+.1f}",
            },
            na_rep="",
        ),
        hide_index=True,
        width="stretch",
        column_config={"Role": st.column_config.ImageColumn("Role", width="small"), "Why": st.column_config.TextColumn(width="large")},
    )
    w = out["weights"]
    st.caption(
        f"The score is made of: on time {w['on_time']:.0%}, speed {w['speed']:.0%}, room check passed {w['quality']:.0%}, "
        f"says yes quickly {w['responsiveness']:.0%}, turns up and finishes {w['reliability']:.0%}. "
        f"Fewer than {out['min_jobs']} jobs = not enough to judge (shown in grey)."
    )


with st.expander("How people are doing (to help, not to punish)"):
    performance_section()
ui.footer()
