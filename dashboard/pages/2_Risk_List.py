import pandas as pd
import streamlit as st

from lib import charts, data, theme, ui

ui.setup("pages/2_Risk_List.py", "Risk list")
ui.html(
    theme.section(
        "Attrition risk overview",
        "Retention",
        "Bands rank people within this week's scores. They flag who to check in with; they do not predict who will resign.",
    )
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


# ------------------------------------------------------------------ summary strip (outline status cards)
def strip(group: list, label: str) -> str:
    n = len(group) or 1
    cards = [
        theme.status_card(
            label, f"{sum(1 for s in group if s.band == b) / n:.0%}", f"{sum(1 for s in group if s.band == b)}", theme.BAND[b]["label"], b
        )
        for b in theme.BAND_ORDER
    ]
    return "".join(cards)


perm = [s for s in scores if s.contract_type == "permanent"]
seas = [s for s in scores if s.contract_type == "seasonal"]
c1, c2 = st.columns([3, 2])
with c1:
    ui.html(
        f'<div class="ss-card"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">'
        f'<b>Permanent · {len(perm)} staff</b>{theme.basis_tag("model_rank")}</div><div class="ss-statusrow">{strip(perm, "Permanent")}</div></div>'
    )
with c2:
    ui.html(
        f'<div class="ss-card"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">'
        f'<b>Seasonal · {len(seas)} staff</b>{theme.basis_tag("contract_date")}</div><div class="ss-statusrow">{strip(seas, "Seasonal")}</div></div>'
    )

# ------------------------------------------------------------------ filters
ui.html('<div style="height:14px"></div>')
f1, f2, f3, f4 = st.columns([2, 2, 2, 1.2])
dept_opts = sorted({depts.get(s.employee_id, "unknown") for s in scores})
with f1:
    sel_depts = st.multiselect("Department", dept_opts, default=[], format_func=theme.dept_label, placeholder="All departments")
with f2:
    sel_bands = st.multiselect("Band", theme.BAND_ORDER, default=[], format_func=lambda b: theme.BAND[b]["label"], placeholder="All bands")
with f3:
    ctype = st.segmented_control("Contract", ["All", "Permanent", "Seasonal"], default="All")
with f4:
    q = st.text_input("Search ID / hero", placeholder="E134, Sunita")

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

ui.html(theme.section(f"{len(df)} employees", "Results", "Click a row to see the driver breakdown."))
if df.empty:
    ui.empty("No employees match these filters.")
else:

    def band_style(v):
        key = {"High": "high", "Watch": "watch", "Low": "low"}.get(v, "unknown")
        b = theme.BAND[key]
        return f"background-color:{b['bg']};color:{b['fg']};font-weight:600"

    show = df.drop(columns=["employee_id", "_band"])
    ev = st.dataframe(
        show.style.map(band_style, subset=["Band"]).format({"Risk (90d)": "{:.3f}"}),
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        height=min(560, 38 * len(df) + 40),
        column_config={
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
                    f'<div class="ss-person"><div class="ss-avatar {"hero" if s.is_demo_hero else ""}">{theme.esc(ui.initials(emp))}</div>'
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
