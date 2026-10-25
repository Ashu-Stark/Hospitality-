"""Worker phone UI (ping → accept → before photo → after photo), shared by the manager preview and the employee app.
All state changes go through the platform API; a manager previewing acts *as* a worker (audited server-side)."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from . import api_client as api
from . import auth, platform, theme, timefmt, ui
from .api_client import ApiError


def _as(me: str) -> str | None:
    return None if auth.role() == "worker" else me  # workers act as themselves; managers name the worker


def _mirror_task(job: dict, me: str) -> None:
    """Mirror an accepted job into the ops task board (ML backend), idempotently, and link it."""
    try:
        t = api.create_task(
            f"dispatch:{job['tenant_id']}:{job['id']}",
            job["title"] + (f" (room {job['room']})" if job.get("room") else ""),
            me,
            supervisor=f"{job['department']} supervisor",
            employee_id=me,
            description=f"Job {job['id']}",
            due_in_minutes={"high": 30, "medium": 120, "low": 480}.get(job["urgency"], 120),
        )
        api.ack_task(t.get("id"))
        platform.link_task(job["id"], t.get("id"))
    except (ApiError, platform.PlatformError):
        pass  # the job itself is accepted; the task board mirror is best-effort


def phone(me: str, dept: str | None, shift: str, seconds: int, allow_upload: bool = False) -> None:
    ui.html(
        '<div class="ss-phone"><div class="ss-phone-notch"></div>'
        f'<div class="ss-phone-head"><span class="ss-avatar sm hero">{theme.esc(ui.initials(me))}</span><div><b>{theme.esc(ui.short_name(me))}</b>'
        f'<div class="m">{theme.esc(theme.dept_label(dept))} · {theme.esc(shift)} shift</div></div></div></div>'
    )

    @st.fragment(run_every=1)
    def offers() -> None:
        try:
            mine = [j for j in platform.jobs("offered", worker=_as(me)) if j["offer_to"] == me]
        except platform.PlatformError as e:
            ui.html(theme.banner(theme.esc(e.message), "red", "alert"))
            return
        if not mine:
            ui.html('<div class="ss-phone-empty">No new jobs. They will show up here.</div>')
            return
        j = mine[0]
        s = j.get("seconds_left", 0)
        ui.html(
            f'<div class="ss-offer ss-anim"><div class="ss-ring"><span>{s}</span></div>'
            f'<div class="t">New job</div><div class="big">{theme.esc(j["title"])}</div>'
            f'<div class="m">{"room " + theme.esc(j["room"]) + " · " if j.get("room") else ""}{theme.esc(j["urgency"])} priority</div>'
            f'<div class="ss-countdown"><i style="width:{100 * s / max(1, seconds):.0f}%"></i></div></div>'
        )
        a, b = st.columns(2)
        if a.button("Decline", key=f"dec_{j['id']}", width="stretch"):
            ui.safe(platform.job_action, j["id"], "decline", _as(me), what="decline")
            st.rerun()
        if b.button("Accept", key=f"acc_{j['id']}", type="primary", width="stretch"):
            job = ui.safe(platform.job_action, j["id"], "accept", _as(me), what="accept")
            if job:
                _mirror_task(job, me)
            st.rerun()

    offers()
    try:
        active = platform.jobs("accepted,in_progress", worker=_as(me))
    except platform.PlatformError:
        active = []
    for j in [j for j in active if j.get("assigned_to") == me]:
        with st.container(key=f"card_wjob_{j['id']}"):
            ph = platform.job_photos(j["id"])
            ui.html(
                f'<div style="display:flex;justify-content:space-between;align-items:center"><b>{theme.esc(j["title"])}</b>'
                f"{theme.band_chip('low', j['status'].replace('_', ' '))}</div>"
                f'<div style="color:#6b6a65;font-size:.8rem">{"room " + theme.esc(j["room"]) if j.get("room") else ""}</div>'
            )
            kind = "before" if "before" not in ph else "after"
            st.markdown(f"**{'1 · Photo before you start' if kind == 'before' else '2 · Photo when finished'}**")
            shot = st.camera_input(f"{kind} photo", key=f"cam_{j['id']}_{kind}", label_visibility="collapsed")
            up = st.file_uploader("Upload a photo", type=["jpg", "jpeg", "png"], key=f"up_{j['id']}_{kind}") if allow_upload else None
            src = shot or up
            if src is not None and st.button(f"Send {kind} photo", key=f"sub_{j['id']}_{kind}", type="primary", width="stretch"):
                info = ui.safe(platform.upload_photo, j["id"], kind, src.getvalue(), _as(me), what=f"upload the {kind} photo")
                if info:
                    step = ui.safe(
                        platform.job_action, j["id"], "start" if kind == "before" else "complete", _as(me), what="update the job"
                    )
                    if step and kind == "after" and j.get("backend_task_id"):
                        try:
                            api.done_task(j["backend_task_id"])
                        except ApiError:
                            pass
                    st.toast(
                        f"{kind.capitalize()} photo saved at {timefmt.hhmm(info['server_ts'], seconds=True)}",
                        icon=":material/photo_camera:",
                    )
                    st.rerun()
            if "before" in ph:
                st.image(
                    platform.photo_bytes(ph["before"]["id"]),
                    caption=f"before · {timefmt.hhmm(ph['before']['server_ts'], seconds=True)}",
                    width="stretch",
                )


def completed(me: str, limit: int = 5) -> None:
    try:
        done = [j for j in platform.jobs("done", worker=_as(me)) if j.get("assigned_to") == me][:limit]
    except platform.PlatformError:
        done = []
    if not done:
        return
    ui.html(theme.section("Done recently", "Proof"))
    for j in done:
        ph = platform.job_photos(j["id"])
        with st.container(key=f"card_wdone_{j['id']}"):
            st.markdown(f"**{j['title']}** · done {timefmt.hhmm(j['done_at'])}")
            c1, c2 = st.columns(2)
            for col, k in zip((c1, c2), ("before", "after")):
                with col:
                    if k in ph:
                        st.image(platform.photo_bytes(ph[k]["id"]), width="stretch")
                        st.caption(
                            f"{k} · {ph[k]['server_ts'][:19].replace('T', ' ')} · "
                            f"{'photo checked' if ph[k]['verified'] else 'photo was changed'}"
                        )
            if j.get("started_at") and j.get("done_at"):
                mins = (datetime.fromisoformat(j["done_at"]) - datetime.fromisoformat(j["started_at"])).total_seconds() / 60
                st.caption(f"Time on the job (before to after photo): {mins:.0f} min")
