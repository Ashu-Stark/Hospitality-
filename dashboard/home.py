"""Home page (routed from app.py)."""

import streamlit as st

from lib import auth, data, nav, platform, tenancy, theme, tour, ui

ui.setup("home.py", "Home")


@st.dialog("Welcome to HOI", width="large")
def welcome() -> None:
    st.markdown("**Hospitality Operations Intelligence** helps hotel teams keep good staff and run fair, forecast-driven shifts.")
    ui.html(
        '<div class="ss-welcome">'
        + "".join(
            f'<div><span class="ss-stepnum">{i}</span>{theme.esc(t)}</div>'
            for i, t in enumerate(
                [
                    "See who may need support, and why",
                    "Test a fix before you roster it",
                    "Auto-assign live requests to on-shift staff",
                    "Proof of work with stamped photos",
                ],
                1,
            )
        )
        + "</div>"
        "<style>.ss-welcome{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin:8px 0 6px}"
        ".ss-welcome>div{background:#fff;border-radius:16px;padding:14px;display:flex;gap:10px;align-items:center;font-weight:500}"
        ".ss-welcome .ss-stepnum{width:30px;height:30px;font-size:.85rem}</style>"
    )
    st.caption("You are looking at a demo hotel with synthetic data. Nothing here is a real person.")
    a, b, c = st.columns(3)
    if a.button("Take the 2-minute tour", type="primary", width="stretch", disabled=not T.get("is_demo")):
        st.session_state["welcomed"] = True
        tour.start()
    if b.button("Set up my hotel", width="stretch", disabled=auth.role() not in ("owner", "platform_admin")):
        st.session_state["welcomed"] = True
        mark_seen()
        st.switch_page(nav.page("pages/12_Setup.py"))
    if c.button("Just explore", width="stretch"):
        st.session_state["welcomed"] = True
        mark_seen()
        st.rerun()


def mark_seen() -> None:
    try:
        platform.set_prefs({"tour_done": True})
        st.session_state["user"]["prefs"] = {**(st.session_state["user"].get("prefs") or {}), "tour_done": True}
    except platform.PlatformError:
        pass


T = tenancy.active()
seen = (auth.current() or {}).get("prefs", {}).get("tour_done")
if not seen and not st.session_state.get("welcomed") and "tour_step" not in st.session_state:
    welcome()

ui.html(
    theme.hero(
        "Keep good people,<br>one roster at a time.",
        "HOI flags staff who may need support and explains why. It turns the matching fix into a fair, "
        "forecast-driven roster, then measures what changed.",
        eyebrow="AI retention & operations · hill hotels",
        pills=["Occupancy forecast", "Attrition risk + drivers", "CP-SAT roster", "Closed loop", "Auto-dispatch", "Photo proof"],
    )
)
c_t1, c_t2, _ = st.columns([1, 1, 3])
if T.get("is_demo") and c_t1.button("Start guided tour", type="primary", icon=":material/explore:", width="stretch"):
    tour.start()
if auth.role() in ("owner", "platform_admin") and c_t2.button("Set up my hotel", icon=":material/add_business:", width="stretch"):
    st.switch_page(nav.page("pages/12_Setup.py"))

QUICK = [
    ("pages/1_Overview.py", "Overview", ":material/dashboard:"),
    ("pages/2_Risk_List.py", "Risk list", ":material/flag:"),
    ("pages/3_Employee_Detail.py", "Employee", ":material/person:"),
    ("pages/4_What_If_Simulator.py", "What-if", ":material/tune:"),
    ("pages/5_Roster.py", "Roster", ":material/calendar_month:"),
    ("pages/6_Closed_Loop.py", "Closed loop", ":material/sync:"),
    ("pages/10_Dispatch.py", "Live dispatch", ":material/bolt:"),
    ("pages/11_Worker_App.py", "Worker app", ":material/smartphone:"),
]
mine = {f for f, _, _ in st.session_state.get("_nav", [])}
quick = [q for q in QUICK if q[0] in mine]  # only pages this role and plan can open (others are not routable)
if quick:
    with st.container(key="ss_quick"):
        for qc, (f, label, ic) in zip(st.columns(len(quick)), quick):
            with qc:
                st.page_link(nav.page(f), label=label, icon=ic)
