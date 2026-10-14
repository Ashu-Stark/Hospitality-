"""Deterministic SYNTHETIC hiring-board data (fixed RNG seed). Nothing here is real.

* 120 candidates "Candidate C-0001" ... "Candidate C-0120" (no accounts), plus the demo job seeker's profile
  (C-0121). Contacts are placeholders "+91-90000-0NNNN", flagged synthetic; no emails.
* 44 job posts from existing synthetic businesses (4 from the demo business owner), 30 open and 14 closed
  (10 filled, 4 withdrawn) so the officials' time-to-fill and seasonal views have something to show.
* Applications in every state, interest requests (pending / accepted / declined), a shortlist and one message thread
  between the two demo accounts.
Inserted only when the hiring collections are empty (see seed.ensure_hiring); never touches other collections.
"""

from __future__ import annotations

import random
import secrets
from datetime import date, datetime, time, timedelta

from .. import catalog, mongo
from ..services import registry
from ..services.hiring import CONSENT_VERSION
from .destinations import BY_ID_DEST
from .districts import BY_ID as DISTRICTS
from .districts import DISTRICTS as DISTRICT_LIST
from .skills import BY_KEY as SKILLS
from .skills import SKILLS as SKILL_LIST

RNG_SEED = 20261013
N_CANDIDATES = 120
N_JOBS_OTHER = 40

CATEGORY_WEIGHTS = {
    "kitchen": 18,
    "housekeeping": 14,
    "front_office": 12,
    "food_beverage": 12,
    "adventure": 14,
    "transport": 10,
    "maintenance": 8,
    "operations": 6,
    "wellness": 6,
    "admin": 3,
    "security": 4,
}
PAY = {  # synthetic monthly INR ranges by category (ASSUMED, illustrative only)
    "kitchen": (11000, 30000),
    "housekeeping": (9000, 16000),
    "front_office": (12000, 28000),
    "food_beverage": (10000, 18000),
    "adventure": (15000, 45000),
    "transport": (14000, 25000),
    "maintenance": (12000, 24000),
    "operations": (10000, 22000),
    "wellness": (15000, 40000),
    "admin": (15000, 30000),
    "security": (10000, 16000),
}
CERTS = {
    "kitchen": ["Food safety training"],
    "food_beverage": ["Food safety training"],
    "adventure": ["First aid", "Wilderness first aid"],
    "mountaineering_guide": ["Basic mountaineering course"],
    "rafting_guide": ["Swift-water rescue"],
    "transport": ["Commercial driving licence"],
    "wellness": ["Yoga teacher training (200 h)", "First aid"],
    "housekeeping": ["Housekeeping skills course"],
    "admin": ["Accounting software course"],
}
TYPE_SKILLS = {
    "hotel": ["front_office", "housekeeping", "fb_service", "cook_indian", "cook_continental", "kitchen_helper", "maintenance", "electrician", "security_guard", "reservations_sales", "laundry"],
    "homestay": ["homestay_host", "cook_pahadi", "housekeeping", "kitchen_helper"],
    "guide": ["trek_guide", "mountaineering_guide"],
    "travel_agent": ["reservations_sales", "tour_coordinator", "accountant"],
    "tour_operator": ["tour_coordinator", "driver_tempo", "trek_guide"],
    "transport": ["driver_taxi", "driver_tempo"],
    "adventure_operator": ["rafting_guide", "paragliding_pilot", "trek_guide"],
    "restaurant": ["cook_indian", "barista", "fb_service", "kitchen_helper", "baker", "cook_pahadi"],
}  # fmt: skip
# Seasonal windows (month, day) by the destination's synthetic profile. ASSUMED, loosely following the seasonality hints.
WINDOWS = {
    "char_dham": ((4, 25), (11, 5)),
    "vof": ((6, 1), (10, 15)),
    "hill_station": ((4, 1), (7, 15)),
    "snow": ((12, 1), (3, 15)),
    "spiritual": ((2, 15), (6, 30)),
    "wildlife": ((10, 15), (6, 15)),
}


def _window_after(anchor: date, win: tuple, ongoing_ok: bool = True) -> tuple[date, date]:
    (m1, d1), (m2, d2) = win
    for y in (anchor.year - 1, anchor.year, anchor.year + 1):
        start = date(y, m1, d1)
        end = date(y + (1 if (m2, d2) < (m1, d1) else 0), m2, d2)
        if (ongoing_ok and end >= anchor + timedelta(days=60)) or start >= anchor:
            return start, end
    return date(anchor.year + 1, m1, d1), date(anchor.year + 1 + (1 if (m2, d2) < (m1, d1) else 0), m2, d2)


