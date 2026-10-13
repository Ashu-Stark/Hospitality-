import pandas as pd
import streamlit as st

from lib import platform, ui

ui.setup("console/2_Audit.py", "Activity log")
ui.page_head("Activity log", "Everything done in HOI, newest first.")

names = {t["id"]: t["name"] for t in (ui.safe(platform.tenants, what="load the hotels") or [])}
c1, c2 = st.columns([2, 3])
scope = c1.selectbox("Hotel", ["All"] + list(names), format_func=lambda i: "All" if i == "All" else names[i])
needle = c2.text_input("Search what was done or who did it", placeholder="login, open, order")
rows = ui.safe(platform.platform_audit, None if scope == "All" else scope, what="load the activity log") or []
if needle:
    rows = [r for r in rows if needle.lower() in (r["action"] + " " + ui.action_label(r["action"]) + " " + (r["actor"] or "")).lower()]
if not rows:
    ui.empty("Nothing matches.")
else:
    df = pd.DataFrame(
        [
            {
                "When": r["at"].replace("T", " "),
                "Hotel": names.get(r["tenant_id"], "platform"),
                "User": r["actor"],
                "What happened": ui.action_label(r["action"]),
                "Detail": r["detail"],
                "Code": r["action"],
            }
            for r in rows
        ]
    )
    st.caption(f"{len(df)} entries, newest first.")
    ui.table(df, ["When", "Hotel", "User", "What happened"], key="audit", height=520)
    st.download_button("Download (Excel/CSV)", df.to_csv(index=False).encode(), "hoi_activity_log.csv", icon=":material/download:")
ui.footer()