ui.html("""<style>
.st-key-ss_quick { background:#fff; border-radius:22px; padding:16px 10px; }
.st-key-ss_quick [data-testid="stPageLink-NavLink"] { flex-direction:column; gap:8px; align-items:center; text-align:center; border-radius:16px; padding:8px 4px; }
.st-key-ss_quick [data-testid="stPageLink-NavLink"]:hover { background:#f4f4f2; }
.st-key-ss_quick [data-testid="stPageLink-NavLink"] span[data-testid="stIconMaterial"] { display:flex !important; align-items:center; justify-content:center;
  width:48px !important; min-width:48px; height:48px; border-radius:999px; background:#e8f1ff; color:#1f6fe5; font-size:24px !important; }
.st-key-ss_quick [data-testid="stColumn"]:not(:last-child) { border-right:1px solid #e6e5e0; }
</style>""")

ui.html(theme.section("The 3-minute demo story", "Follow the loop"))
story = [
    ("1", "Forecast", "Saturday looks busy: the occupancy forecast with its honest uncertainty band.", "Overview"),
    ("2", "Roster", "A roster solved in seconds, with coverage, cost and fairness shown.", "Roster"),
    ("3", "Flag", "The model flags Sunita, with plain-language drivers: overtime overload and missed weekend offs.", "Employee_Detail"),
    ("4", "Fix", "Intervention tasks appear and the roster re-solves with protected weekends.", "Closed_Loop"),
    ("5", "Measure", "Re-score before vs after. The effect is shown as-is, even when it is small.", "Closed_Loop"),
]
cols = st.columns(5)
for c, (n, t, d, href) in zip(cols, story):
    with c:
        ui.html(
            f'<div class="ss-card" style="min-height:190px"><div class="ss-stepnum" style="margin-bottom:12px">{n}</div>'
            f'<div style="font-weight:600;font-size:1.1rem;letter-spacing:-.02em">{t}</div>'
            f'<div style="color:#52514e;font-size:.88rem;margin:6px 0 10px">{d}</div>'
            f'<div style="color:#6b6a65;font-size:.8rem">Page: {href.replace("_", " ")}</div></div>'
        )

ui.html(
    theme.section("What is running", "Model honesty", "Every number here comes from synthetic data. Baselines are shown beside the models.")
)
c1, c2 = st.columns([1.3, 1])
with c1:
    h = ui.safe(data.health, what="reach the backend health check")
    if h:
        rows = h.get("models", [])
        ui.html(
            theme.tiles(
                [
                    theme.tile(
                        r.get("name", "?").replace("_", " ").capitalize(),
                        r.get("version", "?"),
                        f"dataset {str(r.get('dataset_sha256', ''))[:10]}…",
                        "shield",
                    )
                    for r in rows
                ]
            )
        )
with c2:
    ui.html(
        '<div class="ss-card">'
        '<div style="font-weight:600;margin-bottom:8px">Reported results (synthetic data)</div>'
        '<div class="ss-kv">'
        '<div><div class="k">Attrition, permanent ROC-AUC</div><div class="v">0.691 <span class="ss-tag">rules 0.542</span></div></div>'
        '<div><div class="k">Seasonal contract-end</div><div class="v">0.736 <span class="ss-tag">date rule</span></div></div>'
        '<div><div class="k">Occupancy MAPE 7d</div><div class="v">7.2% <span class="ss-tag">naive 13.7%</span></div></div>'
        '<div><div class="k">80% band real coverage</div><div class="v">~68%</div></div>'
        '</div><div style="color:#6b6a65;font-size:.78rem;margin-top:10px">Source: project model cards. Drivers are planted in '
        "the generator, so these show the mechanism working, not real-world accuracy.</div></div>"
    )

ui.footer()
