"""Today: the owner's home. It answers "Is everything OK today?" in one line, then five big tiles (guests, rooms to clean,
staff on shift versus needed, guest requests waiting, supplies low), each with one action button, then a short
"also needs you" list. Space for the answer and the tiles is reserved while the numbers load, so nothing jumps.
Works in hotel and homestay mode (plain words in homestay). All demo data is synthetic."""

import streamlit as st

from lib import auth, data, nav, platform, tenancy, theme, today, ui
from lib.i18n import t

ui.setup("home.py", "Today")
T = tenancy.active()
ROLE = auth.role()
HOMESTAY = tenancy.is_homestay()


# ------------------------------------------------------------------ photo header (property photo + logo + name)
prop = tenancy.current_property() or {}
prof = ui.api(platform.hotel_profile, what="load the hotel profile") or {}
prof = prof if isinstance(prof, dict) else {}
cover = prof.get("cover_photo_url") or ""
cover_src = platform.asset_data_uri(cover.replace(".jpg", "_sm.jpg")) if cover.startswith("/shared/photos/") else None
name = prof.get("display_name") or prop.get("name") or T.get("name", "")
style = f"background-image:linear-gradient(90deg,rgba(8,18,34,.78),rgba(8,18,34,.25)),url('{cover_src}')" if cover_src else ""
ui.html(
    f'<div class="ss-photohead" style="{style}">'
    + f'<div><div class="eyebrow">{t("Good to see you · Homestay mode" if HOMESTAY else "Today · Hotel mode")}</div>'
    f"<h1>{theme.esc(name)}</h1></div>"
    + (  # photo credit: a small (i) with the credit on hover, not a visible caption
        f'<span class="ss-photoinfo" title="Photo: {theme.esc(prof.get("cover_photo_credit"))}" aria-label="Photo credit">i</span>'
        if cover_src and prof.get("cover_photo_credit")
        else ""
    )
    + "</div>"
)
ui.html(
    "<style>.ss-photohead{position:relative}.ss-photoinfo{position:absolute;right:12px;bottom:10px;width:18px;height:18px;"
    "border-radius:50%;background:rgba(255,255,255,.75);color:#0b0b0b;font:600 11px/18px serif;text-align:center;cursor:help}</style>"
)
_pp, _ = st.columns([1, 2])
with _pp:
    ui.property_picker(key="prop_pick_today", label=t("Looking at"))

# ------------------------------------------------------------------ reserve the space, then load
answer_slot = st.empty()
tiles_slot = st.empty()
answer_slot.markdown(f'<div class="ss-verdict" style="background:#fff;color:#9b9a96">{t("Checking today…")}</div>', unsafe_allow_html=True)
tiles_slot.markdown(ui.tile_skeleton(5), unsafe_allow_html=True)

d = today.gather()
s = d.get("summary") or {}
reqs, late, low, urgent = d.get("requests"), d.get("jobs_late"), d.get("low_stock"), d.get("urgent") or []
total = s.get("total")
to_clean = (s.get("dirty", 0) + s.get("cleaning", 0) + s.get("inspection", 0)) if s else None
short = [] if HOMESTAY else today.shortfall(d.get("context"))
short_people = sum(r["people"] for r in short)
shift = ((d.get("context") or {}).get("shift") or "").lower()


def go_extra_staff() -> None:
    """Open Extra staff with the biggest gap of this shift filled in (the owner still checks and sends it)."""
    r = short[0]
    day = (d.get("context") or {}).get("day")
    st.session_state["staffing_prefill"] = {
        "department": r["department"],
        "date_from": day,
        "date_to": day,
        "openings": r["people"],
        "note": f"Shift plan short by about {r['hours']:.0f} hours ({shift} shift, {day}).",
        "source": "roster_shortage",
    }
    st.switch_page(nav.page("pages/20_Extra_Staff.py"))


