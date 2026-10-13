"""Work log: what the team finished on one day, how long each job took, how long it waited, and the photo proof.

Reads GET /dispatch/worklog (owner / hr / dept_head; a department head gets their own department only). Times are the
staff app's job stamps (accept, Start, Done; server clock), not attendance: HOI has no clock-in / clock-out. Staff are
shown by employee id and role only. In the demo hotel every value is SYNTHETIC.
"""

import base64
import io
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st
from PIL import Image

from lib import auth, nav, platform, tenancy, theme, ui

ui.setup("pages/21_Work_Log.py", "Work log")
ui.page_head("Work log", "What your team finished on a day, how long each job took, and the photos.")
HEAD = auth.role() == "dept_head"
LOCAL = timezone(timedelta(minutes=330))  # hotel local time (India); the API uses the same default
answer_slot = st.container()  # the answer line goes first, above the filters

c1, c2, c3 = st.columns([1, 1, 1])
with c1:
    today = datetime.now(LOCAL).date()
    day = st.date_input("Day", value=today, max_value=today, format="DD/MM/YYYY", key="wl_day")
with c3:
    if HEAD:
        dept = None  # the API scopes a department head to their own department
    else:
        opts = ["", *theme.DEPT_LABEL]
        dept = st.selectbox("Department", opts, format_func=lambda d: theme.dept_label(d) if d else "All departments", key="wl_dept")

base = ui.api(platform.worklog, day.isoformat(), department=dept or None, what="load the work log")
if not isinstance(base, dict):
    st.stop()
with c2:
    ids = [p["employee_id"] for p in base["people"]]
    who = st.selectbox("Staff", ["", *sorted(ids)], format_func=lambda e: e or "Everyone", key="wl_who")
out = ui.api(platform.worklog, day.isoformat(), who, dept or None, what="load the work log") if who else base
if not isinstance(out, dict):
    st.stop()
if HEAD:
    st.caption(f"Your department: {theme.dept_label(out.get('department'))}")


def mins(v) -> str:
    if v is None:
        return "—"
    if v < 1:
        return "under 1 min"
    v = round(v)
    return f"{v // 60} h {v % 60} min" if v >= 60 else f"{v} min"


def hhmm(iso: str | None) -> str:
    return iso[11:16] if iso else ""


s = out["summary"]
day_txt = "today" if day == today else day.strftime("%a %d %b")
with answer_slot:
    if s["jobs"]:
        ui.verdict(
            0,
            ok_text=f"{s['jobs_done']} job{'s' if s['jobs_done'] != 1 else ''} done {day_txt} · {mins(s['total_work_minutes'])} of work · "
            f"{s['jobs_with_photos']} with photo proof.",
        )
    else:
        ui.empty(f"No jobs {day_txt}{' for ' + who if who else ''}.")

lw = s["longest_wait_minutes"]
ui.big_numbers(
    [
        ("Jobs done", s["jobs_done"], f"of {s['jobs']} job{'s' if s['jobs'] != 1 else ''} on this day", "ok"),
        ("Average time per job", mins(s["avg_work_minutes"]), "from Start to Done in the staff app", "info"),
        (
            "Jobs with photo proof",
            f"{s['jobs_with_photos']} of {s['jobs_done']}",
            "a before or after photo",
            "ok" if s["jobs_done"] and s["jobs_with_photos"] == s["jobs_done"] else "info",
        ),
        ("Longest wait", mins(lw), "before someone took a job", "warn" if lw and lw > 15 else "ok"),
    ]
)

# ------------------------------------------------------------------ per person
if out["people"]:
    ui.html(theme.section("Each person", "People", "Ids and roles only."))
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Role": ui.avatar_uri(p.get("department")),
                    "Staff ID": p["employee_id"],
                    "Jobs done": p["jobs_done"],
                    "Total minutes": round(p["total_work_minutes"] or 0),
                    "Median minutes": None if p["median_work_minutes"] is None else round(p["median_work_minutes"]),
                    "With photo": p["jobs_with_photos"],
                }
                for p in out["people"]
            ]
        ),
        hide_index=True,
        width="stretch",
        column_config={"Role": st.column_config.ImageColumn("Role", width="small")},
    )


# ------------------------------------------------------------------ job list: one plain sentence per job + photos
@st.cache_data(max_entries=400, show_spinner=False)
def _pics(tid: str, pid: str) -> tuple[str, str] | None:
    """(thumbnail, larger) JPEG data URIs of one stamped photo. Photos never change once taken, so they are cached."""
    try:
        img = Image.open(io.BytesIO(platform.photo_bytes(pid))).convert("RGB")
    except (platform.PlatformError, OSError):
        return None

    def uri(side: int, q: int) -> str:
        c = img.copy()
        c.thumbnail((side, side))
        b = io.BytesIO()
        c.save(b, "JPEG", quality=q)
        return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()

    return uri(160, 70), uri(720, 78)


def photo(pid: str | None, kind: str) -> str:
    p = _pics(tenancy.active().get("id") or "", pid) if pid else None
    if not p:
        return ""
    return (
        f'<details class="wl-ph"><summary><img src="{p[0]}" alt="{kind} photo" width="64" height="64"><span>{kind}</span></summary>'
        f'<img class="big" src="{p[1]}" alt="{kind} photo, larger"></details>'
    )


