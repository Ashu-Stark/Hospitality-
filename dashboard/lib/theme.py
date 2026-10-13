"""HOI design system: one place for colors, CSS and HTML components.

Visual language follows the reference designs (Train.png / Train (1).png):
off-white page, borderless white cards with large radii, tight geometric type,
black active pill in a white pill nav, blue gradient pill CTA, outline status
cards with a pill badge, round day chips, rounded gradient hero banners.

Risk-band colors are reserved status colors and are used identically on every page:
high = red, watch = amber, low = green. Color is never the only signal: every
band chip also carries its text label.
"""

from __future__ import annotations

import html

# ------------------------------------------------------------------ tokens
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#6b6a65"
PAGE, CARD, FIELD, LINE = "#f2f2f0", "#ffffff", "#f4f4f2", "#e6e5e0"
BLUE, BLUE_SOFT = "#1f6fe5", "#e8f1ff"

BAND = {
    "high": {"label": "Check in this week", "fg": "#a32020", "bg": "#fdeceb", "border": "#efa3a1", "dot": "#d03b3b"},
    "watch": {"label": "Keep an eye on", "fg": "#7a5000", "bg": "#fff6df", "border": "#f2cd6f", "dot": "#fab219"},
    "low": {"label": "Doing fine", "fg": "#0a6b12", "bg": "#ecfbea", "border": "#62d36b", "dot": "#0ca30c"},
    "unknown": {"label": "Not known", "fg": INK2, "bg": FIELD, "border": LINE, "dot": MUTED},
}
BAND_ORDER = ["high", "watch", "low"]
BAND_COLOR = {k: v["dot"] for k, v in BAND.items()}

# How clear a reason ("why") is: one blue ramp (ordered) + gray for "no sign".
SUPPORT = {
    "supported": {"label": "Clear sign", "color": "#2a78d6"},
    "weakly_supported": {"label": "Weak sign", "color": "#86b6ef"},
    "unsupported": {"label": "No sign", "color": "#c3c2b7"},
}
SUPPORT_HELP = (
    "**Clear sign**: the numbers show this clearly.  \n"
    "**Weak sign**: only a small hint. Ask, don't assume.  \n"
    "**No sign**: we cannot see this in the numbers, so it is never shown as a reason."
)

BASIS = {
    "model_rank": (
        "compared with the team",
        "Compared with the rest of the team this week: top 10% = check in this week, next 15% = keep an eye on.",
    ),
    "contract_date": ("contract ends soon", "Seasonal staff: based on when their contract ends."),
}


# Loading / coverage ratio colors (department table)
def load_tone(ratio: float | None) -> str:
    if ratio is None:
        return "unknown"
    return "high" if ratio > 1.1 else "watch" if ratio >= 0.95 else "low"


DEPT_LABEL = {
    "housekeeping": "Housekeeping",
    "fnb_service": "F&B service",
    "kitchen": "Kitchen",
    "front_office": "Front office",
    "maintenance": "Maintenance",
    "security": "Security",
}


def dept_label(d: str | None) -> str:
    return DEPT_LABEL.get(str(d), str(d or "unknown").replace("_", " ").capitalize())


# ------------------------------------------------------------------ icons (lucide-style, 1.75px strokes)
_ICON_PATHS = {
    "home": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/>',
    "alert": '<path d="M12 3 2 21h20L12 3z"/><path d="M12 10v5"/><path d="M12 18h.01"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/>',
    "sliders": '<path d="M4 6h10"/><path d="M18 6h2"/><circle cx="16" cy="6" r="2"/><path d="M4 12h4"/><path d="M12 12h8"/><circle cx="10" cy="12" r="2"/><path d="M4 18h12"/><path d="M20 18h0"/><circle cx="18" cy="18" r="2"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18"/><path d="M8 3v4"/><path d="M16 3v4"/>',
    "loop": '<path d="M17 2l4 4-4 4"/><path d="M3 11V9a3 3 0 0 1 3-3h15"/><path d="M7 22l-4-4 4-4"/><path d="M21 13v2a3 3 0 0 1-3 3H3"/>',
    "check": '<rect x="3" y="3" width="18" height="18" rx="4"/><path d="m8 12 3 3 5-6"/>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "rupee": '<path d="M6 4h12"/><path d="M6 9h12"/><path d="M6 4h3a5 5 0 0 1 0 10H6l8 7"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c1-3.5 3.5-5.5 6.5-5.5s5.5 2 6.5 5.5"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7"/><path d="M18 14.7c1.8.8 3 2.5 3.5 5.3"/>',
    "flag": '<path d="M5 21V4"/><path d="M5 4h11l-2 4 2 4H5"/>',
    "trend": '<path d="m3 17 6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    "shield": '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6l-8-3z"/>',
    "bed": '<path d="M3 18V7"/><path d="M3 14h18v4"/><path d="M21 14v-2a3 3 0 0 0-3-3h-7v5"/><circle cx="7" cy="11" r="2"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><path d="M12 7.5h.01"/>',
    "arrow": '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
}


def icon(name: str, size: int = 20, color: str = "currentColor", stroke: float = 1.75) -> str:
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="{stroke}" '
        f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{_ICON_PATHS.get(name, _ICON_PATHS["info"])}</svg>'
    )


# ------------------------------------------------------------------ global CSS
CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;700&display=swap');
:root {{ --ink:{INK}; --ink2:{INK2}; --muted:{MUTED}; --page:{PAGE}; --card:{CARD}; --field:{FIELD}; --line:{LINE};
         --blue:{BLUE}; --blue-soft:{BLUE_SOFT}; }}