# 1 guests
occ = s.get("occupied")
co = d.get("checkouts_today")
t_guests = {
    "label": t("Rooms with guests"),
    "value": f"{occ} of {total}" if occ is not None and total else "—",
    "meaning": (f"{co} leaving today" if co else t("Nobody has booked a checkout yet")) if co is not None else t("From the room board"),
    "tone": "info",
    "button": t("See rooms"),
    "target": "pages/14_Rooms.py",
    "key": "guests",
}
# 2 rooms to clean
t_clean = {
    "label": t("Rooms to clean or check"),
    "value": "—" if to_clean is None else to_clean,
    "meaning": (f"{s.get('ready', 0)} ready for the next guest" if s else t("Room board not available")),
    "tone": "info" if to_clean is None else ("warn" if to_clean else "ok"),
    "button": t("Check rooms" if s.get("inspection") else "See rooms"),
    "target": "pages/14_Rooms.py",
    "key": "clean",
}
# 3 staff on shift vs needed
on = d.get("on_shift")
if HOMESTAY:
    t_staff = {
        "label": t("Team today"),
        "value": today.n(on),
        "meaning": t("Your whole team"),
        "tone": "info",
        "button": t("Our team"),
        "target": "pages/19_Staff.py",
        "key": "staff",
    }
elif short:
    worst = short[0]
    t_staff = {
        "label": t("Staff on shift") + (f" ({shift})" if shift else ""),
        "value": f"{on} of {on + short_people}" if isinstance(on, int) else "—",
        "meaning": f"Short of {worst['people']} {theme.dept_label(worst['department']).lower()} staff"
        + (f" and {len(short) - 1} more team(s)" if len(short) > 1 else ""),
        "tone": "bad" if short_people >= 3 else "warn",
        "button": t("Ask for extra staff"),
        "target": go_extra_staff if auth.can_open("pages/20_Extra_Staff.py") else "pages/5_Roster.py",
        "key": "staff",
    }
else:
    t_staff = {
        "label": t("Staff on shift") + (f" ({shift})" if shift else ""),
        "value": today.n(on),
        "meaning": t("Enough people for this shift" if on else "Nobody on the shift plan right now"),
        "tone": "ok" if on else "info",
        "button": t("See who"),
        "target": "pages/19_Staff.py",
        "key": "staff",
    }
# 4 guest requests
if reqs:
    oldest = max(reqs, key=lambda q: q.get("minutes_open") or 0)
    req_mean = f"Oldest: room {oldest['room']}, waiting {int(oldest.get('minutes_open') or 0)} min"
else:
    req_mean = t("No guest is waiting" if reqs is not None else "Not available for your role")
t_reqs = {
    "label": t("Guest requests waiting"),
    "value": today.n(reqs),
    "meaning": (f"URGENT in room {urgent[0]['room']}. " if urgent else "") + req_mean,
    "tone": "bad" if urgent else ("info" if reqs is None else "warn" if reqs else "ok"),
    "button": t("See requests"),
    "target": "pages/17_Guest_Services.py",
    "key": "reqs",
    "type": "primary" if urgent else "secondary",
}
# 5 supplies
t_low = {
    "label": t("Supplies running low"),
    "value": today.n(low),
    "meaning": (", ".join(i["name"] for i in low[:2]) + (" …" if len(low) > 2 else ""))
    if low
    else t("Stock is fine" if low is not None else "Not available for your role"),
    "tone": "info" if low is None else ("warn" if low else "ok"),
    "button": t("Order stock" if low else "See stock"),
    "target": "pages/13_Inventory.py",
    "key": "low",
}
tiles = [t_guests, t_clean, t_staff, t_reqs, t_low]

# ------------------------------------------------------------------ the answer
needs = [x for x in tiles if x["tone"] in ("warn", "bad")]
names = {"clean": "rooms to clean", "staff": "staff short", "reqs": "guest requests", "low": "low supplies"}
if urgent:
    answer_slot.markdown(
        f'<div class="ss-verdict warn" style="background:#fdeceb;color:#8a1c1c">{theme.icon("alert", 22)}'
        f"<span>Urgent: room {theme.esc(urgent[0]['room'])}, {theme.esc(urgent[0]['title'])}. Go now or send the duty manager.</span></div>",
        unsafe_allow_html=True,
    )
elif needs:
    with answer_slot.container():
        ui.verdict(
            len(needs), bad_text=t("Mostly fine. Look at: ") + ", ".join(t(names.get(x["key"], x["label"].lower())) for x in needs) + "."
        )
else:
    with answer_slot.container():
        ui.verdict(0, ok_text=t("Yes, everything looks fine today."))
with tiles_slot.container():
    ui.action_tiles(tiles, key="today")

