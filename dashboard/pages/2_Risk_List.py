import pandas as pd
import streamlit as st

from lib import charts, data, theme, ui

ui.setup("pages/2_Risk_List.py", "Risk list")
ui.page_head(
    "People to check in with",
    "A ranking for supportive conversations this week. It is not a prediction that anyone will leave, and never grounds for action against them.",
)

scores = ui.safe(data.scores, ui.week(), what="score employees")
if scores is None:
    ui.footer()
    st.stop()
if not scores:
    ui.empty("The backend returned no scores for this week.")
    ui.footer()
    st.stop()

depts = data.dept_map()


# ------------------------------------------------------------------ summary first
n_by = {b: sum(1 for x in scores if x.band == b) for b in ("high", "watch", "low")}
ui.big_numbers(
    [
        ("Check in this week", n_by["high"], "Highest band: a friendly conversation first", "warn" if n_by["high"] else "ok"),
        ("Keep an eye on", n_by["watch"], "Middle band", "info"),
        ("Doing fine", n_by["low"], "Lowest band", "ok"),
    ]
)

# ------------------------------------------------------------------ filters
f1, f4 = st.columns([2, 2])
dept_opts = sorted({depts.get(s.employee_id, "unknown") for s in scores})
with f1:
    sel_depts = st.multiselect("Department", dept_opts, default=[], format_func=theme.dept_label, placeholder="All departments")
with f4:
    q = st.text_input("Search ID / name", placeholder="E134, Sunita")
with st.expander("More filters"):
    g1, g2 = st.columns(2)
    sel_bands = g1.multiselect("Band", theme.BAND_ORDER, default=[], format_func=lambda b: theme.BAND[b]["label"], placeholder="All bands")
    ctype = g2.segmented_control("Contract", ["All", "Permanent", "Seasonal"], default="All")

names = data.hero_names()
rows = []
for s in scores:
    d = depts.get(s.employee_id, "unknown")
    if sel_depts and d not in sel_depts:
        continue
    if sel_bands and s.band not in sel_bands:
        continue
    if ctype in ("Permanent", "Seasonal") and s.contract_type != ctype.lower():
        continue
    if q and q.lower() not in s.employee_id.lower() and q.lower() not in names.get(s.employee_id, "").lower():
        continue
    td = s.top_driver
    rows.append(
        {
            "employee_id": s.employee_id,
            "Role": ui.avatar_uri(d),
            "Employee": ui.display_name(s.employee_id),
            "Department": theme.dept_label(d),
            "Contract": s.contract_type,
            "Band": theme.BAND[s.band]["label"],
            "Rank": s.rank,
            "of": s.group_size,
            "Tied": "tied" if s.rank_is_tied else "",
            "Basis": theme.BASIS[s.band_basis][0].replace("basis: ", ""),
            "Top driver": td.title if td else "—",
            "Risk (90d)": s.risk,
            "_band": s.band,
        }
    )
df = pd.DataFrame(rows)
order = {"High": 0, "Watch": 1, "Low": 2, "n/a": 3}
if not df.empty:
    df = df.sort_values(["Contract", "Band", "Rank"], key=lambda c: c.map(order) if c.name == "Band" else c).reset_index(drop=True)

ui.takeaway(f"{len(df)} people. Tap a row to see why, and what support may help.")
if df.empty:
    ui.empty("No employees match these filters.")
else:

    def band_style(v):
        key = {"High": "high", "Watch": "watch", "Low": "low"}.get(v, "unknown")
        b = theme.BAND[key]
        return f"background-color:{b['bg']};color:{b['fg']};font-weight:600"

    details = st.toggle("Details", key="risk_details", help="Show rank, ties, basis, contract and the raw score")
    main = ["Role", "Employee", "Department", "Band", "Top driver"]
    show = df.drop(columns=["employee_id", "_band"])
    if not details:
        show = show[main]
    ev = st.dataframe(
        show.style.map(band_style, subset=["Band"]).format({"Risk (90d)": "{:.3f}"} if details else {}),
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        height=min(560, 38 * len(df) + 40),
        column_config={
            "Role": st.column_config.ImageColumn("Role", width="small", help="Department avatar (illustration, not a photo)"),
            "Risk (90d)": st.column_config.ProgressColumn("Risk (90d)", min_value=0, max_value=1, format="%.3f"),
            "Rank": st.column_config.NumberColumn(width="small"),
            "of": st.column_config.NumberColumn(width="small"),
        },
    )
    e1, e2 = st.columns([1, 4])
    with e1:
        export = df[["employee_id", "Department", "Contract", "Band", "Rank", "of", "Basis", "Top driver", "Risk (90d)"]]
        st.download_button(
            "Export CSV",
            export.to_csv(index=False).encode(),
            "hoi_risk_list.csv",
            "text/csv",
            icon=":material/download:",
            help="IDs only, no names. Filters applied.",
        )
    with e2:
        if not depts:
            st.caption("Department comes from the latest roster; generate one to fill it in.")

    sel = ev.selection.rows if ev and ev.selection else []
    if sel:
        emp = df.iloc[sel[0]]["employee_id"]
        s = next(x for x in scores if x.employee_id == emp)
        with st.container(key="card_drill"):
            a, b = st.columns([1.5, 1])
            with a:
                ui.html(
                    f'<div class="ss-person">{ui.avatar_img(depts.get(emp), 46)}'
                    f'<div><div style="font-weight:600;font-size:1.15rem">{theme.esc(ui.display_name(emp))}</div>'
                    f'<div style="display:flex;gap:6px;margin-top:4px">{theme.band_chip(s.band)}{theme.basis_tag(s.band_basis)}'
                    f'{theme.contract_tag(s.contract_type)}<span class="ss-tag">rank {s.rank}/{s.group_size}</span></div></div></div>'
                )
                if s.drivers:
                    st.plotly_chart(charts.driver_bars(s.drivers), width="stretch", config={"displayModeBar": False})
                elif s.contract_type == "seasonal":
                    ui.empty("Seasonal staff are banded by contract end date; there is no per-driver breakdown.")
                else:
                    ui.empty("No active risk drivers for this employee.")
            with b:
                st.markdown("**Support levels**", help=theme.SUPPORT_HELP)
                ui.html(" ".join(theme.support_chip(k) for k in theme.SUPPORT))
                for d in s.drivers:
                    st.markdown(f"- **{d.title}**: {d.reason}")
                if s.actions:
                    st.markdown("**Suggested actions**")
                    for ac in s.actions:
                        st.markdown(f"- {ac.action} · _{ac.owner}_")
                if st.button("Open employee detail", type="primary", icon=":material/person:"):
                    ui.go_to_employee(emp)

ui.footer()
