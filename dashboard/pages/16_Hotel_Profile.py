"""Hotel profile: the facts the guest concierge answers from (GET/PUT /hotel/profile). Owner + department heads edit;
HR and storekeepers can read it."""

from __future__ import annotations

import math
import re
from datetime import time

import pandas as pd
import streamlit as st

from lib import auth, platform, theme, ui

ui.setup("pages/16_Hotel_Profile.py", "Hotel profile")
CAN_EDIT = auth.role() in ("owner", "dept_head", "platform_admin")
FIELDS = [
    "display_name",
    "welcome",
    "checkin_time",
    "checkout_time",
    "late_checkout",
    "wifi",
    "contacts",
    "amenities",
    "dining",
    "policies",
    "nearby",
    "faq",
    "languages",
]
LANGS = {"en": "English", "hi": "Hindi"}  # what the API accepts today
TABLES = {  # section -> (columns with type, the column a row needs to count)
    "contacts": ({"label": str, "extension": str}, "label"),
    "amenities": ({"name": str, "hours": str, "where": str, "note": str}, "name"),
    "dining": ({"item": str, "price_inr": int, "veg": bool, "hours": str}, "item"),
    "policies": ({"title": str, "text": str}, "title"),
    "nearby": ({"name": str, "distance_note": str, "tip": str}, "name"),
    "faq": ({"q": str, "a": str}, "q"),
}

ui.html(
    theme.section(
        "Hotel profile",
        "Guest concierge",
        "What the guest concierge knows about your hotel: timings, wifi, dining, policies and answers to common questions. "
        "It answers guests only from this page, so keep it accurate.",
    )
)

# ------------------------------------------------------------------ load
try:
    prof = platform.hotel_profile()
except platform.PlatformError as e:
    if platform.feature_missing(e):
        ui.needs_api_banner("the hotel profile")
        ui.footer()
        st.stop()
    if e.status != 404:
        ui.html(theme.banner(f"<b>Could not load the hotel profile.</b> {theme.esc(e.message)}", "red", "alert"))
        ui.footer()
        st.stop()
    prof = {}
    ui.html(theme.banner("No profile yet. Fill in the sections below and save; guests see it straight away.", "blue", "info"))
if isinstance(prof.get("profile"), dict):
    prof = prof["profile"]
if msg := st.session_state.pop("hp_saved", None):
    st.toast(msg, icon=":material/check:")
if not CAN_EDIT:
    ui.html(theme.banner("You can view the profile. The owner and department heads can change it.", "gray", "shield"))

# ------------------------------------------------------------------ summary
SECTIONS = {
    "Welcome": bool(prof.get("welcome")),
    "Timings": bool(prof.get("checkin_time") and prof.get("checkout_time")),
    "Wifi": bool((prof.get("wifi") or {}).get("network")),
    **{k.title(): bool(prof.get(k)) for k in ("contacts", "amenities", "dining", "policies", "nearby")},
    "FAQ": bool(prof.get("faq")),
}
missing = [k for k, ok in SECTIONS.items() if not ok]
ui.html(
    theme.tiles(
        [
            theme.tile("Profile complete", f"{len(SECTIONS) - len(missing)} of {len(SECTIONS)}", "sections filled in", "check"),
            theme.tile("Dining items", str(len(prof.get("dining") or [])), "with prices guests can see", "rupee"),
            theme.tile("FAQ answers", str(len(prof.get("faq") or [])), "questions answered", "info"),
            theme.tile("Last updated", str(prof.get("updated_at") or "never")[:16].replace("T", " "), "saved profile", "clock"),
        ]
    )
)
if missing:
    st.caption("Still empty: " + ", ".join(missing) + ". The concierge says it does not know and offers the front desk instead.")


# ------------------------------------------------------------------ helpers
def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or (isinstance(v, str) and not v.strip())


def frame(section: str) -> pd.DataFrame:
    cols, _ = TABLES[section]
    rows = [r for r in (prof.get(section) or []) if isinstance(r, dict)]
    df = pd.DataFrame([{c: r.get(c) for c in cols} for r in rows], columns=list(cols))
    for c, typ in cols.items():
        if typ is str:
            df[c] = df[c].fillna("").astype(str)
        elif typ is bool:
            df[c] = df[c].fillna(False).astype(bool)
        else:
            df[c] = pd.to_numeric(df[c], errors="coerce").round().astype("Int64")
    return df


