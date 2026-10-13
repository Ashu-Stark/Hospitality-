"""Today: the manager's home. A photo header, 4-6 big numbers with one-line meanings, a short "do next" list with
one-click actions, and nothing else (routed from app.py). Works in hotel and homestay mode (plain words in homestay)."""

import streamlit as st

from lib import auth, data, nav, platform, portal, tenancy, theme, today, ui

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
logo = portal.logo_src({**T, "logo_url": prof.get("logo_url") or (T.get("logo_url") if not HOMESTAY else None)})
name = prof.get("display_name") or prop.get("name") or T.get("name", "")
greet = "Good to see you" if HOMESTAY else "Today at a glance"
style = f"background-image:linear-gradient(90deg,rgba(8,18,34,.78),rgba(8,18,34,.25)),url('{cover_src}')" if cover_src else ""
ui.html(
    f'<div class="ss-photohead" style="{style}">'
    + (f'<img class="logo" src="{theme.esc(logo)}" alt="">' if logo else "")
    + f'<div><div class="eyebrow">{theme.esc(greet)} · {"Homestay" if HOMESTAY else "Hotel"} mode</div>'
    f"<h1>{theme.esc(name)}</h1></div></div>"
    + (f'<div class="ss-credit">{theme.esc(prof.get("cover_photo_credit") or "")}</div>' if cover_src else "")
)
_pp, _ = st.columns([1, 2])
with _pp:
    ui.property_picker(key="prop_pick_today", label="Looking at")

# ------------------------------------------------------------------ big numbers
d = today.gather()
s = d.get("summary") or {}
to_clean = (s.get("dirty", 0) + s.get("cleaning", 0) + s.get("inspection", 0)) if s else None
reqs, late, low = d.get("requests"), d.get("jobs_late"), d.get("low_stock")


def tone(v, warn_at: int = 1, bad_at: int = 3) -> str:
    if v is None:
        return "info"
    k = len(v) if isinstance(v, list) else int(v)
    return "bad" if k >= bad_at else "warn" if k >= warn_at else "ok"


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

nums = [
    (
        "Rooms ready",
        s.get("ready", "—") if s else "—",
        f"{to_clean} more to clean or check" if to_clean else "Nothing waiting to be cleaned",
        "ok",
    ),
    ("Guest requests open", today.n(reqs), "Waiting for someone to finish them" if reqs else "No guest is waiting", tone(reqs, 1, 4)),
    (
        "Tasks running late" if HOMESTAY else "Jobs late",
        today.n(late),
        "Past their target time" if late else "Everything on time",
        tone(late, 1, 2),
    ),
    (
        "Team today" if HOMESTAY else "Staff on shift",
        today.n(d.get("on_shift")),
        "Your whole team (no roster needed)" if HOMESTAY else "Working right now (from the roster)",
        "info",
    ),
    ("Low stock", today.n(low), "Items at or below their reorder level" if low else "Stock is fine", tone(low, 1, 4)),
]
if checkin or not HOMESTAY:
    nums.append(
        (
            "People to check in with",
            str(len(checkin)),
            "A friendly chat may help (support, not discipline)" if checkin else "No one flagged this week",
            "warn" if checkin else "ok",
        )
    )
ui.big_numbers(nums)

# ------------------------------------------------------------------ do next (one click each)
todo: list[tuple[str, str, str, str, object]] = []  # (title, why, button label, key, action)
for a in d.get("urgent") or []:  # safety / medical alerts from guests come first
    todo.append(
        (
            f"URGENT · room {a['room']}: {a['title']}",
            f"Open {a.get('minutes_open', 0)} min. Go now or send the duty manager.",
            "Open",
            f"act_urgent_{a['id']}",
            "pages/17_Guest_Services.py",
        )
    )
for r in d.get("staffing_pending") or []:
    todo.append(
        (
            f"Staff request not sent yet: {r['openings']} × {theme.dept_label(r['department'])}",
            r.get("last_error") or "The tourism portal did not get it yet.",
            "Send again",
            f"act_staff_{r['id']}",
            lambda rid=r["id"]: platform.resend_staffing_request(rid),
        )
    )
seen_titles: set[str] = set()
for j in d.get("waiting_jobs") or []:
    if j["title"] in seen_titles or len(seen_titles) >= 3:  # one row per request (a request can go to two teams)
        continue
    seen_titles.add(j["title"])
    todo.append(
        (
            f"Nobody has taken: {j['title']}",
            "Offer it again to whoever is free.",
            "Offer again",
            f"act_retry_{j['id']}",
            lambda jid=j["id"]: platform.retry(jid),
        )
    )
if d.get("late_checkouts"):
    todo.append(
        (
            f"{d['late_checkouts']} late checkout request(s)",
            "A guest is waiting for your yes or no.",
            "Decide",
            "act_late",
            "pages/17_Guest_Services.py",
        )
    )
if reqs:
    oldest = max(reqs, key=lambda q: q.get("minutes_open") or 0)
    todo.append(
        (
            f"Guest request: {oldest['title']} (room {oldest['room']})",
            f"Open for {int(oldest.get('minutes_open') or 0)} min.",
            "See requests",
            "act_reqs",
            "pages/17_Guest_Services.py",
        )
    )
if s.get("inspection"):
    todo.append(
        (
            f"{s['inspection']} room(s) waiting for inspection",
            "Pass them so they can be sold.",
            "Inspect rooms",
            "act_insp",
            "pages/14_Rooms.py",
        )
    )
if low:
    todo.append(
        (
            f"Low stock: {', '.join(i['name'] for i in low[:3])}" + (" …" if len(low) > 3 else ""),
            "Reorder before you run out.",
            "Open stock",
            "act_stock",
            "pages/13_Inventory.py",
        )
    )
if checkin and not HOMESTAY:
    todo.append(
        (
            f"Check in with {', '.join(ui.short_name(e) for e in checkin[:3])}",
            "Ask how they are doing; offer support.",
            "See check-ins",
            "act_checkin",
            "pages/2_Risk_List.py",
        )
    )
elif checkin:
    todo.append((f"{', '.join(checkin)} has a lot on", "Ask if they need a hand.", "See team", "act_team", "pages/19_Staff.py"))

visible = {f for f, _, _ in st.session_state.get("_nav", [])}
todo = [t for t in todo if not isinstance(t[4], str) or t[4] in visible][:5]
ui.html('<h3 class="ss-h3">Do next</h3>')
if not todo:
    ui.html(theme.banner("<b>All clear.</b> Nothing needs you right now.", "blue", "check"))
for title, why, label, key, action in todo:
    a, b = st.columns([4, 1.3], vertical_alignment="center")
    a.markdown(f'<div class="ss-donext"><b>{theme.esc(title)}</b><span>{theme.esc(why)}</span></div>', unsafe_allow_html=True)
    with b:
        if st.button(label, key=key, type="primary", width="stretch"):
            if isinstance(action, str):
                st.switch_page(nav.page(action))
            try:
                action()
                st.toast("Done")
            except platform.PlatformError as e:
                st.toast(e.message)
            data.clear()
            st.rerun()
