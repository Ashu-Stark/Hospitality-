"""Headless smoke test: sign in through the platform API (embedded), render every page as the right role,
fail on any exception, and check that role filtering hides pages.

    python tests/smoke.py            # MOCK ML data (offline)
    python tests/smoke.py --live     # ML data from API_BASE_URL
    python tests/smoke.py Dispatch   # only pages whose path contains "Dispatch"
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ["USE_MOCKS"] = "false" if "--live" in sys.argv else "true"
os.environ.setdefault("PLATFORM_API_URL", "embedded")

from streamlit.testing.v1 import AppTest  # noqa: E402

from lib import access, auth, platform  # noqa: E402


def session(username: str) -> dict:
    s = platform.demo_login(username)
    state = {"user": s["user"], "auth_token": s["token"], "tenant": s["tenant"], "welcomed": True}
    if s["user"]["role"] == "platform_admin":
        imp = platform.impersonate(auth.DEMO_TENANT, s["token"])
        state.update(platform_token=s["token"], auth_token=imp["token"], tenant=imp["tenant"])
    return state


SESSIONS = {who: session(u) for who, u in (("platform", "platform"), ("worker", "E134"))}
CASES = [("login.py", None)]
CASES += [(f, "platform") for f, _, _ in access.CONSOLE_PAGES + access.HOTEL_PAGES]
CASES += [(f, "worker") for f, _, _ in access.EMPLOYEE_PAGES]
only = [a for a in sys.argv[1:] if not a.startswith("--")]
failed = 0

for page, who in CASES:
    if only and not any(o in page for o in only):
        continue
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    for k, v in (SESSIONS.get(who) or {}).items():
        at.session_state[k] = v
    at.session_state["_smoke_page"] = page
    at.run()
    errs = [e.value for e in at.exception]
    banners = [m.value for m in at.markdown if "ss-banner red" in str(m.value)]
    failed += bool(errs)
    print(
        f"{'FAIL' if errs else 'ok':4} {page:34} as {who or 'anonymous':9} (markdown={len(at.markdown)}, buttons={len(at.button)}, "
        f"error-banners={len(banners)})"
    )
    for e in errs:
        print("     exception:", str(e)[:1500])
    for b in banners:
        print("     banner:", b[b.find("<b>") :][:200])

if not only or any(o in "pages/15_Hotel_Setup.py" for o in only):  # Hotel setup (voice): a typed flow end to end
    HS = "pages/15_Hotel_Setup.py"
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    for k, v in SESSIONS["platform"].items():
        at.session_state[k] = v
    at.session_state["_smoke_page"] = HS
    at.run()
    steps = []
    try:
        next(b for b in at.button if b.label == "Start a new setup").click().run()
        answers = {
            "rooms": "hamare paas barah kamre hain",
            "location": "Mussoorie",
            "departments": "housekeeping mein teen, kitchen mein do, front desk pe do",
            "peak_months": "may se june aur december",
            "shifts": "subah 7 se 3, shaam 3 se 11",
            "overtime_rate_multiplier": "double",
            "min_rest_hours": "das ghante",
        }
        for _ in range(10):
            q = at.session_state["onb"].get("question") if "onb" in at.session_state else None
            if not q:
                break
            at.text_input[0].input(answers[q["field"]])
            next(b for b in at.button if b.label == "Send answer").click().run()
            steps.append(q["field"])
        for cb in at.checkbox:
            if "qualified person" in cb.label:
                cb.check()
        at.run()
        next(b for b in at.button if b.label == "Confirm and save").click().run()
        res = at.session_state["onb_confirmed"] if "onb_confirmed" in at.session_state else None
        errs = [e.value for e in at.exception]
        ok = not errs and res is not None and res.get("created") and len(steps) == 7
    except Exception as e:  # noqa: BLE001
        ok, errs, res = False, [repr(e)], None
    failed += not ok
    print(f"{'ok' if ok else 'FAIL':4} {HS} typed flow: asked {steps}, confirm -> {res}")
    for e in errs:
        print("     exception:", str(e)[:1500])

if not only or any(o in "pages/15_Hotel_Setup.py" for o in only):  # the cached Hindi demo transcript, button by button
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    for k, v in SESSIONS["platform"].items():
        at.session_state[k] = v
    at.session_state["_smoke_page"] = "pages/15_Hotel_Setup.py"
    at.run()
    try:
        at.radio[0].set_value(at.radio[0].options[1]).run()  # Hindi
        next(b for b in at.button if b.label == "Start a new setup").click().run()
        n = 0
        while at.session_state["onb"].get("question") and n < 10:
            next(b for b in at.button if b.label == "Use the cached Hindi demo answer").click().run()
            n += 1
        f = at.session_state["onb"]["fields"]
        errs = [e.value for e in at.exception]
        got = (f["rooms"]["value"], f["location"]["value"], f["hotel_type"]["value"], f["peak_months"]["value"])
        ok = (
            not errs
            and got == (12, "Mussoorie", "homestay", [5, 6, 12])
            and f["departments"]["value"]
            == {
                "housekeeping": 3,
                "kitchen": 2,
                "front_office": 2,
            }
        )
    except Exception as e:  # noqa: BLE001
        ok, errs, got = False, [repr(e)], None
    failed += not ok
    print(f"{'ok' if ok else 'FAIL':4} pages/15_Hotel_Setup.py cached Hindi demo: summary {got}")
    for e in errs:
        print("     exception:", str(e)[:1500])

if not only:  # role filtering: pages outside a role's set must not be routable for that role
    for role, must_not in (("hr", "pages/13_Inventory.py"), ("storekeeper", "pages/2_Risk_List.py"), ("worker", "pages/1_Overview.py")):
        visible = access.EMPLOYEE_PAGES if role == "worker" else [p for p in access.HOTEL_PAGES if role in auth.ACCESS.get(p[0], set())]
        ok = must_not not in [f for f, _, _ in visible]
        failed += not ok
        print(f"{'ok' if ok else 'FAIL':4} access: {role} cannot open {must_not}")
sys.exit(1 if failed else 0)