def records(section: str, df: pd.DataFrame) -> list[dict]:
    cols, required = TABLES[section]
    out = []
    for r in df.to_dict("records"):
        if _blank(r.get(required)):
            continue  # empty rows from the editor are dropped
        row = {}
        for c, typ in cols.items():
            v = r.get(c)
            if typ is str:
                row[c] = "" if _blank(v) else str(v).strip()
            elif typ is bool:
                row[c] = bool(v) if not _blank(v) and v is not pd.NA else False
            else:
                row[c] = None if v is pd.NA or _blank(v) else int(v)
        out.append(row)
    return out


def editor(section: str, **column_config) -> pd.DataFrame:
    return st.data_editor(
        frame(section),
        key=f"hp_ed_{section}",
        num_rows="dynamic" if CAN_EDIT else "fixed",
        disabled=not CAN_EDIT,
        hide_index=True,
        width="stretch",
        column_config=column_config,
    )


def parse_time(v, default: str) -> time:
    try:
        h, m = str(v or default).split(":")[:2]
        return time(int(h), int(m))
    except (ValueError, TypeError):
        h, m = default.split(":")
        return time(int(h), int(m))


def save(changes: dict, what: str) -> None:
    """PUT the whole profile with this tab's changes; validation messages show right here, under the form."""
    body = {k: prof[k] for k in FIELDS if prof.get(k) is not None}
    body.update(changes)
    try:
        platform.save_hotel_profile(body)
    except platform.PlatformError as e:
        if platform.feature_missing(e):
            ui.needs_api_banner("saving the hotel profile")
        else:
            msg = re.sub(r"(^|; ): ", r"\1", e.message.replace("Value error, ", ""))  # pydantic noise
            st.error(f"Not saved. {msg}", icon=":material/error:")
        return
    st.session_state["hp_saved"] = f"{what} saved. Guests see the change now."
    st.rerun()


def submit(label: str = "Save") -> bool:
    return st.form_submit_button(label, type="primary", icon=":material/save:", disabled=not CAN_EDIT)


T = st.column_config.TextColumn
tabs = st.tabs(["Basics", "Stay & contacts", "Amenities & dining", "Policies & nearby", "FAQ", "What guests see"])

# ------------------------------------------------------------------ basics
with tabs[0], st.form("hp_basics"):
    name = st.text_input("Name guests see", prof.get("display_name") or "", max_chars=120, disabled=not CAN_EDIT)
    welcome = st.text_area(
        "Welcome message",
        prof.get("welcome") or "",
        max_chars=600,
        height=100,
        disabled=not CAN_EDIT,
        placeholder="Namaste! Welcome to ...",
    )
    c1, c2, c3 = st.columns([1, 1, 2])
    cin = c1.time_input("Check-in from", parse_time(prof.get("checkin_time"), "12:00"), step=900, disabled=not CAN_EDIT)
    cout = c2.time_input("Check-out by", parse_time(prof.get("checkout_time"), "11:00"), step=900, disabled=not CAN_EDIT)
    langs = c3.multiselect(
        "Languages the concierge replies in",
        list(LANGS),
        default=[x for x in (prof.get("languages") or ["en", "hi"]) if x in LANGS],
        format_func=LANGS.get,
        disabled=not CAN_EDIT,
    )
    if submit("Save basics"):
        save(
            {
                "display_name": name.strip(),
                "welcome": welcome.strip(),
                "checkin_time": cin.strftime("%H:%M"),
                "checkout_time": cout.strftime("%H:%M"),
                "languages": langs,
            },
            "Basics",
        )

