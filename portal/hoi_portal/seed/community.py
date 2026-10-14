"""SYNTHETIC community data: local experiences hosted by registered local hosts, join requests, staffing agencies and
their pooled-worker block offers. Deterministic (own RNG seed) and inserted once, after the demo and hiring seeds.

Nothing here is real. Experience titles, descriptions, prices, group sizes, durations, seasons and "community share"
notes are SAMPLE text written for the concept. Agency names follow the synthetic "<Word> Sample ..." pattern.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from .. import catalog, mongo
from .destinations import BY_ID_DEST
from .districts import BY_ID as DISTRICTS

RNG_SEED = 20261013
SAMPLE = "SAMPLE (synthetic): "
COMMUNITY_SHARE_NOTE = "Sample figure for the concept, not verified."

# type -> (destinations where the sample lists it, duration hours range, group size range, price per person range INR,
#          months, short description in our own generic words)
_PLAN: dict[str, tuple] = {
    "village_walk": (
        ["munsiyari", "kausani", "chopta", "lansdowne", "dhanaulti", "lohaghat", "pauri", "auli", "kedarnath"],
        (2, 3),
        (2, 10),
        (300, 800),
        [3, 4, 5, 6, 9, 10, 11],
        "Walk through a hill village with a local host: terraced fields, old stone houses, the village temple and daily life. "
        "Go at the host's pace and ask before taking photos of people or homes.",
    ),
    "home_meal": (
        ["kedarnath", "almora", "kausani", "munsiyari", "lansdowne", "dhanaulti", "pauri", "new-tehri-tehri-lake", "rishikesh"],
        (2, 3),
        (2, 8),
        (400, 900),
        list(range(1, 13)),
        "A home-cooked Garhwali or Kumaoni meal with a host family, made from seasonal local produce. Tell the host about "
        "food allergies when you request.",
    ),
    "artisan_workshop": (
        ["munsiyari", "almora", "bageshwar", "pithoragarh", "kausani", "new-tehri-tehri-lake"],
        (2, 4),
        (2, 6),
        (500, 1500),
        [3, 4, 5, 6, 9, 10, 11, 12],
        "Spend a few hours with a local artisan and try a traditional craft yourself, such as bamboo work or wool weaving. "
        "Small items you make are yours to keep.",
    ),
    "farm_stay": (
        ["dhanaulti", "lohaghat", "pauri", "kausani", "lansdowne", "new-tehri-tehri-lake"],
        (6, 8),
        (2, 8),
        (900, 2200),
        [3, 4, 5, 9, 10, 11],
        "A day on a hill farm: help in the fields or orchard in season, cook with the family and learn how the farm year "
        "works. Includes a simple farm lunch.",
    ),
    "nature_walk": (
        ["chopta", "auli", "mussoorie", "lansdowne", "jim-corbett-ramnagar", "nainital", "valley-of-flowers", "dhanaulti"],
        (2, 5),
        (2, 12),
        (400, 1200),
        [3, 4, 5, 6, 9, 10, 11],
        "A guided walk on forest trails with a registered local guide, about trees, flowers and the seasons. Keep to the "
        "trail and carry your waste back.",
    ),
    "birding": (
        ["chopta", "jim-corbett-ramnagar", "nainital", "munsiyari", "kausani", "lansdowne", "almora"],
        (3, 5),
        (2, 6),
        (600, 1800),
        [1, 2, 3, 4, 5, 10, 11, 12],
        "An early-morning birding walk with a local guide. Binoculars can be shared; go quietly and keep a distance from nests.",
    ),
    "folk_music": (
        ["almora", "pauri", "bageshwar", "munsiyari", "new-tehri-tehri-lake", "nainital"],
        (2, 3),
        (4, 20),
        (300, 900),
        [3, 4, 5, 6, 9, 10, 11, 12],
        "An evening of local folk songs and traditional instruments, hosted in a village or homestay courtyard.",
    ),
    "heritage_walk": (
        ["almora", "bageshwar", "haridwar", "rishikesh", "lohaghat", "pithoragarh", "kashipur", "dehradun", "badrinath"],
        (2, 3),
        (2, 15),
        (300, 900),
        list(range(1, 13)),
        "A walk through the old lanes of a temple town with a local guide: temples, markets and stories of the place. "
        "Dress modestly and follow temple rules.",
    ),
}
COUNT_PER_TYPE = 5  # 8 types x 5 = 40 sample experiences
BRING = ["Comfortable walking shoes", "Water bottle", "A warm layer", "Cash for small purchases", "Rain jacket in the monsoon"]
SHARES = [
    "Sample: about 70% of the fee goes to the host family, 10% to a village fund.",
    "Sample: the host keeps the fee; 5% supports a local school.",
    "Sample: fee shared between the guide and the host family.",
    "Sample: 15% goes to a women's self-help group that cooks the meal.",
    "Sample: part of the fee goes to trail upkeep by the village.",
]
WORDS = ["Aster", "Bugyal", "Chir", "Deodar", "Ekra", "Fir", "Ghughuti", "Himal", "Kafal", "Lingura", "Malu", "Ringaal"]

# Staffing agencies: (destination id for the office, districts served, skills pooled, pool size)
_AGENCIES = [
    (
        "rishikesh",
        ["dehradun", "haridwar", "tehri-garhwal", "rudraprayag"],
        ["housekeeping", "fb_service", "kitchen_helper", "front_office", "cook_pahadi"],
        40,
    ),
    ("haridwar", ["haridwar", "dehradun", "pauri-garhwal"], ["housekeeping", "laundry", "security_guard", "fb_service"], 55),
    (
        "dehradun",
        ["dehradun", "tehri-garhwal", "uttarkashi"],
        ["front_office", "reservations_sales", "housekeeping", "driver_taxi", "accountant"],
        35,
    ),
    ("nainital", ["nainital", "almora", "udham-singh-nagar"], ["housekeeping", "fb_service", "cook_indian", "kitchen_helper"], 30),
    ("almora", ["almora", "bageshwar", "pithoragarh", "champawat"], ["homestay_host", "cook_pahadi", "trek_guide", "housekeeping"], 22),
    (
        "jim-corbett-ramnagar",
        ["nainital", "udham-singh-nagar", "pauri-garhwal"],
        ["fb_service", "cook_continental", "driver_tempo", "maintenance"],
        28,
    ),
    ("mussoorie", ["dehradun", "tehri-garhwal"], ["housekeeping", "fb_service", "barista", "baker", "spa_therapist"], 26),
    (
        "pithoragarh",
        ["pithoragarh", "bageshwar", "champawat", "chamoli"],
        ["trek_guide", "cook_pahadi", "homestay_host", "driver_taxi"],
        18,
    ),
]
DEMO_AGENCY_USER = "demo.agency"


def _month_start(d: date, add_months: int) -> date:
    m = d.month - 1 + add_months
    return date(d.year + m // 12, m % 12 + 1, 1)


def _active(b: dict, today: str) -> bool:
    return b.get("status") == "active" and (b.get("valid_until") or "") >= today


def build(d, demo_owner: str | None, agency_owner: str | None, anchor: date | None = None) -> dict[str, list[dict]]:
    """Plan all documents (nothing written). Reads the seeded businesses."""
    from ..services.search import normalize

    anchor = anchor or mongo.today()
    today = anchor.isoformat()
    r = random.Random(RNG_SEED)
    biz = [mongo.clean(b) for b in d.businesses.find({}).sort("id", 1)]
    active = [b for b in biz if _active(b, today)]
    hosts_by_dest: dict[str, list[dict]] = {}
    stays_by_dest: dict[str, list[dict]] = {}
    for b in active:
        if b["type"] in catalog.LOCAL_EXPERIENCE_HOST_TYPES:
            hosts_by_dest.setdefault(b["destination_id"], []).append(b)
        if b["type"] == "homestay":
            stays_by_dest.setdefault(b["destination_id"], []).append(b)
    stays_by_district: dict[str, list[dict]] = {}
    for b in active:
        if b["type"] == "homestay":
            stays_by_district.setdefault(b["district"], []).append(b)

    # ------------------------------------------------------------------ local experiences
    demo_home = next((b for b in active if b.get("owner_user_id") == demo_owner and b["type"] == "homestay"), None) if demo_owner else None
    exps: list[dict] = []
    titles: set[str] = set()

    def make(etype: str, dest_id: str, host: dict) -> None:
        _dests, dur, grp, price, months, desc = _PLAN[etype]
        dest = BY_ID_DEST[dest_id]
        stays = [s for s in stays_by_dest.get(dest_id, []) if s["id"] != host["id"]]
        if not stays:
            stays = [s for s in stays_by_district.get(dest["district"], []) if s["id"] != host["id"]]
        r.shuffle(stays)
        stay_ids = [s["id"] for s in stays[: r.randint(1, 3)]]
        lo = r.randrange(price[0], price[1] + 1, 50)
        hi = lo + r.choice([0, 100, 200, 300])
        gmin = grp[0]
        gmax = r.randint(max(gmin + 1, grp[1] - 4), grp[1])
        hours = r.choice([h / 2 for h in range(dur[0] * 2, dur[1] * 2 + 1)])
        langs = sorted({"Hindi", r.choice(["English", "English", "Hindi"]), "Garhwali" if dest["division"] == "Garhwal" else "Kumaoni"})
        label = catalog.LOCAL_EXPERIENCE_TYPES[etype]
        title = f"{label}, {dest['name']}"
        if title in titles:
            title = f"{label} with {host['name'].split(' Sample ')[0]} hosts, {dest['name']}"
        titles.add(title)
        n = len(exps) + 1
        doc = {
            "id": f"LX-{n:04d}",
            "title": title,
            "type": etype,
            "destination_id": dest_id,
            "district": dest["district"],
            "host_business_id": host["id"],
            "owner_user_id": host.get("owner_user_id"),
            "description": SAMPLE + desc,
            "duration_hours": hours,
            "group_min": gmin,
            "group_max": gmax,
            "price_min": lo,
            "price_max": hi,
            "languages": langs,
            "months": sorted(months),
            "stay_business_ids": stay_ids,
            "community_share": r.choice(SHARES),
            "what_to_bring": r.sample(BRING, 3),
            "status": "listed",
            "synthetic": True,
            "created_at": mongo.now() - timedelta(days=r.randint(5, 200)),
            "updated_at": mongo.now(),
        }
        doc["search_text"] = normalize(title, label, dest["name"], DISTRICTS[dest["district"]]["name"], host["name"])
        exps.append(doc)

    for etype, (dests, *_rest) in _PLAN.items():
        picked = [x for x in dests if hosts_by_dest.get(x)]
        for k in range(min(COUNT_PER_TYPE, len(picked) * 2)):
            dest_id = picked[k % len(picked)]
            hosts = hosts_by_dest[dest_id]
            if etype in ("home_meal", "farm_stay"):
                hosts = [h for h in hosts if h["type"] == "homestay"] or hosts
            make(etype, dest_id, hosts[r.randrange(len(hosts))])
    if demo_home:  # the demo business owner hosts two experiences, so its dashboard has join requests to act on
        for etype in ("home_meal", "village_walk"):
            make(etype, demo_home["destination_id"], demo_home)

    # ------------------------------------------------------------------ join requests for the demo host
    reqs: list[dict] = []
    if demo_home:
        mine = [e for e in exps if e["host_business_id"] == demo_home["id"]]
        for i, (status, days) in enumerate((("pending", 2), ("pending", 1), ("accepted", 6), ("pending", 0))):
            if not mine:
                break
            e = mine[i % len(mine)]
            reqs.append(
                {
                    "id": f"JR-{i + 1:06d}",
                    "experience_id": e["id"],
                    "host_business_id": e["host_business_id"],
                    "owner_user_id": e["owner_user_id"],
                    "name": f"Visitor V-{i + 1:03d} (sample)",
                    "group_size": r.randint(2, 4),
                    "date": (anchor + timedelta(days=7 + 3 * i)).isoformat(),
                    "contact": f"+91-90000-1{i + 1:04d} (synthetic)",
                    "note": SAMPLE + "We are a small family group; one of us is vegetarian.",
                    "status": status,
                    "synthetic": True,
                    "created_at": mongo.now() - timedelta(days=days),
                    "decided_at": mongo.now() - timedelta(days=days - 1) if status != "pending" else None,
                }
            )

    # ------------------------------------------------------------------ staffing agencies + block offers
    agencies: list[dict] = []
    offers: list[dict] = []
    counters: dict[str, int] = {}
    for i, (dest_id, served, skills, pool) in enumerate(_AGENCIES, start=1):
        dest = BY_ID_DEST[dest_id]
        dcode = DISTRICTS[dest["district"]]["code"]
        key = f"reg:STF:{dcode}"
        counters[key] = counters.get(key, 0) + 1
        name = f"{WORDS[(i * 5) % len(WORDS)]} Sample Staffing Agency S{i:02d}, {dest['name']}"
        reg_no = f"UK-STF-{dcode}-{counters[key]:05d}"
        start = anchor - timedelta(days=r.randint(60, 700))
        b = {
            "id": f"biz_s{i:03d}",
            "reg_no": reg_no,
            "name": name,
            "name_lc": name.lower(),
            "type": "staffing_agency",
            "district": dest["district"],
            "destination_id": dest_id,
            "status": "active",
            "verified": i != 6,
            "rating": round(r.uniform(3.6, 4.8), 1),
            "capacity": pool,
            "beds": None,
            "languages": ["Hindi", "English", "Garhwali" if dest["division"] == "Garhwal" else "Kumaoni"],
            "registered_on": start.isoformat(),
            "valid_until": (anchor + timedelta(days=r.randint(90, 330))).isoformat(),
            "hoi_connected": False,
            "owner_user_id": agency_owner if i == 1 else None,
            "agency_skills": skills,
            "districts_served": served,
            "synthetic": True,
            "created_at": mongo.now(),
        }
        b["search_text"] = normalize(
            name, reg_no, "Staffing agency", DISTRICTS[b["district"]]["name"], dest["name"], " ".join(b["languages"])
        )
        agencies.append(b)
        for j in range(2 if i > 1 else 3):
            skill = skills[j % len(skills)]
            frm = _month_start(anchor, 1 + j + r.randint(0, 2))
            to = _month_start(frm, r.choice([2, 3])) - timedelta(days=1)
            offers.append(
                {
                    "id": f"OFR-{len(offers) + 1:05d}",
                    "agency_business_id": b["id"],
                    "owner_user_id": b["owner_user_id"],
                    "skill": skill,
                    "district": dest["district"],
                    "destination_id": dest_id,
                    "workers": r.choice([4, 6, 8, 10, 12, 15]),
                    "available_from": frm.isoformat(),
                    "available_to": to.isoformat(),
                    "note": SAMPLE + "Pooled local workers, briefed on hygiene and guest safety; uniforms provided by the agency.",
                    "status": "open",
                    "synthetic": True,
                    "created_at": mongo.now() - timedelta(days=r.randint(1, 40)),
                    "updated_at": mongo.now(),
                }
            )
    return {"local_experiences": exps, "experience_requests": reqs, "agencies": agencies, "staffing_offers": offers, "counters": counters}


def seed_community(d, demo_owner: str | None, agency_owner: str | None, anchor: date | None = None) -> dict:
    plan = build(d, demo_owner, agency_owner, anchor)
    if plan["agencies"]:
        d.businesses.insert_many(plan["agencies"], ordered=False)
    for name in ("local_experiences", "experience_requests", "staffing_offers"):
        if plan[name]:
            d[name].insert_many(plan[name], ordered=False)
    for key, v in plan["counters"].items():
        d.counters.update_one({"_id": key}, {"$max": {"seq": v}}, upsert=True)
    d.counters.update_one({"_id": "local_experience"}, {"$max": {"seq": len(plan["local_experiences"])}}, upsert=True)
    d.counters.update_one({"_id": "experience_request"}, {"$max": {"seq": len(plan["experience_requests"])}}, upsert=True)
    d.counters.update_one({"_id": "staffing_offer"}, {"$max": {"seq": len(plan["staffing_offers"])}}, upsert=True)
    # One sample HOI staffing request from the demo hotel, so agencies have something to respond to in the demo.
    hotel = d.businesses.find_one({"owner_user_id": demo_owner, "type": "hotel"}) if demo_owner else None
    if hotel:
        from ..services import staffing

        start = (anchor or mongo.today()) + timedelta(days=6)
        r = staffing.ingest_request(
            mongo.clean(hotel),
            "seed",
            {
                "skill": "housekeeping",
                "district": hotel["district"],
                "from": start.isoformat(),
                "to": (start + timedelta(days=13)).isoformat(),
                "openings": 4,
                "shift_note": "Morning shifts 7:00-15:00",
                "source": "hoi_roster_shortage",
                "source_id": "SAMPLE-roster-week-housekeeping",
            },
        )
        d.job_posts.update_one({"id": r["job_id"]}, {"$set": {"synthetic": True}})
    return {k: len(v) for k, v in plan.items() if isinstance(v, list)}
