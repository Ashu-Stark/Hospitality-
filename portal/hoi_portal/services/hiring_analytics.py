"""Officials' "Workforce market" view of the hiring board: aggregates only, never a person or a profile.

* Demand = openings in open job posts (job posts are public information).
* Supply = visible (public) job-seeker profiles. A candidate counts for every skill they list and for every district
  they prefer; a candidate open to "any district" counts for every district.
* k-anonymity: any supply figure based on fewer than K_MIN candidates is suppressed (null + reason), and so is the
  gap derived from it. Time-to-fill needs at least K_MIN filled posts.
* Seasonal curve: openings per calendar month from the season windows of posts made in the last 12 months
  (permanent/undated posts count in every month) vs candidates available in that month.
Everything is labelled synthetic: the seed generates the bulk of the data.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta

from .. import catalog, mongo
from ..seed.districts import BY_ID as DISTRICTS
from ..seed.districts import DISTRICTS as DISTRICT_LIST
from ..seed.skills import SKILLS as SKILL_LIST
from .hiring import _season_months

K_MIN = 5
SUPPRESS_REASON = f"Fewer than {K_MIN} candidates in this group, so the number is hidden to protect privacy (k-anonymity)."


def _available_months(p: dict) -> set[int]:
    f, t = p.get("available_from"), p.get("available_to")
    if not f and not t:
        return set(range(1, 13))
    a = date.fromisoformat(f) if f else date.today()
    b = date.fromisoformat(t) if t else a + timedelta(days=365)
    months, cur = set(), date(a.year, a.month, 1)
    while cur <= b and len(months) < 12:
        months.add(cur.month)
        cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
    return months


def _k(n: int) -> int | None:
    return n if n >= K_MIN else None


def workforce_market(district: str | None) -> dict:
    d = mongo.db()
    today = date.today().isoformat()
    jf = {"district": district} if district else {}
    jobs = [mongo.clean(j) for j in d.job_posts.find(jf)]
    open_jobs = [j for j in jobs if j["status"] == "open" and j["closes_on"] >= today]
    pf: dict = {"visibility": "public"}
    if district:
        pf["$or"] = [{"districts": district}, {"districts": {"$size": 0}}]
    profs = list(d.seeker_profiles.find(pf, {"skill_keys": 1, "districts": 1, "available_from": 1, "available_to": 1}))

    # By skill.
    demand_skill, posts_skill = Counter(), Counter()
    for j in open_jobs:
        for k in j["skills"]:
            demand_skill[k] += j["openings"]
            posts_skill[k] += 1
    supply_skill = Counter(k for p in profs for k in set(p.get("skill_keys") or []))
    by_skill = []
    for s in SKILL_LIST:
        k = s["key"]
        if not demand_skill[k] and not supply_skill[k]:
            continue
        sup = _k(supply_skill[k])
        by_skill.append(
            {
                "key": k,
                "label": s["label"],
                "category": s["category"],
                "openings": demand_skill[k],
                "open_posts": posts_skill[k],
                "candidates": sup,
                "gap": demand_skill[k] - sup if sup is not None else None,
                "suppressed": sup is None,
            }
        )
    by_skill.sort(key=lambda r: (-r["openings"], r["label"]))

    # By district (state scope: all 13; officer scope: own district only).
    keys = [district] if district else [x["id"] for x in DISTRICT_LIST]
    all_profs = profs if district else list(d.seeker_profiles.find({"visibility": "public"}, {"districts": 1}))
    by_district = []
    for k in keys:
        n_open = [j for j in open_jobs if j["district"] == k]
        sup_n = sum(1 for p in all_profs if not p.get("districts") or k in p["districts"])
        sup = _k(sup_n)
        openings = sum(j["openings"] for j in n_open)
        by_district.append(
            {
                "key": k,
                "label": DISTRICTS[k]["name"],
                "openings": openings,
                "open_posts": len(n_open),
                "candidates": sup,
                "gap": openings - sup if sup is not None else None,
                "suppressed": sup is None,
            }
        )

    # Seasonal demand vs supply by calendar month.
    since = mongo.now() - timedelta(days=365)
    demand_m, supply_m = [0] * 12, [0] * 12
    for j in jobs:
        if mongo.aware(j["created_at"]) < since:
            continue
        for m in _season_months(j):
            demand_m[m - 1] += j["openings"]
    for p in profs:
        for m in _available_months(p):
            supply_m[m - 1] += 1

    # Time to fill (posted -> closed as filled), in days.
    fill_days = [
        (mongo.aware(j["closed_at"]) - mongo.aware(j["created_at"])).total_seconds() / 86400
        for j in jobs
        if j.get("closed_reason") == "filled" and j.get("closed_at")
    ]
    ttf = {
        "filled_posts": len(fill_days),
        "median_days": round(statistics.median(fill_days), 1) if len(fill_days) >= K_MIN else None,
        "suppressed": len(fill_days) < K_MIN,
        "reason": None if len(fill_days) >= K_MIN else f"Fewer than {K_MIN} filled posts in scope; not enough to report.",
    }
    by_type = defaultdict(int)
    for j in open_jobs:
        by_type[j["job_type"]] += j["openings"]
    apps_30 = d.job_applications.count_documents(
        {**({"district": district} if district else {}), "created_at": {"$gte": mongo.now() - timedelta(days=30)}}
    )
    return {
        "synthetic": True,
        "note": catalog.SYNTHETIC_NOTE,
        "scope": {"district": district, "district_name": DISTRICTS[district]["name"] if district else "All districts (state)"},
        "generated_at": mongo.iso(mongo.now()),
        "k_min": K_MIN,
        "suppress_reason": SUPPRESS_REASON,
        "source": "Hiring board job posts and visible job-seeker profiles, aggregated. Never per person.",
        "totals": {
            "open_posts": len(open_jobs),
            "openings": sum(j["openings"] for j in open_jobs),
            "candidates": _k(len(profs)),
            "applications_30d": apps_30,
            "openings_by_type": dict(by_type),
        },
        "by_skill": by_skill,
        "by_district": by_district,
        "seasonal": {
            "months": list(range(1, 13)),
            "openings": demand_m,
            "candidates": [_k(v) for v in supply_m],
            "note": "Openings from season windows of posts made in the last 12 months (permanent posts count in every month).",
        },
        "time_to_fill": ttf,
    }