# ------------------------------------------------------------------ stay & contacts
with tabs[1], st.form("hp_stay"):
    wifi = prof.get("wifi") or {}
    late = prof.get("late_checkout") or {}
    st.markdown("**Wifi**")
    w1, w2 = st.columns(2)
    net = w1.text_input("Network name", wifi.get("network") or "", max_chars=64, disabled=not CAN_EDIT)
    hint = w2.text_input(
        "Password hint",
        wifi.get("password_hint") or "",
        max_chars=120,
        disabled=not CAN_EDIT,
        help="Shown to guests. A hint like 'Ask at front desk' is safer than the password.",
    )
    st.markdown("**Late checkout rules**")
    l1, l2, l3 = st.columns([1, 1, 2.4])
    allowed = l1.toggle("Guests can ask", bool(late.get("allowed", True)), disabled=not CAN_EDIT)
    latest = l2.time_input("Latest", parse_time(late.get("latest"), "14:00"), step=1800, disabled=not CAN_EDIT)
    lnote = l3.text_input(
        "Note for guests",
        late.get("note") or "",
        max_chars=200,
        disabled=not CAN_EDIT,
        placeholder="Subject to availability; manager approves",
    )
    st.markdown("**Contacts** (internal extensions only; no personal phone numbers)")
    contacts = editor("contacts", label=T("Desk or service", required=True), extension=T("Extension"))
    if submit("Save stay & contacts"):
        save(
            {
                "wifi": {"network": net.strip(), "password_hint": hint.strip()},
                "late_checkout": {"allowed": allowed, "latest": latest.strftime("%H:%M"), "note": lnote.strip()},
                "contacts": records("contacts", contacts),
            },
            "Stay and contacts",
        )

# ------------------------------------------------------------------ amenities & dining
with tabs[2], st.form("hp_amen"):
    st.markdown("**Amenities**")
    amen = editor(
        "amenities", name=T("Amenity", required=True), hours=T("Hours", help="e.g. 07:00-22:30"), where=T("Where"), note=T("Note")
    )
    st.markdown("**Dining menu** (prices in rupees; the concierge never quotes a price that is not here)")
    dining = editor(
        "dining",
        item=T("Dish", required=True),
        price_inr=st.column_config.NumberColumn("Price (₹)", min_value=0, max_value=100000, step=1, format="₹%d"),
        veg=st.column_config.CheckboxColumn("Veg"),
        hours=T("Served", help="e.g. 07:00-11:00"),
    )
    if submit("Save amenities & dining"):
        save({"amenities": records("amenities", amen), "dining": records("dining", dining)}, "Amenities and dining")

# ------------------------------------------------------------------ policies & nearby
with tabs[3], st.form("hp_pol"):
    st.markdown("**House policies**")
    pol = editor("policies", title=T("Policy", required=True), text=T("What guests should know", width="large"))
    st.markdown("**Nearby places**")
    near = editor("nearby", name=T("Place", required=True), distance_note=T("Distance"), tip=T("Tip", width="large"))
    if submit("Save policies & nearby"):
        save({"policies": records("policies", pol), "nearby": records("nearby", near)}, "Policies and nearby")

# ------------------------------------------------------------------ faq
with tabs[4], st.form("hp_faq"):
    st.caption("Short, factual answers work best. The concierge quotes these and does not make up anything else.")
    faq = editor("faq", q=T("Question", required=True, width="medium"), a=T("Answer", width="large"))
    if submit("Save FAQ"):
        save({"faq": records("faq", faq)}, "FAQ")