# ------------------------------------------------------------------ also needs you (only what the tiles do not cover)
checkin: list[str] = []  # people to check in with: supportive, never for discipline
if HOMESTAY:
    loads: dict[str, int] = {}
    for j in d.get("open_jobs") or []:
        if j.get("assigned_to"):
            loads[j["assigned_to"]] = loads.get(j["assigned_to"], 0) + 1
    checkin = [e for e, k in loads.items() if k >= 3]  # ASSUMED: 3+ open tasks at once = ask if they need a hand
elif ROLE in ("owner", "hr", "platform_admin"):
    try:
        checkin = [x.employee_id for x in data.scores(ui.week()) if x.band == "high"]
    except Exception:  # noqa: BLE001 - the ML backend may be asleep; the home page still works
        checkin = []

todo: list[tuple[str, str, str, str, object]] = []  # (title, why, button label, key, action)
for r in d.get("staffing_pending") or []:
    todo.append(
        (
            f"Your request for {r['openings']} extra {theme.dept_label(r['department']).lower()} staff has not reached the tourism portal yet.",
            r.get("last_error") or "Send it again.",
            "Send again",
            f"act_staff_{r['id']}",
            lambda rid=r["id"]: platform.resend_staffing_request(rid),
        )
    )
seen_titles: set[str] = set()
for j in d.get("waiting_jobs") or []:
    if j["title"] in seen_titles or len(seen_titles) >= 2:  # one row per request (a request can go to two teams)
        continue
    seen_titles.add(j["title"])
    todo.append(
        (
            today.job_sentence(j),
            today.waiting_sentence(j),
            "Send again",
            f"act_retry_{j['id']}",
            lambda jid=j["id"]: platform.retry(jid),
        )
    )
if late:
    todo.append((*today.late_sentence(late), "See jobs", "act_late_jobs", "pages/10_Dispatch.py"))
if d.get("late_checkouts"):
    todo.append(
        (
            *today.late_checkout_sentence(d["late_checkouts"], d.get("late_checkout_rows")),
            "Decide",
            "act_late",
            "pages/17_Guest_Services.py",
        )
    )
if checkin and not HOMESTAY:
    todo.append(
        (
            today.names_sentence([ui.short_name(e) for e in checkin[:3]] + ([f"{len(checkin) - 3} more"] if len(checkin) > 3 else []))
            + " may need a friendly chat this week.",
            "Ask how they are doing and offer support. It is a check-in, not a warning.",
            "See who",
            "act_checkin",
            "pages/2_Risk_List.py",
        )
    )
elif checkin:
    todo.append(
        (
            f"{today.names_sentence(checkin)} {'has' if len(checkin) == 1 else 'have'} 3 or more jobs at once.",
            "Ask if they need a hand.",
            "See team",
            "act_team",
            "pages/19_Staff.py",
        )
    )

visible = {f for f, _, _ in st.session_state.get("_nav", [])}
todo = [x for x in todo if not isinstance(x[4], str) or x[4] in visible][:4]
if todo:
    ui.html(f'<h3 class="ss-h3">{t("Also needs you")}</h3>')
for title, why, label, key, action in todo:
    a, b = st.columns([4, 1.3], vertical_alignment="center")
    a.markdown(f'<div class="ss-donext"><b>{theme.esc(title)}</b><span>{theme.esc(why)}</span></div>', unsafe_allow_html=True)
    with b:
        if st.button(t(label), key=key, width="stretch"):
            if isinstance(action, str):
                st.switch_page(nav.page(action))
            try:
                action()
                st.toast("Done")
            except platform.PlatformError as e:
                st.toast(e.message)
            data.clear()
            st.rerun()

with ui.details(t("Details: where these numbers come from")):
    st.caption(
        "Rooms: the room board. Guest requests and checkouts: guest services. Staff on shift: the shift plan for this "
        "day and shift; 'needed' adds the hours the plan could not fill, turned into people by that shift's length "
        "(an estimate). Supplies: items at or below their 'order when below' level. Demo hotel data is synthetic."
    )
    ui.big_numbers(
        [
            ("Ready rooms", s.get("ready", "—") if s else "—", "Clean and free", "info"),
            ("Jobs late", today.n(late), "Past their target time", "info"),
            ("Jobs nobody took", today.n(d.get("waiting_jobs")), "Waiting for someone", "info"),
        ]
    )
    if short:
        st.caption(
            "Short this shift: "
            + "; ".join(f"{theme.dept_label(r['department'])} about {r['hours']:.0f} h (about {r['people']} people)" for r in short)
        )
