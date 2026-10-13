import pandas as pd
import streamlit as st

from lib import api_client as api
from lib import data, models, theme, ui
from lib.config import current_settings

ui.setup("pages/4_What_If_Simulator.py", "Try a change")
ui.page_head(
    "Try a change",
    "Change one person's work (for example, more weekends off) and see if they are less likely to leave. A guess, not a promise.",
)

scores = ui.safe(data.scores, ui.week(), what="load the check-in list")
if not scores:
    ui.footer()
    st.stop()
by_id = {s.employee_id: s for s in scores}
names = data.hero_names()
perm = [s.employee_id for s in scores if s.contract_type == "permanent"]
options = [e for e in names if e in perm] + sorted(e for e in perm if e not in names)
mock = current_settings().use_mocks
default = "H901" if mock and "H901" in options else st.session_state.get("selected_employee", "H901")

c1, c2 = st.columns([2, 3])
with c1:
    emp = st.selectbox(
        "Person (permanent staff)", options, index=options.index(default) if default in options else 0, format_func=ui.display_name
    )
with c2:
    if mock:
        ui.html(
            '<div style="height:26px"></div>'
            + theme.banner(
                "Practice data has one example: <b>Sunita, 2 weekends off</b>.",
                "amber",
                "info",
            )
        )
st.caption("Seasonal staff are not here: their group depends on when their contract ends.")


@st.cache_data(ttl=120, show_spinner=False)
def probe(base: str, use_mocks: bool, employee_id: str, week: str | None) -> dict:
    """Ask the ML API which inputs a rescore touches and their current values (protected_weekends_off=1)."""
    return api.rescore_attrition(employee_id, protected_weekends_off=2 if use_mocks else 1, week_start=week)


s = current_settings()
with st.spinner("Reading this person's numbers…"):
    try:
        pr = models.parse_rescore(probe(s.api_base_url, s.use_mocks, emp, ui.week()))
        current_feats = pr.features_before
    except api.ApiError as e:
        current_feats = {}
        ui.html(theme.banner(theme.esc(e.message), "amber", "info"))

# ------------------------------------------------------------------ inputs (from the API schema)
with st.container(key="card_inputs"):
    ui.html('<div style="font-weight:600;font-size:1.1rem;margin-bottom:4px">What do you want to change?</div>')
    pw = st.slider("Weekends off (kept free) this month", 0, 4, 2)
    overrides: dict[str, float] = {}
    if current_feats:
        st.markdown("**Or change these numbers yourself** (leave them as they are to work them out from the weekends off)")
        cols = st.columns(min(3, len(current_feats)))
        for i, (k, v) in enumerate(current_feats.items()):
            with cols[i % len(cols)]:
                hi = max(10.0, float(v) * 2)
                nv = st.number_input(
                    models.pretty(k),
                    min_value=0.0,
                    max_value=hi,
                    value=float(v),
                    step=1.0,
                    key=f"ov_{emp}_{k}",
                    help=f"Now: {v}",
                )
                if nv != float(v):
                    overrides[k] = nv
    go = st.button("See the result", type="primary", icon=":material/refresh:")

hist = st.session_state.setdefault("whatif_history", [])
if go:
    with st.spinner("Working it out…"):
        raw = ui.safe(api.rescore_attrition, emp, overrides or None, pw or None, ui.week(), what="work out the result")
    if raw:
        r = models.parse_rescore(raw)
        hist.insert(0, {"r": r, "pw": pw, "ov": overrides, "mismatch": raw.get("_mock_mismatch")})
        del hist[6:]

# ------------------------------------------------------------------ result
latest = next((h for h in hist if h["r"].employee_id == emp), None)
if latest:
    r = latest["r"]
    if latest["mismatch"]:
        ui.html(
            theme.banner(
                f"Practice data: you asked for {theme.esc(latest['mismatch']['requested'])}; showing the saved example for "
                f"{theme.esc(latest['mismatch']['served'])}.",
                "amber",
                "info",
            )
        )
    ui.html(theme.section("Before and after", "Result", "Chance of leaving in the next 90 days."))
    a, mid, b = st.columns([1, 0.35, 1])
    for col, side, label in ((a, r.before, "Before"), (b, r.after, "After")):
        with col:
            ui.html(
                f'<div class="ss-card"><div style="color:#6b6a65;font-size:.85rem">{label}</div>'
                f'<div style="font-size:2.4rem;font-weight:600;letter-spacing:-.04em">{side.risk:.1%}</div>'
                f'<div style="display:flex;gap:6px;flex-wrap:wrap">{theme.band_chip(side.band)}<span class="ss-tag">place {side.rank} of {side.group_size}</span></div></div>'
            )
    with mid:
        rank_d = (r.after.rank or 0) - (r.before.rank or 0)
        ui.html(
            f'<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:150px;gap:8px">'
            f"{theme.icon('arrow', 28, '#6b6a65')}{theme.delta_chip(r.risk_change * 100, fmt='{:.1f} points')}"
            f'<span class="ss-tag">place {rank_d:+d}</span></div>'
        )
    small = abs(r.risk_change) < 0.02
    ui.html(
        theme.banner(
            f"<b>{'A small change.' if small else 'A clear change.'}</b> The chance moved by {r.risk_change * 100:+.1f} points"
            + (
                f"; group: {theme.BAND[r.before.band]['label']} → {theme.BAND[r.after.band]['label']}."
                if r.before.band != r.after.band
                else "; same group."
            )
            + " This is a guess from past patterns, not a promise.",
            "blue",
            "info",
        )
    )
    if r.features_before or r.features_after:
        keys = sorted(set(r.features_before) | set(r.features_after))
        st.dataframe(
            pd.DataFrame(
                [{"What changed": models.pretty(k), "Before": r.features_before.get(k), "After": r.features_after.get(k)} for k in keys]
            ),
            hide_index=True,
            width="stretch",
        )
elif not hist:
    ui.empty("Choose a change and press See the result.")

if hist:
    ui.html(theme.section("What you tried", "History", "Kept only until you close this tab."))
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Person": ui.display_name(h["r"].employee_id),
                    "Weekends off": h["pw"],
                    "Other changes": ", ".join(f"{models.pretty(k)}={v:g}" for k, v in h["ov"].items()) or "—",
                    "Chance before": f"{h['r'].before.risk:.1%}",
                    "Chance after": f"{h['r'].after.risk:.1%}",
                    "Group": f"{theme.BAND[h['r'].before.band]['label']} → {theme.BAND[h['r'].after.band]['label']}",
                }
                for h in hist
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    if st.button("Clear history", icon=":material/delete:"):
        hist.clear()
        st.rerun()

ui.footer()
