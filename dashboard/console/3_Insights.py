"""Super-admin insights: how every hotel on HOI is doing (GET /platform/insights?days=). Summary first, then one hotel."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import platform, portal, tenancy, theme, ui

ui.setup("console/3_Insights.py", "Insights")
ui.page_head("Insights", "How each hotel is doing, in a few numbers. Open a hotel for the detail.")

days = st.segmented_control("Period", [7, 30, 90], default=30, format_func=lambda d: f"Last {d} days", key="ins_days") or 30
raw = ui.api(platform.platform_insights, days, what="load portfolio insights", feature="portfolio insights")
if raw in (None, ui.NEEDS_API):
    ui.footer()
    st.stop()


def num(v) -> float | None:
    try:
        return None if v is None or isinstance(v, bool) else float(v)
    except (TypeError, ValueError):
        return None


def as_pct(v) -> float | None:
    """On-time share; the API sends a percentage (0-100)."""
    return num(v)


def norm(h: dict) -> dict:
    p = ui.pick
    rooms, occ = num(p(h, "rooms.total", "rooms")), num(p(h, "occupied_now", "rooms.occupied", "occupancy.occupied"))
    perf = p(h, "performance", "worker_performance", default={})
    perf = perf if isinstance(perf, dict) else {"average": perf}
    return {
        "id": p(h, "tenant_id", "id"),
        "name": p(h, "name", "tenant_name", "display_name", default="(unnamed)"),
        "plan": p(h, "plan", default="—"),
        "status": p(h, "status", default="active"),
        "properties": ui.as_list(h.get("properties"), "items"),
        "rooms": rooms,
        "occupied": occ,
        "occupancy": None if not rooms or occ is None else 100 * occ / rooms,
        "staff": num(p(h, "staff.count", "staff")),
        "active_users": num(p(h, "active_users", "users.active")),
        "jobs": num(p(h, "jobs.count", "jobs_count")),
        "jobs_done": num(p(h, "jobs.done")),
        "on_time": as_pct(p(h, "jobs.on_time_pct", "jobs.on_time_rate", "jobs.on_time", "on_time_pct")),
        "median_completion": num(p(h, "jobs.median_completion_min", "median_completion_min")),
        "requests": num(p(h, "guest_requests.count", "requests.count", "guest_requests")),
        "median_response": num(p(h, "guest_requests.median_response_min", "requests.median_response_min", "median_response_min")),
        "per_day": ui.as_list(p(h, "guest_requests.per_day", "guest_requests.daily", "requests_per_day"), "days"),
        "express": num(p(h, "checkouts.express", "express_checkouts")),
        "late": num(p(h, "checkouts.late_requested", "checkouts.late", "late_checkouts")),
        "fb_count": num(p(h, "feedback.count", "feedback_count")),
        "fb_avg": num(p(h, "feedback.average", "feedback.avg", "feedback_avg")),
        "comments": ui.as_list(p(h, "feedback.last_comments", "feedback.comments", "feedback.latest"), "items"),
        "fb_trend": ui.as_list(p(h, "feedback.by_day", "feedback.trend", "feedback_trend"), "days"),
        "stock_value": num(p(h, "inventory.stock_value", "stock_value")),
        "below_reorder": num(p(h, "inventory.below_reorder", "inventory.items_below_reorder", "below_reorder")),
        "perf_avg": num(p(perf, "average_score", "average", "score")),
        "perf_suppressed": bool(p(perf, "suppressed", default=False)),
        "perf_workers": num(p(perf, "workers_scored", "workers", "count")),
        "last_activity": p(h, "last_activity", "last_activity_at"),
    }


hotels = [norm(h) for h in ui.as_list(raw, "tenants", "hotels", "groups") if isinstance(h, dict)]
tot = (raw.get("totals") or raw.get("portfolio") or {}) if isinstance(raw, dict) else {}


def total(key_paths: tuple[str, ...], field: str) -> float | None:
    v = num(ui.pick(tot, *key_paths))
    if v is not None:
        return v
    vals = [h[field] for h in hotels if h[field] is not None]
    return sum(vals) if vals else None


def weighted(field: str, weight: str) -> float | None:
    pairs = [(h[field], h[weight] or 0) for h in hotels if h[field] is not None]
    w = sum(x for _, x in pairs)
    return sum(v * x for v, x in pairs) / w if w else None


def fmt(v, suffix: str = "", digits: int = 0) -> str:
    return "—" if v is None else f"{v:,.{digits}f}{suffix}"


# ------------------------------------------------------------------ summary
active = sum(1 for h in hotels if h["status"] != "suspended")
rooms_t, occ_t = total(("rooms",), "rooms"), total(("occupied_now", "occupied"), "occupied")
on_time_t = as_pct(ui.pick(tot, "jobs.on_time_pct", "on_time_pct")) or weighted("on_time", "jobs_done")
fb_t = num(ui.pick(tot, "feedback_average", "feedback.average")) or weighted("fb_avg", "fb_count")
ui.big_numbers(
    [
        ("Hotels live", active, f"{len(hotels) - active} paused", "info"),
        ("Rooms full now", fmt(occ_t), f"of {fmt(rooms_t)} rooms" + (f" ({occ_t / rooms_t:.0%})" if rooms_t and occ_t else ""), "info"),
        ("Jobs on time", fmt(on_time_t, "%"), f"{fmt(total(('jobs.count', 'jobs'), 'jobs'))} jobs in {days} days", "ok"),
        ("Guest rating", fmt(fb_t, "★", 1), f"{fmt(total(('feedback',), 'fb_count'))} ratings", "ok"),
    ]
)
if not hotels:
    ui.empty("No hotel groups yet. Onboard one on the Hotels page.")
    ui.footer()
    st.stop()

# ------------------------------------------------------------------ per-hotel table
ui.html(theme.section("Hotels at a glance"))
f1, f2, f3 = st.columns([2, 1.2, 1.6])
needle = f1.text_input("Search", placeholder="Hotel name", key="ins_q")
status_f = f2.segmented_control("Status", ["All", "Active", "Suspended"], default="All", key="ins_status") or "All"
plans = sorted({h["plan"] for h in hotels})
plan_f = f3.multiselect("Plan", plans, default=plans, format_func=lambda p: tenancy.PLANS.get(p, {}).get("label", p), key="ins_plan")
shown = [
    h
    for h in hotels
    if needle.lower() in h["name"].lower()
    and h["plan"] in plan_f
    and (status_f == "All" or (h["status"] == "suspended") == (status_f == "Suspended"))
]
if not shown:
    ui.empty("No hotel matches these filters.")
else:
    df = pd.DataFrame(
        [
            {
                "Hotel": h["name"],
                "Status": "Suspended" if h["status"] == "suspended" else "Active",
                "Plan": tenancy.PLANS.get(h["plan"], {}).get("label", h["plan"]),
                "Rooms": h["rooms"],
                "Occupancy %": h["occupancy"],
                "On-time %": h["on_time"],
                "Request response (median min)": h["median_response"],
                "Feedback (avg / 5)": h["fb_avg"],
                "Items below reorder": h["below_reorder"],
                "Last activity": str(h["last_activity"] or "")[:16].replace("T", " "),
            }
            for h in shown
        ]
    )
    pill = {"Active": f"color:{theme.BAND['low']['fg']};background:{theme.BAND['low']['bg']}"}
    pill["Suspended"] = f"color:{theme.BAND['high']['fg']};background:{theme.BAND['high']['bg']}"
    if not st.toggle("Details", key="ins_details", help="Show plan, on-time, response time, stock and last activity"):
        df = df[["Hotel", "Status", "Rooms", "Occupancy %", "Feedback (avg / 5)"]]
    st.dataframe(
        df.style.map(lambda v: pill.get(v, ""), subset=["Status"])
        .format(
            precision=0,
            na_rep="—",
            subset=[c for c in ("Rooms", "Occupancy %", "On-time %", "Request response (median min)", "Items below reorder") if c in df],
        )
        .format(precision=1, na_rep="—", subset=["Feedback (avg / 5)"]),
        hide_index=True,
        width="stretch",
        height=min(420, 38 + 35 * len(df)),
        column_config={
            "Occupancy %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%"),
        },
    )
    st.download_button(
        "Export (CSV)", df.to_csv(index=False).encode(), f"hoi_insights_{days}d.csv", icon=":material/download:", key="ins_csv"
    )

# ------------------------------------------------------------------ drill-down
ui.html(theme.section("One hotel in detail"))
pool = shown or hotels
ids = [h["id"] for h in pool]
sel = st.selectbox("Hotel", ids, format_func=lambda i: next(h["name"] for h in pool if h["id"] == i), key="ins_pick")
h = next(x for x in pool if x["id"] == sel)
suspended = h["status"] == "suspended"
with st.container(key="card_ins_head"):
    a, b = st.columns([3, 1])
    a.markdown(
        f"<b style='font-size:1.15rem'>{theme.esc(h['name'])}</b> "
        + (theme.band_chip("high", "suspended") if suspended else theme.band_chip("low", "active"))
        + f" <span class='ss-tag'>{theme.esc(tenancy.PLANS.get(h['plan'], {}).get('label', h['plan']))}</span>"
        + f"<div style='color:#6b6a65;font-size:.8rem;margin-top:4px'>Last activity: {theme.esc(str(h['last_activity'] or '—')[:16].replace('T', ' '))}</div>",
        unsafe_allow_html=True,
    )
    portal.open_hotel_control(b, h["id"], disabled=suspended or not h["id"], key="ins_open")
    b.caption(
        "Reactivate on the Hotels page to open it."
        if suspended
        else "Sign in there with your platform account, then choose this hotel (audited)."
    )


def bar_by_day(points: list, value_keys: tuple[str, ...]) -> tuple[list, list]:
    xs, ys = [], []
    for pnt in points:
        if isinstance(pnt, dict):
            xs.append(ui.pick(pnt, "date", "day", "week"))
            ys.append(num(ui.pick(pnt, *value_keys)))
    return xs, ys


t_ops, t_guests, t_staff, t_inv = st.tabs(["Operations", "Guests", "Staff", "Inventory"])
with t_ops:
    ui.html(
        theme.kv(
            [
                ("Rooms", fmt(h["rooms"])),
                ("Occupied now", fmt(h["occupied"]) + (f" ({h['occupancy']:.0f}%)" if h["occupancy"] is not None else "")),
                ("Staff", fmt(h["staff"])),
                ("Active users", fmt(h["active_users"])),
                (f"Jobs ({days} d)", fmt(h["jobs"])),
                ("On time", fmt(h["on_time"], "%")),
                ("Median completion", fmt(h["median_completion"], " min")),
                ("Express / late checkouts", f"{fmt(h['express'])} / {fmt(h['late'])}"),
            ]
        )
    )
    if len(h["properties"]) > 1:
        with st.expander(f"{len(h['properties'])} properties"):
            st.dataframe(pd.json_normalize(h["properties"]), hide_index=True, width="stretch")

with t_guests:
    xs, ys = bar_by_day(h["per_day"], ("count", "requests", "n"))
    if xs and any(y for y in ys if y):
        busiest = max(zip(ys, xs), key=lambda t: t[0] or 0)
        ui.takeaway(
            f"{fmt(sum(y or 0 for y in ys))} guest requests in {days} days; busiest day {str(busiest[1])[:10]} ({fmt(busiest[0])})."
        )
        fig = go.Figure(
            go.Bar(x=xs, y=ys, marker=dict(color="#2a78d6", cornerradius=4), hovertemplate="%{x}<br>%{y} requests<extra></extra>")
        )
        theme.style_fig(fig, 260, legend=False)
        fig.update_layout(margin=dict(t=12))
        fig.update_xaxes(tickformat="%d %b", dtick=86400000 * (1 if len(xs) <= 31 else 7))  # day or week ticks, never hours
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    else:
        ui.empty(f"{fmt(h['requests'])} guest requests in {days} days; no daily breakdown to chart.")
    st.caption(f"Median response: {fmt(h['median_response'], ' min')} from request to a worker accepting.")

    xs, ys = bar_by_day(h["fb_trend"], ("average", "avg", "rating"))
    fbx = st.expander("Feedback trend")
    if xs and any(y is not None for y in ys):
        last = next((y for y in reversed(ys) if y is not None), None)
        first = next((y for y in ys if y is not None), None)
        word = "steady" if first is None or last is None or abs(last - first) < 0.2 else ("up" if last > first else "down")
        fbx.markdown(f"Feedback is **{word}**: average {fmt(h['fb_avg'], ' / 5', 1)} from {fmt(h['fb_count'])} ratings.")
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
        theme.style_fig(fig, 240, legend=False)
        fig.update_layout(margin=dict(t=12))
        fig.update_xaxes(tickformat="%d %b", dtick=86400000 * (1 if len(xs) <= 31 else 7))  # day or week ticks, never hours
        fig.update_yaxes(range=[0.8, 5.2], dtick=1)
        fbx.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    else:
        fbx.caption(f"Feedback: average {fmt(h['fb_avg'], ' / 5', 1)} from {fmt(h['fb_count'])} ratings; no trend to chart yet.")
    if h["comments"]:
        ui.html(theme.section("Latest comments", "In guests' words"))
        for c in h["comments"][:5]:
            c = c if isinstance(c, dict) else {"comment": c}
            ui.html(
                f'<div class="ss-wrow"><span style="color:#fab219;min-width:84px">{ui.stars(c.get("rating"))}</span>'
                f"<div style='flex:1'>{theme.esc(c.get('comment') or c.get('text') or '')}"
                f"<div class='m'>{theme.esc(str(c.get('date') or c.get('created_at') or '')[:10])}</div></div></div>"
            )

with t_staff:
    if h["perf_suppressed"] or (h["perf_avg"] is None and h["perf_workers"] is not None and h["perf_workers"] < 5):
        ui.html(
            theme.banner(
                "<b>Suppressed: fewer than 5 workers.</b> With so few people an average could identify individuals, so it is not shown.",
                "gray",
                "shield",
            )
        )
    elif h["perf_avg"] is None:
        ui.empty("No performance score yet (not enough completed jobs in this period).")
    else:
        ui.html(
            theme.tiles(
                [
                    theme.tile(
                        "Average performance score", f"{h['perf_avg']:.0f} / 100", f"across {fmt(h['perf_workers'])} workers", "trend"
                    ),
                    theme.tile("Staff", fmt(h["staff"]), f"{fmt(h['active_users'])} active app users", "users"),
                ]
            )
        )
        st.caption("A coaching aid averaged over the hotel; individual scores stay inside the hotel's own workspace.")

with t_inv:
    ui.html(
        theme.tiles(
            [
                theme.tile("Stock value", ui.inr(h["stock_value"]), "at last purchase price", "rupee"),
                theme.tile(
                    "Items below reorder",
                    fmt(h["below_reorder"]),
                    "need a purchase order" if h["below_reorder"] else "all stocked",
                    "alert",
                ),
            ]
        )
    )
ui.footer()
