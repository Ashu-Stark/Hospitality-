"""Shared context for the employee app: who am I, my department, my shifts, today's operating day/shift."""

from __future__ import annotations

from datetime import date

import streamlit as st

from . import auth, data, models, tenancy, theme, ui


def context() -> dict:
    u = auth.current()
    me = u.get("employee_id") or u["username"]
    t = tenancy.active()
    ro, working, bands, day, shift = data.ops_inputs()
    dept = (ro.dept_of.get(me) if ro else None) or working.get(me)
    mine = sorted([a for a in (ro.assignments if ro else []) if a["employee_id"] == me], key=lambda a: a["date"])
    today = next((a for a in mine if a["date"] == day), None)
    return {
        "me": me,
        "tenant": t,
        "roster": ro,
        "working": working,
        "bands": bands,
        "day": day,
        "shift": shift,
        "dept": dept,
        "my_shifts": mine,
        "today": today,
    }


def header(ctx: dict, subtitle: str) -> None:
    st.markdown("<style>.block-container { max-width: 760px !important; }</style>", unsafe_allow_html=True)
    ui.html(
        f'<div class="ss-phone" style="border-radius:28px;margin-bottom:12px"><div class="ss-phone-head">'
        f'<span class="ss-avatar sm hero">{theme.esc(ui.initials(ctx["me"]))}</span><div><b>Hi, {theme.esc(ui.short_name(ctx["me"]))}</b>'
        f'<div class="m">{theme.esc(theme.dept_label(ctx["dept"]))} · {theme.esc(subtitle)}</div></div></div></div>'
    )


def day_label(d: str) -> str:
    x = date.fromisoformat(d)
    return f"{models.DAY_NAMES[x.weekday()]} {x.day}"
