"""Guest services: live guest requests by room, express checkouts, the late-checkout queue and guest feedback
(/guest-services/* on the platform API). Refreshes itself every few seconds like Dispatch."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import auth, platform, theme, ui

ui.setup("pages/17_Guest_Services.py", "Guest services")
REFRESH = 15  # seconds
# the API lets the owner and department heads decide late checkouts (front office / housekeeping heads only)
CAN_DECIDE = auth.role() in ("owner", "dept_head", "platform_admin")
STATUS = {  # job status -> (band tone, label guests' requests show)
    "new": ("watch", "waiting"),
    "offered": ("watch", "finding staff"),
    "unassigned": ("high", "needs supervisor"),
    "accepted": ("low", "accepted"),
    "in_progress": ("low", "in progress"),
    "done": ("unknown", "done"),
}
LATE = {"pending": ("watch", "pending"), "approved": ("low", "approved"), "declined": ("high", "declined")}

ui.html(
    theme.section(
        "Guest services",
        "Front office",
        "Everything guests asked for through the room QR page: requests, express checkouts, late checkout and feedback.",
    )
)

# a single probe decides whether the feature exists on this platform API
first = ui.api(platform.guest_summary, what="load guest services", feature="guest services")
if first in (None, ui.NEEDS_API):
    ui.footer()
    st.stop()


def count(v) -> int | None:
    if isinstance(v, list):
        return len(v)
    try:
        return None if v is None else int(v)
    except (TypeError, ValueError):
        return None


def hhmm(v) -> str:
    s = str(v or "")
    return s[11:16] if "T" in s else s[:5]


@st.fragment(run_every=REFRESH)
def tiles() -> None:
    try:
        s = platform.guest_summary()
    except platform.PlatformError as e:
        ui.html(theme.banner(theme.esc(e.message), "red", "alert"))
        return
    p = ui.pick
    open_n = count(p(s, "open_requests", "requests.open", "open_guest_requests"))
    express = count(p(s, "checkouts_today.count", "express_checkouts_today", "checkouts_today"))
    late = count(p(s, "late_checkouts_pending", "late_pending", "late_checkouts.pending", "pending_late_checkouts"))
    avg = p(s, "feedback_30d.average", "feedback_avg_30d", "feedback.average")
    n_fb = count(p(s, "feedback_30d.count", "feedback_count_30d", "feedback.count"))
    ui.html(
        theme.tiles(
            [
                theme.tile("Open guest requests", "—" if open_n is None else str(open_n), "not done yet", "bed"),
                theme.tile("Express checkouts today", "—" if express is None else str(express), "front office notified", "clock"),
                theme.tile("Late checkout requests", "—" if late is None else str(late), "waiting for your decision", "flag"),
                theme.tile(
                    "Guest feedback (30 days)",
                    "—" if avg is None else f"{float(avg):.1f} / 5",
                    "no ratings yet" if not n_fb else f"from {n_fb} ratings",
                    "check",
                ),
            ]
        )
    )
    st.caption(f"Updates every {REFRESH} seconds.")


tiles()
t_live, t_out, t_late, t_fb = st.tabs(["Live requests", "Checkouts today", "Late checkout queue", "Feedback"])


# ------------------------------------------------------------------ live requests
def guest_requests() -> list[dict] | None:
    s = platform.guest_summary()
    for k in ("requests", "live_requests", "open_requests"):
        if isinstance(s.get(k), list):
            return s[k]
    try:  # summary carries only counts: read guest jobs from dispatch (owner / department heads)
        return [j for j in platform.jobs() if j.get("kind") == "guest" or j.get("source") == "guest"]
    except platform.PlatformError:
        return None


@st.fragment(run_every=REFRESH)
def live() -> None:
    try:
        reqs = guest_requests()
    except platform.PlatformError as e:
        ui.html(theme.banner(theme.esc(e.message), "red", "alert"))
        return
    if reqs is None:
        ui.empty("Your role cannot see individual requests. The owner and department heads see them here and on Dispatch.")
        return
    reqs = [r for r in reqs if r.get("status") != "done"]
    if not reqs:
        ui.empty("No open guest requests. New ones from room QR codes appear here within seconds.")
        return
    by_room: dict[str, list[dict]] = defaultdict(list)
    for r in reqs:
        by_room[str(r.get("room") or r.get("room_number") or "—")].append(r)
    rooms = sorted(by_room, key=lambda k: min(str(x.get("created_at", "")) for x in by_room[k]))
    st.caption(f"{len(reqs)} request{'s' * (len(reqs) != 1)} from {len(rooms)} room{'s' * (len(rooms) != 1)}, oldest first.")
    for room in ui.paginate(rooms, "gs_live_page", per_page=12):
        rows = []
        for r in sorted(by_room[room], key=lambda x: str(x.get("created_at", ""))):
            tone, label = STATUS.get(r.get("status"), ("unknown", str(r.get("status") or "")))
            title = str(r.get("title") or r.get("label") or r.get("type") or "Request").split(" · room")[0]
            who = r.get("assigned_to") or r.get("offer_to")
            rows.append(
                f'<div class="ss-wrow"><div style="flex:1"><b>{theme.esc(title)}</b>'
                f'<div class="m">{theme.esc(hhmm(r.get("created_at")))}'
                + (f" · open {r['minutes_open']} min" if isinstance(r.get("minutes_open"), int) and r.get("status") != "done" else "")
                + (" · express checkout" if r.get("kind") == "guest_checkout" else "")
                + (f" · {theme.esc(theme.dept_label(r.get('department')))}" if r.get("department") else "")
                + (f" · {theme.esc(ui.short_name(who))}" if who and r.get("status") in ("accepted", "in_progress", "done") else "")
                + f"</div></div>{theme.band_chip(tone, label)}</div>"
            )
        ui.html(
            f'<div class="ss-card" style="padding:10px 16px;margin-bottom:8px"><div style="font-size:.75rem;color:#6b6a65">Room</div>'
            f'<b style="font-size:1.15rem">{theme.esc(room)}</b>{"".join(rows)}</div>'
        )


# ------------------------------------------------------------------ checkouts today
@st.fragment(run_every=REFRESH)
def checkouts() -> None:
    day = date.today().isoformat()
    res = ui.api(platform.guest_checkouts, day, what="load today's checkouts", feature="express checkouts")
    if res in (None, ui.NEEDS_API):
        return
    rows = ui.as_list(res, "checkouts", "items")
    if not rows:
        ui.empty("No express checkouts booked for today yet.")
        return
    help_n = sum(1 for r in rows if r.get("luggage_help"))
    st.caption(f"{len(rows)} express checkouts today; {help_n} want help with luggage.")
    df = pd.DataFrame(
        [
            {
                "Time": hhmm(r.get("time")),
                "Room": str(r.get("room") or r.get("room_number") or ""),
                "Luggage help": bool(r.get("luggage_help")),
                "Status": str(r.get("status") or "booked"),
            }
            for r in rows
        ]
    ).sort_values("Time")
    st.dataframe(df, hide_index=True, width="stretch", column_config={"Luggage help": st.column_config.CheckboxColumn()})


# ------------------------------------------------------------------ late checkout queue
@st.fragment(run_every=REFRESH * 2)
def late_queue() -> None:
    res = ui.api(platform.late_checkouts, what="load late checkout requests", feature="late checkout")
    if res in (None, ui.NEEDS_API):
        return
    rows = ui.as_list(res, "late_checkouts", "items", "requests")
    pending = [r for r in rows if r.get("status", "pending") == "pending"]
    decided = [r for r in rows if r.get("status", "pending") != "pending"]
    if not pending:
        ui.empty("No late checkout requests waiting. Guests ask from their room page; you decide here.")
    for r in pending:
        lid = str(r.get("id"))
        with st.container(key=f"card_late_{lid}"):
            a, b = st.columns([2.2, 2])
            a.markdown(
                f"**Room {theme.esc(r.get('room') or r.get('room_number') or '—')}** wants to stay until **{theme.esc(hhmm(r.get('until')))}**  \n"
                + (f"“{theme.esc(r.get('reason'))}”  \n" if r.get("reason") else "")
                + f"<span style='color:#6b6a65;font-size:.8rem'>asked at {theme.esc(hhmm(r.get('created_at')))}</span>",
                unsafe_allow_html=True,
            )
            if not CAN_DECIDE:
                b.caption("The owner or the front office / housekeeping head decides.")
                continue
            with b:
                note = st.text_input(
                    "Note to the guest",
                    key=f"late_note_{lid}",
                    placeholder="e.g. Approved until 13:00",
                    max_chars=200,
                    label_visibility="collapsed",
                )
                c1, c2 = st.columns(2)
                for col, approve, label in ((c1, True, "Approve"), (c2, False, "Decline")):
                    if col.button(label, key=f"late_{label}_{lid}", type="primary" if approve else "secondary", width="stretch"):
                        out = ui.api(
                            platform.decide_late_checkout, lid, approve, note.strip(), what="record the decision", feature="late checkout"
                        )
                        if out not in (None, ui.NEEDS_API):
                            st.toast(f"Late checkout {'approved' if approve else 'declined'}; the guest sees it on their page.")
                            st.rerun()
    if decided:
        with st.expander(f"Decided ({len(decided)})"):
            ui.html(
                "".join(
                    f'<div class="ss-wrow"><b style="min-width:70px">{theme.esc(r.get("room") or r.get("room_number") or "—")}</b>'
                    f'<div style="flex:1">until {theme.esc(hhmm(r.get("until")))}<div class="m">{theme.esc(r.get("note") or "")}</div></div>'
                    f"{theme.band_chip(*LATE.get(r.get('status'), ('unknown', str(r.get('status')))))}</div>"
                    for r in decided[:50]
                )
            )


# ------------------------------------------------------------------ feedback
def feedback() -> None:
    days = st.segmented_control("Period", [7, 30, 90], default=30, format_func=lambda d: f"Last {d} days", key="gs_fb_days") or 30
    res = ui.api(platform.guest_feedback, days, what="load guest feedback", feature="guest feedback")
    if res in (None, ui.NEEDS_API):
        return
    items = ui.as_list(res, "items", "feedback", "entries")
    ratings = [float(i["rating"]) for i in items if isinstance(i.get("rating"), (int, float))]
    avg = ui.pick(res, "average", "avg") if isinstance(res, dict) else None
    avg = float(avg) if avg is not None else (sum(ratings) / len(ratings) if ratings else None)
    if not items and avg is None:
        ui.empty(f"No guest feedback in the last {days} days.")
        return
    trend = ui.as_list(ui.pick(res, "by_day", "trend") if isinstance(res, dict) else None, "days")
    if not trend:  # build a daily average from the items when the API does not send one
        acc: dict[str, list[float]] = defaultdict(list)
        for i in items:
            if isinstance(i.get("rating"), (int, float)):
                acc[str(i.get("created_at") or i.get("at") or "")[:10]].append(float(i["rating"]))
        trend = [{"date": d, "average": sum(v) / len(v), "count": len(v)} for d, v in sorted(acc.items()) if d]
    low = sum(1 for r in ratings if r <= 2)
    ui.html(
        theme.section(
            f"Guests rate their stay {avg:.1f} / 5" if avg is not None else "Guest ratings",
            f"Last {days} days",
            f"{len(items)} ratings" + (f"; {low} of them 2 stars or less: read those first." if low else "."),
        )
    )
    xs = [t.get("date") or t.get("day") for t in trend if isinstance(t, dict)]
    ys = [ui.pick(t, "average", "avg") for t in trend if isinstance(t, dict)]
    if len(xs) >= 2:
        fig = go.Figure(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines+markers",
                line=dict(color="#2a78d6", width=2),
                marker=dict(size=8, color="#2a78d6", line=dict(color="#fff", width=2)),
                hovertemplate="%{x}<br>average %{y:.1f} / 5<extra></extra>",
            )
        )
        theme.style_fig(fig, 220, legend=False)
        fig.update_layout(margin=dict(t=12))
        fig.update_xaxes(tickformat="%d %b", dtick=86400000 * (1 if len(xs) <= 31 else 7))  # day or week ticks, never hours
        fig.update_yaxes(range=[0.8, 5.2], dtick=1, title="average rating")
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    f1, f2 = st.columns([1.2, 2])
    stars = f1.segmented_control("Stars", ["All", "1-2", "3", "4-5"], default="All", key="gs_fb_stars") or "All"
    only_comments = f2.toggle("Only with a comment", value=True, key="gs_fb_comments")
    keep = {"All": range(0, 6), "1-2": range(1, 3), "3": range(3, 4), "4-5": range(4, 6)}[stars]
    shown = [
        i
        for i in sorted(items, key=lambda x: str(x.get("created_at") or x.get("at") or ""), reverse=True)
        if (not only_comments or (i.get("comment") or "").strip()) and round(float(i.get("rating") or 0)) in keep
    ]
    if not shown:
        ui.empty("No feedback matches these filters.")
        return
    ui.html(
        '<div class="ss-card" style="padding:8px 16px">'
        + "".join(
            f'<div class="ss-wrow"><span style="color:#fab219;min-width:84px">{ui.stars(i.get("rating"))}</span>'
            f"<div style='flex:1'>{theme.esc(i.get('comment') or '(no comment)')}"
            f"<div class='m'>{theme.esc(str(i.get('created_at') or i.get('at') or '')[:16].replace('T', ' '))}"
            + (f" · room {theme.esc(i.get('room'))}" if i.get("room") else "")
            + (f" · {theme.esc(i.get('lang'))}" if i.get("lang") else "")
            + "</div></div></div>"
            for i in ui.paginate(shown, "gs_fb_page", per_page=15)
        )
        + "</div>"
    )


with t_live:
    live()
with t_out:
    checkouts()
with t_late:
    late_queue()
with t_fb:
    feedback()
ui.footer()
