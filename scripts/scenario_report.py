"""Scenario report for the FICTIONAL "Himsagar Ridge Resort, Mussoorie" (ALL DATA SYNTHETIC).

    .venv\\Scripts\\python.exe scripts\\scenario_report.py                 # in-process, mongomock only (offline)
    .venv\\Scripts\\python.exe scripts\\scenario_report.py --live          # + checks against the deployed services
    .venv\\Scripts\\python.exe scripts\\scenario_report.py --live-only --ops-url ... --platform-url ...
Options: --stress N (default 100), --seed S, --json PATH (write every number), --skip-day.

In-process sections (scripts/hoi_scenarios.py): roster demo week, roster stress (random carry-in as the backend stress
test, and the carry-in from the data), 4 rolling weeks, attrition scoring + closed loop, a full simulated day of jobs
through the real dispatch engine (rooms, guest concierge on its rule-based path, late checkout, feedback, inventory),
voice onboarding (typed) creating the hotel. The live checks only use the public HTTP APIs (demo logins; they never read
a database URI) and say which results need the new code deployed. Live dispatch checks create a few jobs in the demo
tenant and remove them at the end (POST /dispatch/reset); reseed afterwards for a pristine demo (scripts/reseed_atlas.py).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hoi_scenarios as hs  # noqa: E402

OPS_URL = "https://hoi-ops.onrender.com"
PLATFORM_URL = "https://hoi-platform-api.onrender.com"
HS_IDS = {f"HS{n:02d}" for n in range(1, 21)}


def line(title: str) -> None:
    print(f"\n=== {title} " + "=" * max(3, 70 - len(title)))


def show(d: dict, keys: list[str] | None = None, indent: str = "  ") -> None:
    for k, v in d.items():
        if keys is None or k in keys:
            print(f"{indent}{k}: {v}")


# ---------------------------------------------------------------------------------------------- in-process
def run_offline(args: argparse.Namespace) -> dict:
    hs.configure_offline_env()
    logging.disable(logging.WARNING)
    out: dict = {"assumptions": hs.SIM_ASSUMPTIONS}
    t0 = time.perf_counter()
    ops = hs.ops_client()

    line("Roster: demo week 2029-12-24 (19 rostered staff, backend/hotels/himsagar.yaml)")
    demo = hs.roster_demo_week(ops)
    demo_out = {k: v for k, v in demo.items() if k != "roster"}
    out["roster_demo_week"] = demo_out
    show(
        demo_out,
        [
            "status",
            "method",
            "hard_violations",
            "solve_seconds",
            "shifts",
            "coverage_pct",
            "overtime_hours",
            "understaffed_shifts",
            "max_hours_spread",
            "max_weekend_spread",
        ],
    )

    for mode in ("random", "data"):
        line(f"Roster stress: {args.stress} scenarios, carry-in {mode}")
        st = hs.roster_stress(args.stress, args.seed, carry_mode=mode)
        out[f"roster_stress_{mode}"] = {k: v for k, v in st.items() if k != "results"}
        show(
            st,
            [
                "solved",
                "infeasible",
                "infeasible_with_causes",
                "hard_violations_total",
                "statuses",
                "by_kind",
                "infeasible_causes_by_department",
                "solve_seconds",
                "coverage_pct_mean",
                "coverage_pct_min",
                "overtime_hours_mean",
                "overtime_hours_max",
                "hours_spread_max",
                "weekend_spread_max",
            ],
        )
        for ex in st["examples_infeasible"][:3]:
            print(f"    e.g. #{ex['i']} {ex['kind']} ({ex['desc']}): {ex['causes'][0]}")

    line("Roster: 4 rolling weeks (run length and last shift carried week to week)")
    roll = hs.roster_rolling(4)
    out["roster_rolling"] = roll
    for w in roll["weeks"]:
        print(
            f"  {w['week_start']}: {w['status']}, hard {w['hard_violations']}, coverage {w.get('coverage_pct')}%, "
            f"overtime {w.get('overtime_hours')} h, rest across boundary {w['rest_violations_across_boundary']}"
            + (f", causes {w['causes']}" if w["causes"] else "")
        )
    print(
        f"  stitched longest run {roll['max_consecutive_days_stitched']} (limit {roll['limit']}), "
        f"rest violations across boundaries {roll['rest_violations_across_boundaries']}"
    )
    before = hs.roster_rolling(4, carry_last_shift=False)
    out["roster_rolling_without_last_shift"] = {"rest_violations_across_boundaries": before["rest_violations_across_boundaries"]}
    print(
        f"  (without carrying the last shift, as before this change: "
        f"{before['rest_violations_across_boundaries']} rest violations across boundaries)"
    )

    line("Attrition scoring + closed loop (19 rostered staff; HS01 manager not scored)")
    loop = hs.ops_loop(ops)
    out["loop"] = {k: v for k, v in loop.items() if k != "bands_by_employee"}
    show(loop, ["scored", "bands", "segments", "flagged", "interventions", "metrics"])
    for p in loop["people"]:
        print(
            f"    {p['employee_id']}: drivers {p['top_drivers']}; baseline {p['baseline']} -> protected "
            f"{p['protected']} (risk change {p['risk_change']:+.4f}, a SIMULATION)"
        )
    for k, v in loop["totals"].items():
        print(f"    {k} roster: {v}")

    if not args.skip_day:
        line("One full day of operations through the real dispatch engine (virtual clock)")
        sim = hs.DaySim(ops, seed=args.seed, roster=demo["roster"], bands=loop["bands_by_employee"])
        day = sim.run()
        out["day"] = day
        show(
            day,
            [
                "day",
                "jobs_total",
                "final_status",
                "every_job_assigned_or_escalated",
                "escalated_unassigned",
                "escalated_jobs",
                "offers",
                "off_shift_or_wrong_department_offers",
                "response_min_median",
                "response_min_p90",
                "completion_min_median",
                "completion_min_p90",
                "on_time_pct",
            ],
        )
        print("  events:", day["events"])
        for d, v in day["by_department"].items():
            print(f"    {d}: {v}")
        print("  load per worker (jobs done, by department/shift):", {k: v["jobs_done"] for k, v in day["load_per_worker"].items()})
        print("  retention guard:", day["retention_guard"])
        print("  performance (k>=5 rule):", {k: v for k, v in day["performance"].items() if k != "scores"})
        print("    scores (score, completed jobs):", day["performance"]["scores"])
        line("Rooms flow (all 24 rooms), guest concierge, late checkout, feedback, inventory")
        show(day["rooms"])
        print("  concierge (rule-based path, no AI calls):", day["concierge"])
        print("  guest services:", day["guest_services"])
        print("  inventory:", day["inventory"])
        out["demo_roster_assignments"] = demo["roster"]["assignments"]

    line("Voice onboarding (typed Hinglish answers, rule-based extractor) creating the hotel")
    onb = hs.onboarding_demo(ops)
    out["onboarding"] = onb
    show(onb)
    out["seconds"] = round(time.perf_counter() - t0, 1)
    print(f"\n(in-process total {out['seconds']} s; SYNTHETIC data, FICTIONAL hotel)")
    return out


# ---------------------------------------------------------------------------------------------- live
class Live:
    def __init__(self, base: str, timeout: float = 90, headers: dict | None = None) -> None:
        import httpx

        self.base, self.c = base.rstrip("/"), httpx.Client(base_url=base.rstrip("/"), timeout=timeout, headers=headers or {})
        self.checks: list[dict] = []

    def call(self, method: str, path: str, **kw):  # noqa: ANN201
        for attempt in range(3):  # free-tier services sleep: the first request can take ~60 s
            try:
                return self.c.request(method, path, **kw)
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    raise
                print(f"    ({path}: {type(e).__name__}, retrying)")
                time.sleep(5)
        return None

    def check(self, name: str, ok: bool, detail: object = "", needs_deploy: bool = False) -> None:
        tag = "PASS" if ok else ("NEEDS NEW CODE" if needs_deploy else "FAIL")
        self.checks.append({"check": name, "result": tag, "detail": detail})
        print(f"  [{tag}] {name}: {detail}")


def live_ops(url: str) -> list[dict]:
    line(f"LIVE ops backend {url}")
    key = os.getenv("HOI_OPS_API_KEY", "").strip()  # the ops API's shared secret (backend/auth.py); never printed
    L = Live(url, timeout=180, headers={"X-HOI-Key": key} if key else None)
    r = L.call("GET", "/health")
    h = r.json() if r is not None and r.status_code == 200 else {}
    L.check("health", r is not None and r.status_code == 200, {"database": h.get("database"), "mock": h.get("mock")})
    r = L.call("GET", "/forecast", params={"from": "2029-12-24", "to": "2029-12-30"})
    L.check("forecast demo week", r.status_code == 200, [d["mean"] for d in r.json()["days"]] if r.status_code == 200 else r.text[:200])
    r = L.call("POST", "/attrition/score", json={})
    ids = sorted(s["employee_id"] for s in r.json()) if r.status_code == 200 else []
    L.check(
        "attrition scores the 19 HS staff",
        set(ids) == HS_IDS - {"HS01"},
        f"{len(ids)} scored, e.g. {ids[:4]}",
        needs_deploy=r.status_code == 200,
    )
    t0 = time.perf_counter()
    r = L.call("POST", "/roster/generate", json={"week_start": "2029-12-24"})
    secs = round(time.perf_counter() - t0, 2)
    if r.status_code == 200:
        ro = r.json()
        staff = {a["employee_id"] for a in ro["assignments"]}
        L.check(
            "roster demo week (HS staff, 0 hard violations)",
            ro["status"] != "infeasible" and staff <= HS_IDS and not ro["hard_violations"],
            {"status": ro["status"], "method": ro["method"], "causes": ro["causes"][:2], "staff": len(staff)},
            needs_deploy=True,
        )
        cov = [c["coverage"] for c in ro["coverage"]]
        L.check(
            "roster from the MongoDB cache (cached_db, < 2 s)",
            ro["method"] == "cached_db" and secs < 2,
            {"method": ro["method"], "seconds": secs, "coverage": cov},
            needs_deploy=True,
        )
    else:
        L.check("roster demo week", False, r.text[:200], needs_deploy=True)
    t0 = time.perf_counter()
    r = L.call("POST", "/loop/run")
    print(f"    (/loop/run took {time.perf_counter() - t0:.1f} s)")
    L.check(
        "closed loop",
        r.status_code == 200 and set(r.json().get("flagged", [])) <= HS_IDS,
        r.json().get("flagged") if r.status_code == 200 else r.text[:200],
        needs_deploy=True,
    )
    r = L.call("GET", "/metrics/overview")
    L.check("metrics overview", r.status_code == 200, r.json() if r.status_code == 200 else r.text[:200])
    return L.checks


def live_platform(url: str, assignments: list[dict] | None) -> list[dict]:
    line(f"LIVE platform API {url}")
    L = Live(url, timeout=120)
    r = L.call("GET", "/ready")
    L.check("ready (pings MongoDB)", r is not None and r.status_code == 200, r.text[:120] if r is not None else "")
    s = L.call("POST", "/auth/demo/demo.owner")
    if s.status_code != 200:
        L.check("demo owner login", False, s.text[:200])
        return L.checks
    sess = s.json()
    owner = {"Authorization": f"Bearer {sess['token']}"}
    t = sess.get("tenant") or {}
    L.check("demo owner login", True, t.get("name"))
    L.check(
        "tenant logo_url in the login response",
        t.get("logo_url") == "/shared/brand/himsagar-logo.svg",
        t.get("logo_url"),
        needs_deploy=True,
    )
    props = L.call("GET", "/workspace/properties", headers=owner).json()
    L.check(
        "property is the demo hotel",
        [p["name"] for p in props] == ["Himsagar Ridge Resort, Mussoorie (demo)"] and props[0]["rooms"] == 24,
        [(p["name"], p["rooms"]) for p in props],
    )
    rooms = L.call("GET", "/rooms", headers=owner).json()
    nums = sorted(x["number"] for x in rooms["rooms"])
    L.check("24 rooms 101-108, 201-208, 301-308", nums == [f"{f}{i:02d}" for f in (1, 2, 3) for i in range(1, 9)], rooms["summary"])
    staff = L.call("GET", "/workspace/staff", headers=owner).json()
    sids = {x["employee_id"] for x in staff}
    L.check(
        "20 staff HS01-HS20 (ids + role titles only)",
        HS_IDS <= sids,
        f"{len(sids)} staff; role_title present: {all(x.get('role_title') for x in staff if x['employee_id'] in HS_IDS)}",
    )
    prof = L.call("GET", "/hotel/profile", headers=owner).json()
    L.check("hotel profile", "(demo)" in prof.get("display_name", ""), prof.get("display_name"))
    L.check("profile logo_url", prof.get("logo_url") == "/shared/brand/himsagar-logo.svg", prof.get("logo_url"))
    accts = L.call("GET", "/auth/demo-accounts").json()
    names = {a["username"] if isinstance(a, dict) else a[0] for a in accts}
    L.check("demo accounts include HS05 / demo.frontoffice", {"HS05", "demo.frontoffice"} <= names, sorted(names), needs_deploy=True)
    tok = rooms["rooms"][0]["guest_token"]
    g = L.call("GET", f"/public/guest/{tok}").json()
    L.check(
        "guest page profile",
        "(demo)" in (g.get("profile") or {}).get("display_name", ""),
        {"hotel": g.get("hotel"), "logo_url": (g.get("profile") or {}).get("logo_url")},
    )
    L.check(
        "guest page logo_url (public profile)",
        (g.get("profile") or {}).get("logo_url") == "/shared/brand/himsagar-logo.svg",
        (g.get("profile") or {}).get("logo_url"),
        needs_deploy=True,
    )

    # ---- a compressed real-time dispatch run (decisions immediately; offers never left to time out)
    if assignments:
        r = L.call("PUT", "/dispatch/roster", json={"week_start": "2029-12-24", "assignments": assignments}, headers=owner)
        L.check("publish the demo-week roster", r.status_code == 200, r.json() if r.status_code == 200 else r.text[:150])
    day = "2029-12-25"
    working = {
        a["employee_id"]: next((x["department"] for x in staff if x["employee_id"] == a["employee_id"]), "")
        for a in (assignments or [])
        if a["date"] == day and a["shift"] == "morning"
    }
    r = L.call(
        "PUT", "/dispatch/context", json={"day": day, "shift": "morning", "working": working, "bands": {}, "floors": 3}, headers=owner
    )
    L.check("dispatch context = morning shift of 2029-12-25", r.status_code == 200, f"{len(working)} on shift")
    photo = hs.jpeg()
    done, off_shift, flows = 0, 0, []

    def work(job: dict, decline_first: bool = False) -> str:
        nonlocal done, off_shift
        for _ in range(6):
            job = next(j for j in L.call("GET", "/dispatch/jobs", headers=owner).json() if j["id"] == job["id"])
            if job["status"] != "offered":
                return job["status"]
            emp = job["offer_to"]
            off_shift += emp not in working
            if decline_first:
                decline_first = False
                L.call("POST", f"/dispatch/jobs/{job['id']}/decline", json={"employee_id": emp}, headers=owner)
                continue
            L.call("POST", f"/dispatch/jobs/{job['id']}/accept", json={"employee_id": emp}, headers=owner)
            for kind, step in (("before", "start"), ("after", "complete")):
                L.call(
                    "POST",
                    f"/dispatch/jobs/{job['id']}/photos",
                    data={"kind": kind, "employee_id": emp},
                    files={"file": ("p.jpg", photo, "image/jpeg")},
                    headers=owner,
                )
                L.call("POST", f"/dispatch/jobs/{job['id']}/{step}", json={"employee_id": emp}, headers=owner)
            done += 1
            return "done"
        return job["status"]

    occupied = [x for x in rooms["rooms"] if x["status"] == "occupied"][:2]
    for room in occupied:  # checkout -> cleaning -> inspection -> ready -> check-in (restores occupancy)
        out = L.call("POST", f"/rooms/{room['id']}/checkout", headers=owner).json()
        st = work({"id": out["current_job_id"]})
        ins = L.call("POST", f"/rooms/{room['id']}/inspect", json={"passed": True}, headers=owner)
        back = L.call("POST", f"/rooms/{room['id']}/check-in", headers=owner)
        flows.append(
            (
                room["number"],
                st,
                ins.json().get("status") if ins.status_code == 200 else ins.status_code,
                back.json().get("status") if back.status_code == 200 else back.status_code,
            )
        )
    L.check(
        "rooms flow checkout -> clean -> inspect -> ready -> check-in",
        all(f[1] == "done" and f[2] == "ready" and f[3] == "occupied" for f in flows),
        flows,
    )
    gtok = [x for x in rooms["rooms"] if x["status"] == "occupied"][3]["guest_token"]
    created = []
    for key in ("towels", "tea", "hot_water"):
        r = L.call("POST", f"/public/guest/{gtok}/requests", json={"key": key})
        created.append(r.status_code)
    jobs = [j for j in L.call("GET", "/dispatch/jobs", headers=owner).json() if j["status"] == "offered"]
    results = []
    for i, j in enumerate(jobs):
        st = work(j, decline_first=(i == 0))
        if st == "unassigned":  # the only on-shift worker declined: escalated; the supervisor retries
            L.call("POST", f"/dispatch/jobs/{j['id']}/retry", headers=owner)
            st = "escalated->" + work(j)
        results.append(st)
    L.check(
        "guest requests dispatched and completed (one decline re-offered)",
        created == [201] * 3 and results and all(x.endswith("done") for x in results),
        {"created": created, "results": results},
    )
    mj = L.call(
        "POST",
        "/dispatch/jobs",
        json={"title": "Geyser not heating · room 204 (live test)", "department": "maintenance", "room": "204", "urgency": "high"},
        headers=owner,
    )
    L.check(
        "maintenance fault dispatched",
        mj.status_code == 201 and work(mj.json()) in ("done", "unassigned"),
        mj.json().get("status") if mj.status_code == 201 else mj.text[:150],
    )
    L.check("no offer to an off-shift worker", off_shift == 0, f"{off_shift} off-shift offers; {done} jobs done")
    chat = L.call("POST", f"/public/guest/{gtok}/chat", json={"message": "wifi?"})
    L.check(
        "concierge chat answers from the profile",
        chat.status_code == 200 and "Himsagar" in chat.json().get("reply", ""),
        {"source": chat.json().get("source") if chat.status_code == 200 else chat.status_code},
    )
    late = L.call("POST", f"/public/guest/{gtok}/late-checkout", json={"until": "13:00"})
    if late.status_code == 201:
        lid = late.json()["id"]
        dec = L.call("POST", f"/guest-services/late-checkouts/{lid}/decide", json={"approve": True, "note": "live test"}, headers=owner)
        L.check(
            "late checkout request + approval",
            dec.status_code == 200,
            dec.json().get("status") if dec.status_code == 200 else dec.text[:150],
        )
    else:
        L.check("late checkout request", False, late.text[:150])
    fb = L.call("POST", f"/public/guest/{gtok}/feedback", json={"rating": 5, "comment": "live scenario test", "lang": "en"})
    L.check("feedback", fb.status_code in (201, 409), fb.status_code)
    perf = L.call("GET", "/dispatch/performance?days=1", headers=owner)
    L.check(
        "performance endpoint (k>=5 rule)",
        perf.status_code == 200
        and all((w.get("score") is not None) == (w.get("completed_jobs", 0) >= 5) for w in perf.json().get("workers", [])),
        {"workers": len(perf.json().get("workers", []))} if perf.status_code == 200 else perf.status_code,
    )
    hs05 = L.call("POST", "/auth/demo/HS05")
    L.check("worker HS05 one-click login", hs05.status_code == 200, hs05.status_code, needs_deploy=True)
    L.call("POST", "/dispatch/reset", headers=owner)  # remove the live test jobs and photos
    return L.checks


# ---------------------------------------------------------------------------------------------- main
def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--live", action="store_true", help="also check the deployed services")
    ap.add_argument("--live-only", action="store_true")
    ap.add_argument("--ops-url", default=OPS_URL)
    ap.add_argument("--platform-url", default=PLATFORM_URL)
    ap.add_argument("--stress", type=int, default=100)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--skip-day", action="store_true")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    report: dict = {
        "hotel": "Himsagar Ridge Resort, Mussoorie (demo)",
        "synthetic": True,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    ok = True
    if not args.live_only:
        report["offline"] = run_offline(args)
        off = report["offline"]
        ok &= off["roster_demo_week"]["hard_violations"] == 0
        ok &= all(off[f"roster_stress_{m}"]["hard_violations_total"] == 0 for m in ("random", "data"))
        ok &= off["roster_rolling"]["rest_violations_across_boundaries"] == 0
        if "day" in off:
            ok &= off["day"]["off_shift_or_wrong_department_offers"] == 0 and off["day"]["every_job_assigned_or_escalated"]
    if args.live or args.live_only:
        assignments = (report.get("offline") or {}).get("demo_roster_assignments")
        if assignments is None:  # live-only: the demo-week roster from the in-process backend (mongomock)
            hs.configure_offline_env()
            logging.disable(logging.WARNING)
            assignments = hs.roster_demo_week(hs.ops_client())["roster"]["assignments"]
        if assignments:
            assignments = [{**a, "date": str(a["date"]) if isinstance(a["date"], date) else a["date"]} for a in assignments]
        report["live"] = {"ops": live_ops(args.ops_url), "platform": live_platform(args.platform_url, assignments)}
        live = report["live"]["ops"] + report["live"]["platform"]
        print(
            f"\nLIVE: {sum(c['result'] == 'PASS' for c in live)} pass, "
            f"{sum(c['result'] == 'NEEDS NEW CODE' for c in live)} need the new code deployed, "
            f"{sum(c['result'] == 'FAIL' for c in live)} fail"
        )
    if args.json:
        args.json.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
        print(f"report written to {args.json}")
    print("\nOVERALL (hard rules, shifts, assignment):", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
