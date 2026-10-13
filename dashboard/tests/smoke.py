"""Headless smoke test: sign in through the platform API (embedded), render every page of this portal as the right role,
fail on any exception, and check that role and portal filtering hide pages.

    python tests/smoke.py                      # hotel admin portal (ADMIN_PORTAL=hotel, the default), MOCK ML data
    ADMIN_PORTAL=super python tests/smoke.py   # super-admin portal: console pages only, hotel roles refused
    python tests/smoke.py --live               # ML data from API_BASE_URL
    python tests/smoke.py Dispatch             # only pages whose path contains "Dispatch"
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ["USE_MOCKS"] = "false" if "--live" in sys.argv else "true"
os.environ.setdefault("PLATFORM_API_URL", "embedded")
os.environ.setdefault("HOI_LOGIN_RATE_PER_MINUTE", "1000")  # the test signs in more than 10 times a minute (embedded API only)

from streamlit.testing.v1 import AppTest  # noqa: E402

from lib import access, auth, config, platform  # noqa: E402

SUPER = config.is_super()
print(f"portal: {config.portal()}")


def session(username: str, open_hotel: bool = True) -> dict:
    """Session state as the app holds it after sign-in. In the hotel portal a platform admin has chosen the demo hotel
    (audited impersonation) unless open_hotel is False; in the super-admin portal they hold only the console token."""
    s = platform.demo_login(username)
    state = {"user": s["user"], "auth_token": s["token"], "tenant": s["tenant"], "welcomed": True}
    if s["user"]["role"] == "platform_admin":
        state.update(platform_token=s["token"], tenant=None)
        if open_hotel and not SUPER:
            imp = platform.impersonate(auth.DEMO_TENANT, s["token"])
            state.update(auth_token=imp["token"], tenant=imp["tenant"], imp_tid=auth.DEMO_TENANT)
    return state


def run_page(page: str, state: dict | None) -> AppTest:
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    for k, v in (state or {}).items():
        at.session_state[k] = v
    at.session_state["_smoke_page"] = page
    at.run()
    return at


def nav_of(at: AppTest) -> list[str]:
    return [f for f, _, _ in (at.session_state["_nav"] if "_nav" in at.session_state else [])]


def report(ok: bool, msg: str, errs: list | None = None) -> int:
    print(f"{'ok' if ok else 'FAIL':4} {msg}")
    for e in errs or []:
        print("     exception:", str(e)[:1500])
    return 0 if ok else 1


def _login_script():
    import streamlit as st

    from lib import auth

    st.session_state["err"] = auth.demo_login(st.session_state["who"])
    st.session_state["signed_in"] = auth.current() is not None


def try_login(username: str) -> tuple[str | None, bool]:
    """Sign in through the app's real sign-in code path inside a Streamlit run: (error message, signed in?)."""
    at = AppTest.from_function(_login_script, default_timeout=60)
    at.session_state["who"] = username
    at.run()
    return at.session_state["err"], at.session_state["signed_in"]


DEMO_USERS = {
    "platform": "platform",
    "worker": "HS05",
    "owner": "demo.owner",
    "hr": "demo.hr",
    "dept_head": "demo.housekeeping",
    "storekeeper": "demo.store",
    "homestay": "demo.homestay",
}
SESSIONS = {who: session(u) for who, u in DEMO_USERS.items()}
HP, GS, INS = "pages/16_Hotel_Profile.py", "pages/17_Guest_Services.py", "console/3_Insights.py"
CASES = [("login.py", None)]
if SUPER:
    CASES += [(f, "platform") for f, _, _ in access.SUPER_PAGES]
else:
    CASES += [(f, "platform") for f, _, _ in access.HOTEL_PAGES]
    CASES += [(f, "worker") for f, _, _ in access.EMPLOYEE_PAGES]
    # hospitality suite admin pages, rendered as each hotel role that may open them (read-only roles included)
    CASES += [(HP, r) for r in ("owner", "dept_head", "hr", "storekeeper")] + [(GS, r) for r in ("owner", "dept_head", "hr")]