html, body, [class*="css"], .stApp, .stMarkdown, button, input, textarea, select {{
  font-family: 'Inter Tight', system-ui, -apple-system, 'Segoe UI', sans-serif !important; }}
.stApp {{ background: var(--page); color: var(--ink); }}
header[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{ padding-top: 1.4rem; padding-bottom: 4rem; max-width: 1320px; }}
h1, h2, h3, h4 {{ letter-spacing: -0.03em; color: var(--ink); font-weight: 600 !important; }}
[data-testid="stSidebar"] {{ background: #fbfbfa; border-right: 1px solid var(--line); }}
[data-testid="stSidebarNav"] a {{ border-radius: 999px; }}
[data-testid="stSidebarNav"] a[aria-current="page"] {{ background: var(--ink); }}
[data-testid="stSidebarNav"] a[aria-current="page"] span {{ color: #fff !important; }}

/* Cards: st.container(border=True) becomes a borderless white card */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {{ }}
div[data-testid="stVerticalBlockBorderWrapper"][class*="border"], .st-key-card, div[class*="st-key-card"] {{
  background: var(--card); border: none !important; border-radius: 22px !important; padding: 6px 4px; }}
div[data-testid="stContainer"], div[data-testid="stLayoutWrapper"] > div[data-testid="stVerticalBlock"][height] {{ }}

/* Buttons: pills. Primary = blue gradient pill (the Search CTA). */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button, .stLinkButton > a {{
  border-radius: 999px !important; border: 1px solid var(--line) !important; background: #fff; color: var(--ink);
  font-weight: 500; padding: .45rem 1.1rem; box-shadow: none; transition: background .15s, border-color .15s; }}
.stButton > button:hover, .stDownloadButton > button:hover {{ border-color: var(--ink) !important; color: var(--ink); }}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {{
  background: linear-gradient(180deg, #3b86ff 0%, #1463e0 100%); color: #fff; border: none !important;
  box-shadow: 0 6px 16px rgba(31,111,229,.28); }}
.stButton > button[kind="primary"]:hover {{ filter: brightness(1.05); color: #fff; }}
.stButton > button[kind="tertiary"] {{ border: none !important; background: transparent; color: var(--blue); padding-left: 0; }}

/* Fields: soft gray, rounded, borderless */
[data-baseweb="select"] > div, .stTextInput input, .stNumberInput input, .stDateInput input, .stTextArea textarea {{
  background: var(--field) !important; border-radius: 14px !important; border-color: transparent !important; }}
[data-testid="stWidgetLabel"] p {{ color: var(--muted); font-size: .8rem; }}
[data-baseweb="tag"] {{ border-radius: 999px !important; background: var(--ink) !important; }}

/* Pills / segmented control: black active pill */
[data-testid="stButtonGroup"] button {{ border-radius: 999px !important; border: 1px solid var(--line) !important; background: #fff; }}
[data-testid="stButtonGroup"] button[aria-checked="true"], [data-testid="stButtonGroup"] button[kind*="Active"] {{
  background: var(--ink) !important; color: #fff !important; border-color: var(--ink) !important; }}
[data-testid="stButtonGroup"] button[aria-checked="true"] p, [data-testid="stButtonGroup"] button[kind*="Active"] p {{ color: #fff !important; }}

/* Tabs as pill nav */
.stTabs [data-baseweb="tab-list"] {{ gap: 4px; background: #fff; border-radius: 999px; padding: 5px; width: fit-content; }}
.stTabs [data-baseweb="tab"] {{ border-radius: 999px; padding: 6px 18px; height: auto; }}
.stTabs button[role="tab"] {{ padding: 8px 18px !important; border-radius: 999px !important; min-height: 40px; }}
.stTabs [aria-selected="true"] {{ background: var(--ink); color: #fff !important; }}
.stTabs [aria-selected="true"] p {{ color: #fff !important; }}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {{ display: none; }}

/* Metrics -> stat tiles */
[data-testid="stMetric"] {{ background: #fff; border-radius: 22px; padding: 18px 20px; }}
[data-testid="stMetricLabel"] p {{ color: var(--muted); font-size: .82rem; }}
[data-testid="stMetricValue"] {{ letter-spacing: -0.03em; font-weight: 600; }}
[data-testid="stExpander"] details {{ background: #fff; border: none; border-radius: 18px; }}
[data-testid="stDataFrame"], [data-testid="stTable"] {{ border-radius: 16px; overflow: hidden; }}
[data-testid="stAlert"] {{ border-radius: 18px; border: none; }}
.stPlotlyChart {{ background: #fff; border-radius: 22px; padding: 8px 6px 2px; }}

/* keyed st.container(key="card_*") -> white card */
div[class*="st-key-card"] {{ background:#fff; border-radius:22px; padding:18px 22px !important; }}
/* keyboard focus must always be visible */
button:focus-visible, a:focus-visible, [role="tab"]:focus-visible, input:focus-visible, [data-baseweb="select"]:focus-within {{
  outline: 3px solid #1f6fe5 !important; outline-offset: 2px; }}
/* ------- custom components ------- */
.ss-topbar {{ display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom: 4px; }}
.ss-brand {{ display:flex; align-items:center; gap:10px; font-weight:700; letter-spacing:-.03em; font-size:1.25rem; }}
.ss-brand-mark {{ width:36px; height:36px; border-radius:12px; background: linear-gradient(135deg,#1f6fe5,#0b0b0b);
  display:grid; place-items:center; color:#fff; }}
.ss-util {{ display:flex; gap:18px; align-items:center; font-size:.74rem; letter-spacing:.06em; text-transform:uppercase; color:var(--ink); }}
.ss-mode {{ border:1.5px solid var(--ink); border-radius:999px; padding:6px 14px; font-weight:600; font-size:.72rem; letter-spacing:.06em; }}
.ss-mode.mock {{ border-color:#d48a00; color:#7a5000; background:#fff6df; }}
.ss-mode.live {{ border-color:#0ca30c; color:#0a6b12; background:#ecfbea; }}
.ss-nav {{ display:flex; gap:4px; background:#fff; border-radius:999px; padding:5px; width:fit-content; flex-wrap:wrap; }}

.ss-hero {{ position:relative; border-radius:28px; padding:44px 44px 40px; color:#fff; overflow:hidden; margin: 8px 0 18px;
  background: radial-gradient(120% 140% at 85% 10%, #e0631f 0%, #c94d16 45%, #b03f14 100%); }}
.ss-hero.blue {{ background: radial-gradient(120% 140% at 85% 0%, #7fb2ff 0%, #2a6fe0 45%, #123a8a 100%); }}
.ss-hero.dark {{ background: radial-gradient(120% 140% at 90% 0%, #5c6b5a 0%, #2c3a2c 50%, #111811 100%); }}
.ss-hero .eyebrow {{ font-size:.78rem; letter-spacing:.08em; text-transform:uppercase; opacity:.9; }}
.ss-hero h1 {{ color:#fff; font-size: clamp(2rem, 4.2vw, 3.4rem); line-height:1.02; margin:.35rem 0 .6rem; letter-spacing:-.045em; }}
.ss-hero p {{ color:rgba(255,255,255,.88); max-width: 640px; font-size:1rem; margin:0; }}
.ss-hero .ridge {{ position:absolute; right:-40px; bottom:-30px; width:55%; height:70%; opacity:.18; pointer-events:none; }}
.ss-hero .pillrow {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:18px; }}
.ss-hero .hpill {{ background:rgba(255,255,255,.18); border:1px solid rgba(255,255,255,.35); border-radius:999px; padding:6px 12px; font-size:.8rem; }}

.ss-section {{ margin: 22px 0 10px; }}
.ss-section .eyebrow {{ font-size:.74rem; color:var(--ink2); }}
.ss-section h2 {{ font-size:1.3rem; margin:.1rem 0 0; padding:0 !important; letter-spacing:-.035em; }}
.ss-section {{ line-height:1.25; }}
.ss-section .sub {{ color:var(--muted); font-size:.9rem; margin-top:4px; }}

.ss-card {{ background:#fff; border-radius:22px; padding:20px 22px; }}
.ss-tiles {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(172px, 1fr)); gap:12px; }}
.ss-tile {{ background:#fff; border-radius:22px; padding:18px 20px; display:flex; flex-direction:column; gap:6px; min-height:132px; }}
.ss-tile .top {{ display:flex; align-items:center; gap:10px; color:var(--ink2); font-size:.85rem; }}
.ss-tile .ic {{ width:36px; height:36px; border-radius:999px; background:var(--blue-soft); color:var(--blue); display:grid; place-items:center; flex:none; }}
.ss-tile .val {{ font-size:1.9rem; font-weight:600; letter-spacing:-.04em; color:var(--ink); line-height:1.05; }}
.ss-tile .sub {{ color:var(--muted); font-size:.8rem; }}
.ss-tile .assume {{ display:inline-block; margin-top:2px; font-size:.7rem; font-weight:600; letter-spacing:.03em; color:#7a5000;
  background:#fff6df; border:1px solid #f2cd6f; border-radius:999px; padding:2px 8px; width:fit-content; }}

.ss-quick {{ background:#fff; border-radius:22px; padding:18px 8px; display:grid; grid-template-columns: repeat(auto-fit, minmax(110px,1fr)); }}
.ss-quick a {{ text-decoration:none; color:var(--ink); display:flex; flex-direction:column; align-items:center; gap:8px; font-size:.84rem;
  text-align:center; padding:6px 4px; border-right:1px solid var(--line); }}
.ss-quick a:last-child {{ border-right:none; }}
.ss-quick .ic {{ width:44px; height:44px; border-radius:999px; background:var(--blue-soft); color:var(--blue); display:grid; place-items:center; }}

.ss-chip {{ display:inline-flex; align-items:center; gap:6px; border-radius:999px; padding:3px 10px; font-size:.76rem; font-weight:600;
  border:1px solid; white-space:nowrap; line-height:1.4; }}
.ss-chip .dot {{ width:7px; height:7px; border-radius:999px; }}
.ss-tag {{ display:inline-block; border-radius:999px; padding:2px 9px; font-size:.7rem; color:var(--ink2); background:var(--field);
  border:1px solid var(--line); white-space:nowrap; }}
.ss-tag.seasonal {{ background:#eef4ff; border-color:#c9dcff; color:#1d4fa8; }}

.ss-status {{ border:1.5px solid; border-radius:16px; padding:12px 14px; display:flex; flex-direction:column; gap:4px; min-width:104px; flex:1 1 0; }}
.ss-status .row {{ display:flex; justify-content:space-between; font-size:.8rem; color:var(--ink2); gap:12px; }}
.ss-status .big {{ font-size:1.25rem; font-weight:600; letter-spacing:-.03em; }}
.ss-status .badge {{ border-radius:999px; padding:2px 10px; font-size:.74rem; width:fit-content; max-width:100%; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.ss-statusrow {{ display:flex; gap:10px; flex-wrap:nowrap; overflow-x:auto; }}

.ss-days {{ display:flex; gap:8px; align-items:center; background:#fff; border-radius:22px; padding:12px 14px; overflow-x:auto; }}
.ss-day {{ min-width:62px; border-radius:999px; background:var(--field); text-align:center; padding:8px 6px; border:1.5px solid transparent; }}
.ss-day .n {{ font-weight:600; font-size:1.05rem; letter-spacing:-.02em; }}
.ss-day .d {{ font-size:.72rem; color:var(--muted); }}
.ss-day.on {{ background:var(--blue-soft); border-color:var(--blue); color:#1557c0; }}
.ss-day.on .d {{ color:#1557c0; }}
.ss-day.alert {{ border-color:#efa3a1; }}
.ss-month {{ writing-mode: vertical-rl; transform: rotate(180deg); font-size:.72rem; font-weight:600; letter-spacing:.08em; color:var(--ink2); }}

.ss-field {{ background:var(--field); border-radius:16px; padding:10px 14px; display:flex; gap:12px; align-items:center; }}
.ss-field .lbl {{ font-size:.72rem; color:var(--muted); }}
.ss-field .v {{ font-weight:500; }}

.ss-person {{ display:flex; align-items:center; gap:14px; }}
.ss-avatar {{ width:46px; height:46px; border-radius:999px; background:var(--field); display:grid; place-items:center; font-weight:600; color:var(--ink2); flex:none; }}
.ss-avatar.hero {{ background:linear-gradient(135deg,#e0631f,#b03f14); color:#fff; }}
.ss-kv {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(132px, 1fr)); gap:10px; }}
.ss-kv div {{ background:var(--field); border-radius:14px; padding:10px 12px; }}
.ss-kv .k {{ font-size:.72rem; color:var(--muted); }}
.ss-kv .v {{ font-weight:600; font-size:1rem; letter-spacing:-.02em; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}

.ss-step {{ display:flex; gap:14px; align-items:flex-start; }}
.ss-stepnum {{ width:38px; height:38px; border-radius:999px; background:var(--ink); color:#fff; display:grid; place-items:center; font-weight:600; flex:none; }}
.ss-stepnum.todo {{ background:var(--field); color:var(--muted); }}
.ss-step h3 {{ margin:0; font-size:1.2rem; }}
.ss-step p {{ margin:2px 0 0; color:var(--ink2); font-size:.9rem; }}

.ss-delta {{ display:inline-flex; align-items:center; gap:4px; border-radius:999px; padding:2px 9px; font-size:.78rem; font-weight:600; }}
.ss-delta.good {{ background:#ecfbea; color:#0a6b12; }}
.ss-delta.bad {{ background:#fdeceb; color:#a32020; }}
.ss-delta.flat {{ background:var(--field); color:var(--ink2); }}

.ss-banner svg {{ flex:none; margin-top:1px; }}
.ss-banner {{ border-radius:18px; padding:14px 18px; display:flex; gap:12px; align-items:flex-start; font-size:.92rem; }}
.ss-banner.red {{ background:#fdeceb; color:#7d1717; border:1.5px solid #efa3a1; }}
.ss-banner.amber {{ background:#fff6df; color:#5c3c00; border:1.5px solid #f2cd6f; }}
.ss-banner.blue {{ background:var(--blue-soft); color:#123a8a; border:1.5px solid #bcd4ff; }}
.ss-banner.gray {{ background:#fff; color:var(--ink2); border:1.5px solid var(--line); }}

.ss-kanban-col {{ background:#ebebe8; border-radius:22px; padding:12px; min-height:200px; }}
.ss-task {{ background:#fff; border-radius:16px; padding:12px 14px; margin-bottom:10px; border:1.5px solid transparent; }}
.ss-task.overdue {{ border-color:#d03b3b; background:#fff7f7; }}
.ss-task.near90 {{ border-color:#ec835a; }}
.ss-task.near50 {{ border-color:#fab219; }}
.ss-task .t {{ font-weight:600; letter-spacing:-.02em; }}
.ss-task .m {{ color:var(--muted); font-size:.78rem; }}
.ss-task .key {{ color:#b5b4ae; font-size:.68rem; font-family: ui-monospace, monospace; }}

/* ------- nav (pill bar, horizontally scrollable) ------- */
.st-key-ss_nav {{ background:#fff; border-radius:999px; padding:5px 8px; margin:10px 0 8px; }}
.st-key-ss_nav [data-testid="stHorizontalBlock"] {{ gap:2px !important; align-items:center; flex-wrap:wrap !important; }}
@media (max-width: 820px) {{ .st-key-ss_nav [data-testid="stHorizontalBlock"] {{ flex-wrap:nowrap !important; overflow-x:auto; scrollbar-width:none; }} }}
.st-key-ss_nav {{ border-radius:28px !important; }}
.st-key-ss_nav [data-testid="stHorizontalBlock"]::-webkit-scrollbar {{ display:none; }}
.st-key-ss_nav [data-testid="stColumn"] {{ width:auto !important; flex:0 0 auto !important; min-width:0 !important; }}
.st-key-ss_nav [data-testid="stPageLink-NavLink"] {{ border-radius:999px; padding:6px 12px; justify-content:center; transition:background .15s; }}
.st-key-ss_nav [data-testid="stPageLink-NavLink"]:hover {{ background:#f4f4f2; }}
.st-key-ss_nav [data-testid="stPageLink-NavLink"] p {{ font-size:.86rem; white-space:nowrap; }}
.st-key-ss_nav [data-testid="stMarkdownContainer"], .st-key-ss_nav [data-testid="stElementContainer"] {{ margin:0 !important; }}
.ss-navactive {{ margin:0 !important; background:#0b0b0b; color:#fff; border-radius:999px; padding:8px 14px; text-align:center; font-size:.86rem;
  font-weight:500; white-space:nowrap; animation: ss-pop .25s ease-out; }}
.ss-brand-long {{ font-weight:500; color:var(--ink2); font-size:.95rem; }}
.ss-tenant {{ display:inline-flex; align-items:center; gap:8px; text-transform:none; letter-spacing:0; font-size:.85rem; font-weight:500;
  background:#fff; border-radius:999px; padding:6px 12px; }}
.ss-tenant i {{ width:10px; height:10px; border-radius:999px; display:inline-block; }}

/* ------- section nav: second row (pages of the active section) ------- */
.st-key-ss_subnav {{ margin:-2px 0 10px; padding:0 4px; }}
.st-key-ss_subnav [data-testid="stHorizontalBlock"] {{ gap:4px !important; flex-wrap:wrap !important; }}
@media (max-width: 820px) {{ .st-key-ss_subnav [data-testid="stHorizontalBlock"] {{ flex-wrap:nowrap !important; overflow-x:auto; scrollbar-width:none; }} }}
.st-key-ss_subnav [data-testid="stColumn"] {{ width:auto !important; flex:0 0 auto !important; min-width:0 !important; }}
.st-key-ss_subnav [data-testid="stPageLink-NavLink"] {{ border-radius:999px; padding:4px 12px; border:1px solid var(--line); background:#fff; }}
.st-key-ss_subnav [data-testid="stPageLink-NavLink"] p {{ font-size:.84rem; white-space:nowrap; }}
.st-key-ss_subnav [data-testid="stMarkdownContainer"], .st-key-ss_subnav [data-testid="stElementContainer"] {{ margin:0 !important; }}
.ss-subactive {{ background:var(--blue-soft); color:#123a8a; border:1px solid #bcd4ff; border-radius:999px; padding:5px 12px; font-size:.84rem;
  font-weight:600; white-space:nowrap; }}
.st-key-ss_nav [data-testid="stPageLink-NavLink"] {{ min-height:40px; }}
/* ------- simple pages: title, big numbers, takeaway, do-next ------- */
.ss-phead h1 {{ font-size:1.8rem; margin:.2rem 0 0; padding:0 !important; }}
.ss-phead p {{ color:var(--ink2); margin:.2rem 0 .8rem; font-size:.98rem; }}
.ss-bigs {{ display:grid; grid-template-columns:repeat(3, minmax(0,1fr)); gap:12px; margin:6px 0 14px; }}
.ss-bigs.n4 {{ grid-template-columns:repeat(4, minmax(0,1fr)); }}
@media (max-width: 900px) {{ .ss-bigs, .ss-bigs.n4 {{ grid-template-columns:repeat(2, minmax(0,1fr)); }} }}
.ss-big {{ background:#fff; border-radius:22px; padding:18px 20px; border-left:6px solid var(--line); min-height:150px; box-sizing:border-box; }}
.ss-big .v {{ font-size:2.6rem; font-weight:700; letter-spacing:-.04em; line-height:1; color:var(--ink); }}
.ss-big .l {{ font-weight:600; margin-top:8px; }}
.ss-big .m {{ color:var(--muted); font-size:.85rem; margin-top:2px; }}
.ss-big .assume {{ display:inline-block; margin-top:6px; font-size:.7rem; font-weight:600; color:#7a5000; background:#fff6df; border:1px solid #f2cd6f; border-radius:999px; padding:2px 8px; }}
.ss-big.ok {{ border-left-color:#0ca30c; }} .ss-big.warn {{ border-left-color:#e3a008; }}
.ss-big.bad {{ border-left-color:#d03b3b; }} .ss-big.info {{ border-left-color:#1f6fe5; }}
@media (max-width: 600px) {{ .ss-bigs, .ss-bigs.n4 {{ gap:8px; }} .ss-big {{ padding:14px; min-height:140px; }} .ss-big .v {{ font-size:2rem; }} }}
/* Today: photo header */
.ss-photohead {{ border-radius:26px; min-height:150px; padding:26px 28px; display:flex; align-items:flex-end; gap:16px; color:#fff;
  background:#1b315e center/cover no-repeat; margin:6px 0 2px; }}
.ss-photohead h1 {{ color:#fff; margin:.2rem 0 0; font-size:clamp(1.5rem,3.4vw,2.4rem); line-height:1.05; padding:0 !important; }}
.ss-photohead .eyebrow {{ font-size:.78rem; letter-spacing:.06em; text-transform:uppercase; opacity:.9; }}
.ss-photohead .logo {{ height:56px; width:auto; background:#fff; border-radius:14px; padding:6px 8px; }}
.ss-credit {{ color:var(--muted); font-size:.72rem; margin:0 0 8px 6px; }}
.ss-h3 {{ font-size:1.3rem; margin:14px 0 8px; }}
@media (max-width:600px) {{ .ss-photohead {{ min-height:120px; padding:18px; }} .ss-photohead .logo {{ height:40px; }} }}
.ss-h3 {{ font-size:1.3rem; margin:14px 0 8px; }}
.ss-takeaway {{ display:flex; gap:8px; align-items:center; color:var(--ink); font-weight:500; margin:10px 0 6px; }}
.ss-takeaway svg {{ color:var(--blue); flex:none; }}
.ss-donext {{ background:#fff; border-radius:18px; padding:14px 16px; display:flex; flex-direction:column; gap:2px; }}
.ss-donext b {{ font-size:1.02rem; }} .ss-donext span {{ color:var(--muted); font-size:.85rem; }}
.stButton > button, .stLinkButton > a {{ min-height:44px; }}
div[class*="st-key-act_"] .stButton > button {{ min-height:48px; font-size:1rem; }}

/* ------- motion (disabled for prefers-reduced-motion) ------- */
@keyframes ss-rise {{ from {{ opacity:0; transform: translateY(10px); }} to {{ opacity:1; transform:none; }} }}
@keyframes ss-pop {{ from {{ transform: scale(.94); opacity:.6; }} to {{ transform:none; opacity:1; }} }}
@keyframes ss-pulse {{ 0% {{ box-shadow:0 0 0 0 rgba(31,111,229,.55); }} 70% {{ box-shadow:0 0 0 14px rgba(31,111,229,0); }} 100% {{ box-shadow:0 0 0 0 rgba(31,111,229,0); }} }}
@keyframes ss-shift {{ 0% {{ background-position:0% 50%; }} 50% {{ background-position:100% 50%; }} 100% {{ background-position:0% 50%; }} }}
@keyframes ss-shimmer {{ from {{ background-position:-200px 0; }} to {{ background-position:200px 0; }} }}
.ss-hero, .ss-tile, .ss-card, .ss-status, .ss-quick, .ss-days, .ss-task, .ss-anim, .ss-banner,
div[class*="st-key-card"], .stPlotlyChart {{ animation: ss-rise .45s cubic-bezier(.2,.7,.2,1) both; }}
.ss-tiles > *:nth-child(2) {{ animation-delay:.05s; }} .ss-tiles > *:nth-child(3) {{ animation-delay:.1s; }}
.ss-tiles > *:nth-child(4) {{ animation-delay:.15s; }} .ss-tiles > *:nth-child(5) {{ animation-delay:.2s; }}
.ss-statusrow > *:nth-child(2) {{ animation-delay:.05s; }} .ss-statusrow > *:nth-child(3) {{ animation-delay:.1s; }}
.ss-hero {{ background-size: 160% 160% !important; animation: ss-rise .5s both, ss-shift 14s ease-in-out infinite; }}
.ss-tile, .ss-card, .ss-status, .ss-task {{ transition: transform .18s ease, box-shadow .18s ease; }}
.ss-tile:hover, .ss-status:hover, .ss-task:hover {{ transform: translateY(-2px); box-shadow: 0 10px 24px rgba(11,11,11,.06); }}
.stButton > button {{ transition: transform .12s ease, background .15s, border-color .15s, box-shadow .15s !important; }}
.stButton > button:active {{ transform: scale(.97); }}
.ss-avatar.ping, .ss-ring {{ animation: ss-pulse 1.4s infinite; }}
[data-testid="stSkeleton"] {{ background: linear-gradient(90deg,#ecebe6 0,#f6f6f3 50%,#ecebe6 100%) !important; background-size:400px 100% !important;
  animation: ss-shimmer 1.2s linear infinite; border-radius:16px; }}
@media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ animation: none !important; transition: none !important; }} }}

/* ------- dispatch / worker app ------- */
.ss-wrow {{ display:flex; align-items:center; gap:10px; padding:8px 4px; border-bottom:1px solid var(--line); }}
.ss-wrow:last-child {{ border-bottom:none; }}
.ss-wrow .m {{ color:var(--muted); font-size:.76rem; }}
.ss-avatar.sm {{ width:34px; height:34px; font-size:.8rem; }}
.ss-ravatar {{ border-radius:999px; flex:none; display:inline-block; vertical-align:middle; }}
.ss-ravatar.ping {{ animation: ss-pulse 1.4s infinite; }}
.ss-tag .ss-ravatar {{ margin:-2px 5px 0 -4px; }}
.ss-ping {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-top:8px; color:var(--blue); font-size:.88rem; }}
.ss-countdown {{ flex-basis:100%; height:6px; background:var(--blue-soft); border-radius:999px; overflow:hidden; margin-top:6px; }}
.ss-countdown i {{ display:block; height:100%; background:linear-gradient(90deg,#3b86ff,#1463e0); border-radius:999px; transition: width 1s linear; }}
.ss-phone {{ background:#0b0b0b; border-radius:36px 36px 0 0; padding:14px 16px 16px; color:#fff; position:relative; }}
.ss-phone-notch {{ width:90px; height:20px; background:#000; border-radius:0 0 14px 14px; margin:-14px auto 10px; }}
.ss-phone-head {{ display:flex; gap:10px; align-items:center; }}
.ss-phone-head .m {{ color:#b5b4ae; font-size:.78rem; }}
.ss-phone-empty {{ background:#fff; border-radius:0 0 28px 28px; padding:28px 18px; text-align:center; color:var(--muted); margin-bottom:12px; }}
.ss-offer {{ background:linear-gradient(160deg,#ffffff, #eef4ff); border-radius:0 0 28px 28px; padding:20px 18px 18px; margin-bottom:10px; position:relative; }}
.ss-offer .t {{ color:var(--blue); font-weight:600; font-size:.8rem; text-transform:uppercase; letter-spacing:.06em; }}
.ss-offer .big {{ font-size:1.45rem; font-weight:600; letter-spacing:-.03em; margin:4px 0; padding-right:70px; }}
.ss-offer .m {{ color:var(--ink2); font-size:.85rem; }}
.ss-ring {{ position:absolute; right:18px; top:18px; width:56px; height:56px; border-radius:999px; background:var(--blue); color:#fff;
  display:grid; place-items:center; font-weight:700; font-size:1.2rem; }}

/* ------- onboarding stepper + tour ------- */
.ss-stepper {{ display:flex; gap:8px; background:#fff; border-radius:999px; padding:6px; margin:6px 0 14px; overflow-x:auto; }}
.ss-stepper .s {{ display:flex; align-items:center; gap:8px; padding:6px 14px 6px 6px; border-radius:999px; white-space:nowrap; color:var(--muted); font-size:.88rem; }}
.ss-stepper .s span {{ width:26px; height:26px; border-radius:999px; background:var(--field); display:grid; place-items:center; font-weight:600; font-size:.8rem; }}
.ss-stepper .s.on {{ background:var(--ink); color:#fff; }} .ss-stepper .s.on span {{ background:#fff; color:var(--ink); }}
.ss-stepper .s.done span {{ background:#ecfbea; color:#0a6b12; }}
.st-key-tour_card {{ background: linear-gradient(135deg,#0b0b0b,#1d2a44) !important; color:#fff; border-radius:22px; padding:18px 22px !important;
  margin:4px 0 14px; }}
.st-key-tour_card p, .st-key-tour_card .ss-tour-body {{ color:rgba(255,255,255,.85); }}
.ss-tour-head {{ display:flex; justify-content:space-between; align-items:center; gap:10px; }}
.ss-tour-dots {{ display:flex; gap:5px; }} .ss-tour-dots i {{ width:18px; height:5px; border-radius:999px; background:rgba(255,255,255,.25); }}
.ss-tour-dots i.on {{ background:#ffb47a; }}
.ss-tour-title {{ font-size:1.35rem; font-weight:600; letter-spacing:-.03em; margin:8px 0 4px; color:#fff; }}
.st-key-tour_card .stButton > button[kind="tertiary"] {{ color:#b5b4ae; }}
.st-key-tour_resume {{ background:#fff6df; border-radius:16px; padding:8px 14px !important; margin-bottom:10px; }}

/* ------- responsiveness ------- */
@media (max-width: 1100px) {{
  .ss-brand-long {{ display:none; }}
  .ss-hero {{ padding:32px 28px; }}
}}
@media (max-width: 820px) {{
  .block-container {{ padding-left: 16px !important; padding-right: 16px !important; }}
  .ss-hero {{ padding:26px 20px; border-radius:22px; }}
  .ss-hero p {{ font-size:.92rem; }}
  .ss-util .ss-tenant {{ display:none; }}
  .ss-tiles {{ grid-template-columns: repeat(2, minmax(0,1fr)); }}
  .ss-tile {{ min-height:112px; padding:14px; }} .ss-tile .val {{ font-size:1.5rem; }}
  .ss-statusrow {{ flex-wrap:wrap; }} .ss-status {{ flex:1 1 40%; }}
  .ss-kv {{ grid-template-columns: repeat(2, minmax(0,1fr)); }}
  .ss-section h2 {{ font-size:1.35rem; }}
  .st-key-ss_quick [data-testid="stHorizontalBlock"] {{ flex-wrap:wrap !important; }}
  .st-key-ss_quick [data-testid="stColumn"] {{ flex:1 1 22% !important; min-width:22% !important; border-right:none !important; }}
}}
@media (max-width: 480px) {{
  .ss-tiles {{ grid-template-columns: 1fr; }}
  .ss-hero h1 {{ font-size:1.8rem; }}
  .ss-topbar {{ flex-wrap:wrap; }}
  .ss-util .ss-poweredby {{ display:none; }}  /* the HOI mark is already in the corner */
}}

.ss-footer {{ margin-top:40px; background:#e9e9e6; border-radius:24px; padding:20px 24px; color:var(--ink2); font-size:.8rem;
  display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; }}
</style>
"""

RIDGE_SVG = (
    '<svg class="ridge" viewBox="0 0 400 200" preserveAspectRatio="none"><path fill="#fff" '
    'd="M0 200 L60 110 L100 140 L170 50 L230 120 L270 90 L330 150 L400 70 L400 200 Z"/></svg>'
)


# ------------------------------------------------------------------ HTML component builders
def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def hero(title: str, subtitle: str = "", eyebrow: str = "", variant: str = "orange", pills: list[str] | None = None) -> str:
    pr = "".join(f'<span class="hpill">{esc(p)}</span>' for p in (pills or []))
    return (
        f'<div class="ss-hero {variant}">{RIDGE_SVG}<div class="eyebrow">{esc(eyebrow)}</div><h1>{title}</h1>'
        f"<p>{esc(subtitle)}</p>{f'<div class=pillrow>{pr}</div>' if pr else ''}</div>"
    )


def section(title: str, eyebrow: str = "", sub: str = "") -> str:
    """A plain section heading with an optional one-line meaning (the eyebrow is kept for callers but not shown)."""
    return f'<div class="ss-section"><h2>{esc(title)}</h2>' + (f"<div class=sub>{esc(sub)}</div>" if sub else "") + "</div>"


TILE_TONE = {"alert": "warn", "flag": "warn", "check": "ok", "rupee": "info", "clock": "info", "bed": "info", "user": "info"}


def tile(label: str, value: str, sub: str = "", ic: str = "info", assumption: str = "") -> str:
    """A big number with its label and a one-line meaning (same look as ui.big_numbers)."""
    a = ""  # an assumption stays in the hover text, never a visible pill
    tip = f' title="{esc(assumption)}"' if assumption else ""
    return (
        f'<div class="ss-big {TILE_TONE.get(ic, "info")}"{tip}><div class="v">{esc(value)}</div><div class="l">{esc(label)}</div>'
        f'<div class="m">{esc(sub)}</div>{a}</div>'
    )


def tiles(items: list[str]) -> str:
    cls = "ss-bigs n4" if len(items) in (4, 7, 8) else "ss-bigs"
    return f'<div class="{cls}">{"".join(items)}</div>'


def band_chip(band: str, text: str | None = None) -> str:
    b = BAND.get(band, BAND["unknown"])
    return (
        f'<span class="ss-chip" style="color:{b["fg"]};background:{b["bg"]};border-color:{b["border"]}">'
        f'<span class="dot" style="background:{b["dot"]}"></span>{esc(text or b["label"])}</span>'
    )


def basis_tag(basis: str) -> str:
    label, tip = BASIS.get(basis, BASIS["model_rank"])
    return f'<span class="ss-tag" title="{esc(tip)}">{esc(label)}</span>'


def contract_tag(contract_type: str) -> str:
    return f'<span class="ss-tag {"seasonal" if contract_type == "seasonal" else ""}">{esc(contract_type)}</span>'


def support_chip(level: str) -> str:
    s = SUPPORT.get(level, SUPPORT["supported"])
    return (
        f'<span class="ss-chip" style="color:{INK2};background:#fff;border-color:{LINE}">'
        f'<span class="dot" style="background:{s["color"]}"></span>{esc(s["label"])}</span>'
    )


def status_card(left: str, right: str, big: str, badge: str, tone: str) -> str:
    """The outline 'fare card' from the reference design."""
    b = BAND.get(tone, BAND["unknown"])
    return (
        f'<div class="ss-status" style="border-color:{b["border"]};background:{b["bg"]}">'
        f'<div class="row"><span>{esc(left)}</span><span>{esc(right)}</span></div>'
        f'<div class="big" style="color:{b["fg"]}">{esc(big)}</div>'
        f'<span class="badge" style="background:#fff;color:{b["fg"]};border:1px solid {b["border"]}">{esc(badge)}</span></div>'
    )


def delta_chip(delta: float, fmt: str = "{:+.3f}", good_when_negative: bool = True, flat_eps: float = 1e-9) -> str:
    if abs(delta) < flat_eps:
        return '<span class="ss-delta flat">no change</span>'
    good = (delta < 0) == good_when_negative
    arrow = "↓" if delta < 0 else "↑"
    return f'<span class="ss-delta {"good" if good else "bad"}">{arrow} {esc(fmt.format(abs(delta)))}</span>'


def banner(text_html: str, tone: str = "blue", ic: str = "info") -> str:
    return f'<div class="ss-banner {tone}">{icon(ic, 20)}<div>{text_html}</div></div>'


def day_strip(days: list[dict], selected: str | None = None) -> str:
    """days: [{'date': 'YYYY-MM-DD', 'alert': bool}] — round day chips like the reference date strip."""
    from datetime import date as _d

    if not days:
        return ""
    first = _d.fromisoformat(days[0]["date"])
    out = [f'<span class="ss-month">{first.strftime("%b").upper()}</span>']
    for x in days:
        d = _d.fromisoformat(x["date"])
        cls = "ss-day" + (" on" if x["date"] == selected else "") + (" alert" if x.get("alert") else "")
        out.append(f'<div class="{cls}"><div class="n">{d.day}</div><div class="d">{d.strftime("%a")}</div></div>')
    return f'<div class="ss-days">{"".join(out)}</div>'


def kv(items: list[tuple[str, str]]) -> str:
    return '<div class="ss-kv">' + "".join(f'<div><div class="k">{esc(k)}</div><div class="v">{v}</div></div>' for k, v in items) + "</div>"


def step_header(n: int, title: str, sub: str, done: bool = True) -> str:
    return (
        f'<div class="ss-step"><div class="ss-stepnum {"" if done else "todo"}">{n}</div>'
        f"<div><h3>{esc(title)}</h3><p>{esc(sub)}</p></div></div>"
    )


# ------------------------------------------------------------------ plotly
PLOT_FONT = dict(family="Inter Tight, system-ui, sans-serif", color=INK2, size=12)


def style_fig(fig, height: int = 320, legend: bool = True):
    fig.update_layout(
        height=height,
        margin=dict(l=12, r=12, t=36, b=12),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=PLOT_FONT,
        hoverlabel=dict(bgcolor="#fff", font=PLOT_FONT, bordercolor=LINE),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=None) if legend else None,
        showlegend=legend,
        title=dict(font=dict(size=14, color=INK), x=0.01, y=0.98),
    )
    fig.update_xaxes(showgrid=False, linecolor="#c3c2b7", tickfont=dict(color=MUTED), zeroline=False)
    fig.update_yaxes(gridcolor="#ecebe6", linecolor="rgba(0,0,0,0)", tickfont=dict(color=MUTED), zeroline=False)
    return fig
