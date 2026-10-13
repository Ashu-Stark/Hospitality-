import pandas as pd
import streamlit as st

from lib import platform, theme, ui

ui.setup("console/2_Audit.py", "Audit log")
ui.html(
    theme.section(
        "Audit log",
        "Platform console",
        "Sign-ins, invites, plan and module changes, workspace access, dispatch, inventory and purchasing actions.",
    )
)

names = {t["id"]: t["name"] for t in (ui.safe(platform.tenants, what="load hotel groups") or [])}
c1, c2 = st.columns([2, 3])
scope = c1.selectbox("Hotel group", ["All"] + list(names), format_func=lambda i: "All" if i == "All" else names[i])
needle = c2.text_input("Filter action or user", placeholder="login.failed, platform., po.")
rows = ui.safe(platform.platform_audit, None if scope == "All" else scope, what="load the audit log") or []
if needle:
    rows = [r for r in rows if needle.lower() in (r["action"] + " " + (r["actor"] or "")).lower()]
if not rows:
    ui.empty("No audit entries match.")
else:
    df = pd.DataFrame(
        [
            {
                "When": r["at"].replace("T", " "),
                "Hotel": names.get(r["tenant_id"], "platform"),
                "User": r["actor"],
                "Action": r["action"],
                "Detail": r["detail"],
            }
            for r in rows
        ]
    )
    st.dataframe(df, hide_index=True, width="stretch", height=520)
    st.download_button("Export CSV", df.to_csv(index=False).encode(), "hoi_audit.csv", icon=":material/download:")
ui.footer()