only = [a for a in sys.argv[1:] if not a.startswith("--")]
failed = 0

for page, who in CASES:
    if only and not any(o in page for o in only):
        continue
    at = run_page(page, SESSIONS.get(who))
    errs = [e.value for e in at.exception]
    banners = [m.value for m in at.markdown if "ss-banner red" in str(m.value)]
    failed += bool(errs)
    if who and page not in nav_of(at):  # the router would fall back to another page: not a real render
        errs.append(f"{page} is not in the {who} navigation")
        failed += 1
    print(
        f"{'FAIL' if errs else 'ok':4} {page:34} as {who or 'anonymous':9} (markdown={len(at.markdown)}, buttons={len(at.button)}, "
        f"error-banners={len(banners)})"
    )
    for e in errs:
        print("     exception:", str(e)[:1500])
    for b in banners:
        print("     banner:", b[b.find("<b>") :][:200])

# ------------------------------------------------------------------ super-admin portal: portal rules, then done
if SUPER:
    if not only:
        for who, u in DEMO_USERS.items():
            if who == "platform":
                continue
            err, signed_in = try_login(u)
            failed += report(
                bool(err) and not signed_in and config.hotel_portal_url() in err,
                f"portal: {who} is refused by the platform console and pointed to the hotel portal",
            )
            at = run_page("console/0_Home.py", SESSIONS[who])  # e.g. a hotel session restored from a shared cookie
            failed += report(not at.exception and nav_of(at) == ["login.py"], f"portal: a {who} session only gets the sign-in page")
        err, signed_in = try_login("platform")
        failed += report(err is None and signed_in, "portal: platform admin signs in to the platform console")
        at = run_page("home.py", SESSIONS["platform"])
        hotel_files = {f for f, _, _ in access.HOTEL_PAGES + access.EMPLOYEE_PAGES} | {access.PICK_PAGE[0]}
        failed += report(
            nav_of(at) == [f for f, _, _ in access.SUPER_PAGES] and not hotel_files & set(nav_of(at)),
            f"portal: platform admin navigation is the console only {nav_of(at)}",
        )
        at = run_page("console/1_Tenants.py", SESSIONS["platform"])
        links = list(at.get("link_button"))
        failed += report(
            not at.exception and bool(links) and not any(b.label in ("Open", "Open this hotel") for b in at.button),
            f"portal: Hotels page links to the hotel portal ({len(links)} link buttons), no in-app impersonation",
            [e.value for e in at.exception],
        )
    sys.exit(1 if failed else 0)

# ------------------------------------------------------------------ hotel admin portal
if not only:
    for who in ("owner", "hr", "dept_head", "storekeeper", "worker", "platform"):
        nav = nav_of(run_page("home.py", SESSIONS[who]))
        failed += report(bool(nav) and not any(f.startswith("console/") for f in nav), f"portal: {who} has no console pages here")
    err, signed_in = try_login("demo.owner")
    failed += report(err is None and signed_in, "portal: owner signs in to the hotel portal")
    err, signed_in = try_login("platform")
    failed += report(err is None and signed_in, "portal: platform admin may sign in to the hotel portal")
    # a platform admin must choose a hotel first (audited), then sees the banner on every page, and can exit
    at = run_page("home.py", session("platform", open_hotel=False))
    errs = [e.value for e in at.exception]
    failed += report(
        not errs and nav_of(at) == [access.PICK_PAGE[0]], f"portal: platform admin must choose a hotel first {nav_of(at)}", errs
    )
    try:
        next(b for b in at.button if b.key == f"pick_{auth.DEMO_TENANT}").click().run()
        errs = [e.value for e in at.exception]
        opened = at.session_state["imp_tid"] if "imp_tid" in at.session_state else None
        keep = ("user", "auth_token", "platform_token", "tenant", "imp_tid", "welcomed")
        at = run_page("pages/1_Overview.py", {k: at.session_state[k] for k in keep if k in at.session_state})
        errs += [e.value for e in at.exception]
        banner = any("Viewing as platform admin" in str(m.value) for m in at.markdown)
        ok = not errs and opened == auth.DEMO_TENANT and "home.py" in nav_of(at) and banner
        failed += report(ok, f"portal: platform admin opened {opened} (audited) and sees the 'Viewing as platform admin' banner", errs)
        next(b for b in at.button if b.key == "imp_exit").click().run()
        failed += report(nav_of(at) == [access.PICK_PAGE[0]], "portal: Exit returns the platform admin to hotel selection")
    except Exception as e:  # noqa: BLE001
        failed += report(False, f"portal: platform admin hotel selection flow ({e!r})")

