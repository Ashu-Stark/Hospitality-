"""Extra staff: ask the tourism portal's staffing partners for people when the roster is short, and follow each request.
The request carries a department/skill, dates and a head count only (no personal data). If sending fails the request
stays "Not sent yet" with a Send again button."""

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from lib import platform, theme, timefmt, today, ui

ui.setup("pages/20_Extra_Staff.py", "Extra staff")
ui.page_head(
    "Extra staff", "Ask local staffing partners (through the Uttarakhand tourism portal) for people when your shift plan is short."
)
DEPTS = ["housekeeping", "front_office", "fnb_service", "kitchen", "maintenance", "security"]
STATUS = {"sent": ("Sent to the portal", "low"), "pending_send": ("Not sent yet", "watch")}


def request_form(prefill: dict | None = None, key: str = "stf") -> None:
    """The 'Request staff' form (also opened from the Roster page with the short department and dates filled in)."""
    p = prefill or {}
    with st.form(key, border=False):
        a, b = st.columns(2)
        dept = a.selectbox(
            "Department", DEPTS, index=DEPTS.index(p["department"]) if p.get("department") in DEPTS else 0, format_func=theme.dept_label
        )
        openings = b.number_input("How many people", 1, 50, int(p.get("openings") or 1))
        c, e = st.columns(2)
        d0 = c.date_input("From", value=date.fromisoformat(p["date_from"]) if p.get("date_from") else date.today() + timedelta(days=1))
        d1 = e.date_input("To", value=date.fromisoformat(p["date_to"]) if p.get("date_to") else date.today() + timedelta(days=3))
        skill = st.text_input("Skill (optional)", value=p.get("skill") or "", max_chars=60, placeholder="e.g. room cleaning, tandoor")
        note = st.text_area(
            "Note for the partner (optional)", value=p.get("note") or "", max_chars=500, placeholder="No names or phone numbers"
        )
        if st.form_submit_button("Request staff", type="primary", icon=":material/group_add:", width="stretch"):
            try:
                r = platform.create_staffing_request(
                    department=dept,
                    openings=int(openings),
                    date_from=d0.isoformat(),
                    date_to=d1.isoformat(),
                    skill=skill,
                    note=note,
                    source=p.get("source", "manual"),
                )
                st.session_state.pop("staffing_prefill", None)
                sent = r["status"] == "sent"
                ui.flash("Sent to the tourism portal." if sent else "Saved. Not sent yet: " + (r.get("last_error") or ""), ok=sent)
                st.rerun()
            except platform.PlatformError as ex:
                st.error(ex.message)


rows = ui.api(platform.staffing_requests, what="load staffing requests", feature="staffing requests")
rows = rows if isinstance(rows, list) else []
pending = [r for r in rows if r["status"] == "pending_send"]
ui.big_numbers(
    [
        ("Requests", len(rows), "Made from this property", "info"),
        ("Not sent yet", len(pending), "Press Send again below" if pending else "All delivered", "warn" if pending else "ok"),
        ("People asked for", sum(r["openings"] for r in rows), "Across all requests", "info"),
    ]
)

pre = st.session_state.get("staffing_prefill")
with st.expander("Request staff", expanded=bool(pre) or not rows):
    if pre:
        gap = pre.get("gap_day") or pre["date_from"]
        st.caption(
            f"Filled in from the shift plan: {theme.dept_label(pre['department'])} is short on {gap}."
            + (" The tourism portal takes requests up to 180 days ahead, so the dates are in the coming week." if gap != pre["date_from"] else "")
        )
    request_form(pre)

for r in pending:  # one clear action per card
    a, b = st.columns([4, 1.3], vertical_alignment="center")
    a.markdown(
        f'<div class="ss-donext"><b>{r["openings"]} × {theme.esc(theme.dept_label(r["department"]))} · {r["date_from"]} to {r["date_to"]}</b>'
        f"<span>{theme.esc(r.get('last_error') or 'Not delivered yet.')}</span></div>",
        unsafe_allow_html=True,
    )
    if b.button("Send again", key=f"act_resend_{r['id']}", type="primary", width="stretch"):
        with st.spinner("Sending… the tourism portal can take up to a minute to wake up."):
            try:
                ui.flash(*today.action_result(platform.resend_staffing_request(r["id"])))
            except platform.PlatformError as ex:
                ui.flash(ex.message, ok=False)
        st.rerun()

if rows:
    df = pd.DataFrame(
        [
            {
                "Status": STATUS.get(r["status"], (r["status"], ""))[0],
                "Department": theme.dept_label(r["department"]),
                "People": r["openings"],
                "Dates": f"{r['date_from']} → {r['date_to']}",
                "Skill": r.get("skill") or "",
                "Portal number": r.get("portal_ref") or "",
                "Tries": r.get("attempts"),
                "From": "roster" if r.get("source") == "roster_shortage" else "manual",
                "Created": timefmt.stamp(r.get("created_at")),
            }
            for r in rows
        ]
    )
    ui.html('<h3 class="ss-h3">All requests</h3>')
    ui.table(df, ["Status", "Department", "People", "Dates"], key="stf_tbl")
st.caption(
    "Your portal key is saved in Settings and is never shown. Requests contain no personal details. "
    "The tourism portal is an HOI project, not a government website."
)
ui.footer()