def sentence(j: dict) -> str:
    who, title, room = j.get("assigned_to"), j.get("title") or "a job", j.get("room")
    where = f" in room {room}" if room else ""
    if j["status"] == "done":
        what = f"cleaned room {room}" if j.get("kind") == "cleaning" and room else f"did “{title}”{where}"
        head = f"{who} {what}"
    elif j["status"] == "in_progress":
        head = f"{who} is working on “{title}”{where}"
    elif j["status"] == "accepted":
        head = f"{who} took “{title}”{where}, not started yet"
    else:
        head = f"“{title}”{where} is waiting for someone"
    m = j["minutes"]
    bits = [
        f"started {hhmm(j.get('started_at'))}" if j.get("started_at") else "",
        f"took {mins(m['work'])}" if m["work"] is not None else "",
        f"waited {mins(m['wait'])}" if m["wait"] is not None else "",
    ]
    return " · ".join([head, *[b for b in bits if b]])


if out["jobs"]:
    ui.html(theme.section("Jobs", "Day", "Tap a photo to see it bigger; tap outside it to close."))
    rows = ui.paginate(out["jobs"], key="wl_page", per_page=20)
    html = []
    for j in rows:
        pics = photo(j["photos"].get("before"), "before") + photo(j["photos"].get("after"), "after")
        html.append(
            f'<div class="wl-row s-{theme.esc(j["status"])}">{ui.avatar_img(j.get("department"), 32)}'
            f'<div class="wl-t">{theme.esc(sentence(j))}<div class="m">{theme.esc(theme.dept_label(j.get("department")))}'
            f" · job created {hhmm(j.get('created_at'))}</div></div>"
            f'<div class="wl-pics">{pics}</div></div>'
        )
    ui.html('<div class="wl-list">' + "".join(html) + "</div>")

    # ------------------------------------------------------------------ CSV of the whole day (all rows, not just this page)
    csv = pd.DataFrame(
        [
            {
                "date": out["date"],
                "job_id": j["id"],
                "title": j["title"],
                "kind": j.get("kind"),
                "room": j.get("room"),
                "department": j.get("department"),
                "staff_id": j.get("assigned_to"),
                "status": j["status"],
                "created": hhmm(j.get("created_at")),
                "accepted": hhmm(j.get("accepted_at")),
                "started": hhmm(j.get("started_at")),
                "done": hhmm(j.get("done_at")),
                "wait_min": j["minutes"]["wait"],
                "response_min": j["minutes"]["response"],
                "work_min": j["minutes"]["work"],
                "total_min": j["minutes"]["total"],
                "before_photo_id": j["photos"].get("before"),
                "after_photo_id": j["photos"].get("after"),
                "data": "SYNTHETIC demo" if tenancy.active().get("is_demo") else "",
            }
            for j in out["jobs"]
        ]
    ).to_csv(index=False)
    st.download_button("Download this day (CSV)", csv, file_name=f"work_log_{out['date']}.csv", mime="text/csv", icon=":material/download:")

st.caption(
    "Times come from the staff app: when a job was taken, Start and Done. They are not attendance (there is no clock-in). "
    "Photos carry the server's time stamp." + (" SYNTHETIC demo data." if tenancy.active().get("is_demo") else "")
)
nav.link("pages/10_Dispatch.py", "Live jobs", ":material/bolt:")
ui.html("""<style>
.wl-list { display:flex; flex-direction:column; gap:8px; }
.wl-row { background:#fff; border-radius:16px; padding:10px 14px; display:flex; gap:12px; align-items:center; border-left:4px solid var(--line); }
.wl-row.s-done { border-left-color:#62d36b; } .wl-row.s-in_progress { border-left-color:#c9bbf6; } .wl-row.s-accepted { border-left-color:#f2cd6f; }
.wl-row .ss-ravatar { border-radius:999px; flex:none; }
.wl-t { flex:1; min-width:0; font-size:1rem; } .wl-t .m { color:var(--muted); font-size:.8rem; margin-top:2px; }
.wl-pics { display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end; }
.wl-ph summary { list-style:none; cursor:pointer; display:flex; flex-direction:column; align-items:center; gap:2px; font-size:.7rem; color:var(--muted); }
.wl-ph summary::-webkit-details-marker { display:none; }
.wl-ph summary img { width:64px; height:64px; object-fit:cover; border-radius:10px; display:block; }
/* tap a thumbnail: the photo opens large over a dimmed page; tap anywhere outside it (the backdrop) to close */
.wl-ph[open] summary::before { content:""; position:fixed; inset:0; background:rgba(11,11,11,.6); z-index:999; cursor:zoom-out; }
.wl-ph .big { display:none; }
.wl-ph[open] .big { display:block; position:fixed; z-index:1000; top:50%; left:50%; transform:translate(-50%,-50%);
  max-width:min(92vw,760px); max-height:88vh; border-radius:16px; box-shadow:0 20px 60px rgba(0,0,0,.45); background:#000; }
@media (max-width:640px) { .wl-row { flex-wrap:wrap; } .wl-pics { justify-content:flex-start; } }
</style>""")
ui.footer()