# ------------------------------------------------------------------ preview
def preview_html(p: dict) -> str:
    e = theme.esc

    def block(title: str, body: str) -> str:
        return f'<div class="gp-sec"><h4>{e(title)}</h4>{body}</div>' if body else ""

    wifi, late = p.get("wifi") or {}, p.get("late_checkout") or {}
    chips = "".join(
        f'<span class="gp-chip">{e(k)} <b>{e(v)}</b></span>'
        for k, v in (("Check-in", p.get("checkin_time")), ("Check-out", p.get("checkout_time")))
        if v
    )
    if late.get("allowed"):
        chips += f'<span class="gp-chip">Late checkout until <b>{e(late.get("latest") or "")}</b></span>'
    rows = lambda items, fn: "".join(fn(x) for x in items or [] if isinstance(x, dict))  # noqa: E731
    amen = rows(
        p.get("amenities"),
        lambda a: (
            f'<div class="gp-row"><b>{e(a.get("name"))}</b><span>{e(" · ".join(x for x in (a.get("hours"), a.get("where"), a.get("note")) if x))}</span></div>'
        ),
    )
    dine = rows(
        p.get("dining"),
        lambda d: (
            f'<div class="gp-row"><b><i class="gp-veg {"" if d.get("veg") else "non"}"></i>{e(d.get("item"))}</b>'
            f"<span>{e(d.get('hours') or '')}</span><em>{'₹' + format(int(d['price_inr']), ',') if d.get('price_inr') is not None else ''}</em></div>"
        ),
    )
    contacts = rows(
        p.get("contacts"), lambda c: f'<div class="gp-row"><b>{e(c.get("label"))}</b><em>dial {e(c.get("extension"))}</em></div>'
    )
    pol = rows(p.get("policies"), lambda x: f'<div class="gp-row"><b>{e(x.get("title"))}</b><span>{e(x.get("text"))}</span></div>')
    near = rows(
        p.get("nearby"),
        lambda x: (
            f'<div class="gp-row"><b>{e(x.get("name"))}</b><span>{e(" · ".join(y for y in (x.get("distance_note"), x.get("tip")) if y))}</span></div>'
        ),
    )
    faq = rows(p.get("faq"), lambda x: f"<details><summary>{e(x.get('q'))}</summary><p>{e(x.get('a'))}</p></details>")
    wifi_html = (
        f'<div class="gp-row"><b>{e(wifi.get("network"))}</b><span>{e(wifi.get("password_hint") or "")}</span></div>'
        if wifi.get("network")
        else ""
    )
    return (
        """<style>
.gp-phone{max-width:420px;margin:8px auto;background:#fff;border-radius:28px;border:1px solid #e6e5e0;overflow:hidden;
box-shadow:0 10px 30px rgba(0,0,0,.06)}
.gp-head{background:var(--brand,#1f6fe5);color:#fff;padding:22px 20px 18px}.gp-head h3{margin:0;font-size:1.25rem;color:#fff}
.gp-head p{margin:6px 0 0;opacity:.92;font-size:.9rem}.gp-chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}
.gp-chip{background:rgba(255,255,255,.18);border-radius:999px;padding:4px 10px;font-size:.76rem}
.gp-sec{padding:12px 20px;border-top:1px solid #f0efea}.gp-sec h4{margin:0 0 6px;font-size:.78rem;text-transform:uppercase;
letter-spacing:.06em;color:#6b6a65}.gp-row{display:flex;gap:8px;align-items:baseline;padding:5px 0;font-size:.88rem;flex-wrap:wrap}
.gp-row b{font-weight:600}.gp-row span{color:#6b6a65;flex:1;font-size:.8rem}.gp-row em{font-style:normal;font-weight:600;margin-left:auto}
.gp-veg{display:inline-block;width:10px;height:10px;border:1.5px solid #0ca30c;border-radius:2px;margin-right:6px;
background:radial-gradient(circle,#0ca30c 40%,transparent 45%)}.gp-veg.non{border-color:#a3461f;
background:radial-gradient(circle,#a3461f 40%,transparent 45%)}
.gp-sec details{padding:6px 0;font-size:.88rem}.gp-sec summary{cursor:pointer;font-weight:600}.gp-sec details p{margin:4px 0 0;color:#52514e}
</style>"""
        f'<div class="gp-phone"><div class="gp-head"><h3>{e(p.get("display_name") or "Your hotel")}</h3>'
        f"<p>{e(p.get('welcome') or '')}</p><div class='gp-chips'>{chips}</div></div>"
        + block("Wifi", wifi_html)
        + block("Call us", contacts)
        + block("Amenities", amen)
        + block("Dining", dine)
        + block("House policies", pol)
        + block("Nearby", near)
        + block("Questions", faq)
        + (f'<div class="gp-sec" style="color:#6b6a65;font-size:.78rem">{e(late.get("note"))}</div>' if late.get("note") else "")
        + "</div>"
    )


with tabs[5]:
    a, b = st.columns([1.3, 1])
    with a:
        st.caption("The saved profile, as the guest concierge's Explore view shows it. Unsaved edits are not included.")
        ui.html(preview_html(prof))
    with b:
        ui.html(theme.section("Try it as a guest", "QR page"))
        try:
            rooms = [r for r in platform.rooms().get("rooms", []) if r.get("guest_token")]  # tokens are owner-only
        except platform.PlatformError:
            rooms = []
        if rooms:
            rid = st.selectbox(
                "Sample room",
                [r["id"] for r in rooms],
                format_func=lambda i: next(f"Room {r['number']}" for r in rooms if r["id"] == i),
                key="hp_room",
            )
            room = next(r for r in rooms if r["id"] == rid)
            url = f"{platform.public_url()}/guest/?t={room['guest_token']}"
            st.link_button(f"Open the guest page for room {room['number']}", url, icon=":material/open_in_new:", width="stretch")
            st.code(url, language=None)
            st.caption("The same link the room's QR code opens. Needs the platform API running as a service.")
        else:
            st.caption("The owner can open a room's guest page here or print its QR code on the Rooms page.")
ui.footer()