def _dt(d: date, hour: int = 10) -> datetime:
    return datetime.combine(d, time(hour, 0), tzinfo=mongo.now().tzinfo)


class HiringGenerator:
    def __init__(self, anchor: date | None = None):
        self.anchor = anchor or mongo.today()
        self.r = random.Random(RNG_SEED)
        self.n_app = 0
        self.n_int = 0

    # ---------------------------------------------------------------- candidates
    def candidate(self, i: int) -> dict:
        r, a = self.r, self.anchor
        cats, weights = list(CATEGORY_WEIGHTS), list(CATEGORY_WEIGHTS.values())
        cat = r.choices(cats, weights)[0]
        in_cat = [s["key"] for s in SKILL_LIST if s["category"] == cat]
        keys = r.sample(in_cat, k=min(len(in_cat), r.choice([1, 1, 2])))
        if r.random() < 0.3:
            other = [s["key"] for s in SKILL_LIST if s["category"] != cat]
            keys.append(r.choice(other))
        primary_years = r.choice([0, 1, 1, 2, 2, 3, 4, 5, 6, 8, 10, 12, 15])
        skills = [{"key": k, "years": primary_years if n == 0 else r.choice([0, 1, 2, 3, 5])} for n, k in enumerate(keys)]
        home = r.choice(DISTRICT_LIST)
        if r.random() < 0.15:
            districts = []
        else:
            same = [x["id"] for x in DISTRICT_LIST if x["division"] == home["division"] and x["id"] != home["id"]]
            districts = [home["id"]] + r.sample(same, k=r.choice([0, 1, 1, 2]))
        langs = ["Hindi"]
        if r.random() < 0.55:
            langs.append("English")
        if r.random() < 0.55:
            langs.append("Garhwali" if home["division"] == "Garhwal" else "Kumaoni")
        if r.random() < 0.08:
            langs.append("Nepali")
        if home["id"] == "dehradun" and r.random() < 0.3:
            langs.append("Jaunsari")
        roll = r.random()
        if roll < 0.5:
            avail = "seasonal"
            start = a + timedelta(days=r.randint(-20, 200))
            frm, to = start.isoformat(), (start + timedelta(days=r.randint(90, 210))).isoformat()
        elif roll < 0.85:
            avail = "permanent"
            frm, to = ((a + timedelta(days=r.randint(0, 45))).isoformat(), None) if r.random() < 0.5 else (None, None)
        else:
            avail, frm, to = "part_time", None, None
        pay_min = pay_max = None
        if r.random() < 0.7:
            lo, hi = PAY[cat]
            pay_min = int(r.randint(lo, hi) / 500) * 500
            pay_max = pay_min + r.choice([2000, 3000, 5000, 8000])
        certs: list[str] = []
        for src in [keys[0], cat]:
            for c in CERTS.get(src, []):
                if r.random() < 0.45 and c not in certs:
                    certs.append(c)
        label = SKILLS[keys[0]]["label"]
        created = mongo.now() - timedelta(days=r.randint(1, 200), hours=r.randint(0, 23))
        code = f"C-{i:04d}"
        return {
            "code": code,
            "display_name": f"Candidate {code}",
            "headline": f"{label}, {primary_years} year{'s' if primary_years != 1 else ''} of experience",
            "skills": skills,
            "skill_keys": [s["key"] for s in skills],
            "certifications": certs[:2],
            "languages": langs,
            "districts": districts,
            "availability": avail,
            "available_from": frm,
            "available_to": to,
            "pay_min": pay_min,
            "pay_max": pay_max,
            "bio": "Synthetic sample profile generated for the hackathon demo. Not a real person.",
            "visibility": "public" if r.random() < 0.92 else "hidden",
            "phone": f"+91-90000-0{i:04d}",
            "email": None,
            "consent": {"version": CONSENT_VERSION, "at": created, "synthetic": True},
            "synthetic": True,
            "created_at": created,
            "updated_at": created,
        }

    def demo_profile(self, user_id: str, code: str) -> dict:
        a = self.anchor
        start, end = _window_after(a, WINDOWS["char_dham"])
        now = mongo.now()
        return {
            "code": code,
            "user_id": user_id,
            "display_name": "Asha (demo)",
            "headline": "Cook for pahadi and Indian food, 4 years in yatra season kitchens",
            "skills": [{"key": "cook_pahadi", "years": 4}, {"key": "cook_indian", "years": 3}, {"key": "kitchen_helper", "years": 2}],
            "skill_keys": ["cook_pahadi", "cook_indian", "kitchen_helper"],
            "certifications": ["Food safety training"],
            "languages": ["Hindi", "Garhwali", "English"],
            "districts": ["rudraprayag", "chamoli"],
            "availability": "seasonal",
            "available_from": max(start, a).isoformat(),
            "available_to": end.isoformat(),
            "pay_min": 15000,
            "pay_max": 20000,
            "bio": "Demo account profile (synthetic). Cooked mandua roti, jhangora kheer and dal for pilgrim groups.",
            "visibility": "public",
            "phone": "+91-90000-09121",
            "email": "demo.seeker@example.invalid",
            "consent": {"version": CONSENT_VERSION, "at": now, "synthetic": True},
            "synthetic": True,
            "created_at": now - timedelta(days=12),
            "updated_at": now - timedelta(days=2),
        }

    # ---------------------------------------------------------------- jobs
    def job(self, n: int, b: dict, skills: list[str], *, open_: bool, filled: bool = True, job_type: str | None = None) -> dict:
        r, a = self.r, self.anchor
        dest = BY_ID_DEST.get(b.get("destination_id")) or {}
        win = WINDOWS.get(dest.get("profile"))
        if open_:
            created_d = a - timedelta(days=r.randint(1, 35))
        else:
            created_d = a - timedelta(days=r.randint(45, 330))
        if job_type is None:
            job_type = "seasonal" if win and r.random() < 0.65 else r.choice(["permanent", "permanent", "part_time"])
        sf = st = None
        if job_type == "seasonal":
            s0, e0 = _window_after(created_d if not open_ else a, win or WINDOWS["hill_station"])
            sf, st = s0.isoformat(), e0.isoformat()
        cat = SKILLS[skills[0]]["category"]
        lo, hi = PAY[cat]
        pay_min = int(r.randint(lo, hi) / 500) * 500 if r.random() < 0.8 else None
        pay_max = pay_min + r.choice([2000, 4000, 6000]) if pay_min else None
        langs = ["Hindi"]
        if r.random() < 0.4:
            langs.append("Garhwali" if DISTRICTS[b["district"]]["division"] == "Garhwal" else "Kumaoni")
        if cat in ("front_office", "adventure", "wellness") and r.random() < 0.6:
            langs.append("English")
        title = SKILLS[skills[0]]["title"]
        stay = b["type"] in catalog.STAY_TYPES or b["type"] == "adventure_operator"
        created = _dt(created_d, 9 + n % 8)
        closed_at = closes = None
        reason = None
        if open_:
            closes = (a + timedelta(days=r.randint(10, 60))).isoformat()
        else:
            closed_at = created + timedelta(days=r.randint(6, 50), hours=r.randint(0, 20))
            closes = closed_at.date().isoformat()
            reason = "filled" if filled else "withdrawn"
        place = dest.get("name") or DISTRICTS[b["district"]]["name"]
        return {
            "id": f"JOB-{n:06d}",
            "owner_user_id": b.get("owner_user_id"),
            "business_id": b["id"],
            "business_name": b["name"],
            "business_type": b["type"],
            "business_reg_no": b["reg_no"],
            "title": title,
            "skills": skills,
            "district": b["district"],
            "destination_id": b.get("destination_id"),
            "job_type": job_type,
            "season_from": sf,
            "season_to": st,
            "pay_min": pay_min,
            "pay_max": pay_max,
            "accommodation": stay and r.random() < 0.7,
            "food": stay and r.random() < 0.7,
            "openings": r.choice([1, 1, 1, 2, 2, 3, 4]),
            "languages": langs,
            "description": f"Synthetic sample job post for the demo. {title} needed at {b['name']} ({place}). "
            "Duties, timings and pay to be discussed with the employer.",
            "closes_on": closes,
            "status": "open" if open_ else "closed",
            "closed_reason": reason,
            "closed_at": closed_at,
            "synthetic": True,
            "created_at": created,
            "updated_at": closed_at or created,
        }

    # ---------------------------------------------------------------- applications / interests
    def application(self, job: dict, prof: dict, status: str, seeker_user_id: str | None = None, note: str | None = None) -> dict:
        self.n_app += 1
        path = {
            "applied": ["applied"],
            "viewed": ["applied", "viewed"],
            "shortlisted": ["applied", "viewed", "shortlisted"],
            "contacted": ["applied", "viewed", "shortlisted", "contacted"],
            "not_selected": ["applied", "viewed", "not_selected"],
        }[status]
        t0 = mongo.aware(job["created_at"]) + timedelta(days=self.r.randint(0, 6), hours=self.r.randint(1, 12))
        t0 = min(t0, mongo.now() - timedelta(hours=len(path) * 6))
        hist = [{"status": s, "at": t0 + timedelta(hours=6 * k)} for k, s in enumerate(path)]
        doc = {
            "id": f"JA-{self.n_app:06d}",
            "job_id": job["id"],
            "business_id": job["business_id"],
            "owner_user_id": job["owner_user_id"],
            "district": job["district"],
            "seeker_user_id": seeker_user_id,
            "candidate_id": prof["code"],
            "note": note,
            "status": status,
            "history": hist,
            "synthetic": True,
            "created_at": hist[0]["at"],
            "updated_at": hist[-1]["at"],
        }
        return doc

    def interest(self, owner: str, b: dict, prof: dict, status: str, job: dict | None, message: str) -> dict:
        self.n_int += 1
        created = mongo.now() - timedelta(days=self.r.randint(1, 10), hours=self.r.randint(0, 20))
        return {
            "id": f"INT-{self.n_int:06d}",
            "owner_user_id": owner,
            "business_id": b["id"],
            "business_name": b["name"],
            "business_type": b["type"],
            "district": b["district"],
            "candidate_id": prof["code"],
            "seeker_user_id": prof.get("user_id"),
            "job_id": job["id"] if job else None,
            "message": message,
            "status": status,
            "synthetic": True,
            "created_at": created,
            "responded_at": None if status == "pending" else created + timedelta(hours=self.r.randint(2, 30)),
        }