if not only:  # grouped navigation: at most five sections; homestay mode shows the minimal page set
    at = run_page("home.py", SESSIONS["owner"])
    nav = nav_of(at)
    secs = access.sections([p for p in access.HOTEL_PAGES if p[0] in nav])
    failed += report(
        len(secs) <= 5 and not at.exception, f"nav: hotel owner sees {len(nav)} pages in {len(secs)} sections {[x[0] for x in secs]}"
    )
    for page in ["home.py", *sorted(access.HOMESTAY_PAGES - {"home.py"})]:
        at = run_page(page, SESSIONS["homestay"])
        errs = [e.value for e in at.exception]
        hn = nav_of(at)
        ok = not errs and page in hn and set(hn) <= access.HOMESTAY_PAGES
        failed += report(ok, f"homestay: {page} renders; nav {len(hn)} pages, all in the homestay set", errs)
    for page in ("pages/5_Roster.py", "pages/2_Risk_List.py", "pages/10_Dispatch.py"):
        at = run_page(page, SESSIONS["homestay"])
        failed += report(page not in nav_of(at), f"homestay: {page} is hidden")
    at = run_page("home.py", SESSIONS["homestay"])
    txt = " ".join(str(m.value) for m in at.markdown)
    failed += report("Deodar Nest" in txt and "Homestay mode" in txt, "homestay: Today shows the homestay name and mode")

if not only or any(o in "pages/15_Hotel_Setup.py" for o in only):  # Hotel setup (voice): a typed flow end to end
    HS = "pages/15_Hotel_Setup.py"
    at = run_page(HS, SESSIONS["platform"])
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
    failed += report(ok, f"{HS} typed flow: asked {steps}, confirm -> {res}", errs)

if not only or any(o in "pages/15_Hotel_Setup.py" for o in only):  # the cached Hindi demo transcript, button by button
    at = run_page("pages/15_Hotel_Setup.py", SESSIONS["platform"])
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
    failed += report(ok, f"pages/15_Hotel_Setup.py cached Hindi demo: summary {got}", errs)

if not only or any(o in p for o in only for p in (HP, GS, INS)):  # wrong roles are denied the new pages
    for page, who in ((GS, "storekeeper"), (GS, "worker"), (HP, "worker"), (INS, "owner"), (INS, "hr"), (INS, "platform")):
        at = run_page(page, SESSIONS[who])
        nav_files = nav_of(at)
        errs = [e.value for e in at.exception]
        failed += report(not errs and page not in nav_files, f"access: {who} is not offered {page} (falls back to {nav_files[0]})", errs)

if not only:  # role filtering: pages outside a role's set must not be routable for that role
    for role, must_not in (
        ("hr", "pages/13_Inventory.py"),
        ("storekeeper", "pages/2_Risk_List.py"),
        ("worker", "pages/1_Overview.py"),
        ("storekeeper", GS),
        ("worker", HP),
    ):
        visible = access.EMPLOYEE_PAGES if role == "worker" else [p for p in access.HOTEL_PAGES if role in auth.ACCESS.get(p[0], set())]
        failed += report(must_not not in [f for f, _, _ in visible], f"access: {role} cannot open {must_not}")
sys.exit(1 if failed else 0)