def _msg(thread_id: str, role: str, user_id: str, text: str, at: datetime) -> dict:
    return {
        "id": "msg_" + secrets.token_hex(6),
        "thread_id": thread_id,
        "sender_role": role,
        "sender_user_id": user_id,
        "text": text,
        "created_at": at,
    }


def seed_hiring(d, demo_owner: str, demo_seeker: str, anchor: date | None = None) -> dict:
    """Insert the synthetic hiring-board data. Caller guarantees the hiring collections are empty."""
    g = HiringGenerator(anchor)
    r = g.r
    today = g.anchor.isoformat()
    profiles = [g.candidate(i) for i in range(1, N_CANDIDATES + 1)]
    demo_prof = g.demo_profile(demo_seeker, f"C-{N_CANDIDATES + 1:04d}")
    public = [p for p in profiles if p["visibility"] == "public"]

    active = [mongo.clean(b) for b in d.businesses.find({"status": "active"}) if registry.effective_status(b, today) == "active"]
    active.sort(key=lambda b: b["id"])
    own = [b for b in active if b.get("owner_user_id") == demo_owner]
    others = [b for b in active if not b.get("owner_user_id")]
    jobs: list[dict] = []
    n = 0

    # Demo business owner: four open posts.
    home = next((b for b in own if b["type"] == "homestay"), own[0] if own else None)
    hotel = next((b for b in own if b["type"] == "hotel"), home)
    demo_specs = [
        (home, ["cook_pahadi"], "seasonal"),
        (home, ["housekeeping", "laundry"], "seasonal"),
        (hotel, ["front_office", "reservations_sales"], "permanent"),
        (hotel, ["kitchen_helper"], "seasonal"),
    ]
    demo_jobs = []
    for b, sk, jt in demo_specs:
        if not b:
            continue
        n += 1
        j = g.job(n, b, sk, open_=True, job_type=jt)
        demo_jobs.append(j)
        jobs.append(j)

    # Other synthetic businesses: 26 open, 14 closed (10 filled, 4 withdrawn).
    pool = r.sample(others, k=min(N_JOBS_OTHER, len(others)))
    for k, b in enumerate(pool):
        n += 1
        cands = TYPE_SKILLS.get(b["type"], ["housekeeping"])
        sk = [r.choice(cands)]
        same = [s["key"] for s in SKILL_LIST if s["category"] == SKILLS[sk[0]]["category"] and s["key"] != sk[0]]
        if same and r.random() < 0.35:
            sk.append(r.choice(same))
        open_ = k < 26
        jobs.append(g.job(n, b, sk, open_=open_, filled=k < 36 or open_))

    # Applications: open posts get candidates who list one of the required skills.
    apps: list[dict] = []
    statuses = ["applied", "applied", "viewed", "viewed", "shortlisted", "contacted", "not_selected", "not_selected"]
    for j in jobs:
        fit = [p for p in public if set(p["skill_keys"]) & set(j["skills"])]
        if not fit:
            continue
        k = r.randint(3, 6) if j in demo_jobs else r.randint(0, 3)
        for p in r.sample(fit, k=min(k, len(fit))):
            st = r.choice(statuses) if j["status"] == "open" else r.choice(["contacted", "not_selected", "not_selected"])
            apps.append(g.application(j, p, st))

    # Demo seeker: applied to two synthetic posts and to the demo owner's kitchen-helper post (with a short thread).
    taken = {(a["job_id"], a["candidate_id"]) for a in apps}
    kitchen = [
        j
        for j in jobs
        if j["status"] == "open" and j not in demo_jobs and set(j["skills"]) & {"cook_pahadi", "cook_indian", "kitchen_helper"}
    ]
    msgs: list[dict] = []
    for j, st in zip(kitchen[:2], ["applied", "shortlisted"], strict=False):
        if (j["id"], demo_prof["code"]) not in taken:
            apps.append(g.application(j, demo_prof, st, demo_seeker, "Available for the full season."))
    kh = next((j for j in demo_jobs if "kitchen_helper" in j["skills"]), None)
    if kh:
        a = g.application(kh, demo_prof, "viewed", demo_seeker, "I can join from the start of the season.")
        apps.append(a)
        t = mongo.aware(a["created_at"])
        msgs.append(
            _msg(a["id"], "job_seeker", demo_seeker, "Namaste. Is accommodation provided for kitchen staff?", t + timedelta(hours=2))
        )
        msgs.append(
            _msg(
                a["id"],
                "business",
                demo_owner,
                "Yes, shared staff rooms and meals are provided. Can you start in the first week?",
                t + timedelta(hours=20),
            )
        )

    # Demo business owner: interest requests (accepted / pending / declined) and a shortlist.
    ints: list[dict] = []
    shortlist: list[dict] = []
    if home:
        cooks = [p for p in public if "cook_pahadi" in p["skill_keys"] or "cook_indian" in p["skill_keys"]] or public
        picks = r.sample(cooks, k=min(3, len(cooks)))
        cook_job = demo_jobs[0] if demo_jobs else None
        for p, st in zip(picks, ["accepted", "pending", "declined"], strict=False):
            ints.append(g.interest(demo_owner, home, p, st, cook_job, "We are hiring for the yatra season. Would you like to talk?"))
        ints.append(
            g.interest(
                demo_owner, home, demo_prof, "pending", cook_job, "We liked your profile. Would you cook for our homestay this season?"
            )
        )
        for p in picks[:2] + r.sample(public, k=1):
            if p["code"] not in {s["candidate_id"] for s in shortlist}:
                shortlist.append(
                    {"owner_user_id": demo_owner, "candidate_id": p["code"], "created_at": mongo.now() - timedelta(days=r.randint(1, 9))}
                )

    all_profiles = profiles + [demo_prof]
    d.seeker_profiles.insert_many(all_profiles)
    d.job_posts.insert_many(jobs)
    if apps:
        d.job_applications.insert_many(apps)
    if ints:
        d.interest_requests.insert_many(ints)
    if shortlist:
        d.job_shortlist.insert_many(shortlist)
    if msgs:
        d.job_messages.insert_many(msgs)
    for name, v in (("candidate", len(all_profiles)), ("job", n), ("job_application", g.n_app), ("interest", g.n_int)):
        d.counters.update_one({"_id": name}, {"$max": {"seq": v}}, upsert=True)
    return {
        "candidates": len(all_profiles),
        "jobs": len(jobs),
        "jobs_open": sum(1 for j in jobs if j["status"] == "open"),
        "applications": len(apps),
        "interests": len(ints),
        "messages": len(msgs),
    }
