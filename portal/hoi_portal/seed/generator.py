"""Deterministic SYNTHETIC demo data (fixed RNG seed). Nothing here is real.

Storage layout for occupancy (documented in README):
  * `occupancy`     one document per (business_id, month "YYYY-MM") with day-indexed arrays
                    `avail[]`, `occ[]` (rooms available / occupied, null = no report) and `src[]`
                    ("s" seeded, "m" monthly submission, "i" HOI ingest).
  * `occupancy_agg` one document per (destination_id, stay_type, month) with day-indexed sums `avail[]`,
                    `occ[]` (0 = nothing reported). Crowd index and occupancy analytics read only this.
History covers the 730 days before the seed date (the anchor), so "last 30 days" always has data in a demo.
Given the same anchor date the output is identical.
"""

from __future__ import annotations

import calendar
import logging
import random
from collections import defaultdict
from datetime import date, timedelta

from .. import catalog, mongo, security
from .destinations import DESTINATIONS
from .districts import BY_ID as DISTRICTS
from .districts import DISTRICTS as DISTRICT_LIST
from .festivals import FESTIVALS

log = logging.getLogger("hoi.portal.seed")
RNG_SEED = 20260413
HISTORY_DAYS = 730

# Synthetic monthly occupancy patterns (Jan..Dec, 0-1). ASSUMED shapes loosely following the curated seasonality
# hints (Char Dham closed in winter, monsoon dip, winter snow, Corbett monsoon closure). Not data.
PROFILES = {
    "char_dham": [0.04, 0.04, 0.05, 0.3, 0.86, 0.88, 0.5, 0.45, 0.7, 0.82, 0.3, 0.04],
    "vof": [0.08, 0.08, 0.1, 0.15, 0.3, 0.6, 0.7, 0.75, 0.6, 0.35, 0.1, 0.08],
    "hill_station": [0.55, 0.45, 0.5, 0.6, 0.85, 0.9, 0.5, 0.45, 0.55, 0.7, 0.6, 0.86],
    "snow": [0.8, 0.75, 0.55, 0.55, 0.7, 0.75, 0.35, 0.3, 0.45, 0.6, 0.5, 0.8],
    "spiritual": [0.55, 0.6, 0.8, 0.7, 0.8, 0.85, 0.8, 0.75, 0.6, 0.7, 0.65, 0.7],
    "wildlife": [0.75, 0.75, 0.7, 0.65, 0.7, 0.6, 0.25, 0.2, 0.3, 0.7, 0.8, 0.85],
    "town": [0.45, 0.45, 0.5, 0.55, 0.6, 0.6, 0.45, 0.45, 0.5, 0.55, 0.5, 0.5],
}
WORDS = [
    "Apricot",
    "Birch",
    "Cedar",
    "Daisy",
    "Elm",
    "Fern",
    "Glacier",
    "Hazel",
    "Iris",
    "Juniper",
    "Kestrel",
    "Lotus",
    "Maple",
    "Neem",
    "Oak",
    "Pine",
    "Quartz",
    "Rhododendron",
    "Spruce",
    "Tulsi",
    "Umber",
    "Valley",
    "Willow",
    "Yak",
    "Zinnia",
]
TYPE_WEIGHTS = {
    "hotel": 30,
    "homestay": 30,
    "guide": 8,
    "travel_agent": 7,
    "tour_operator": 7,
    "transport": 8,
    "adventure_operator": 5,
    "restaurant": 5,
}
CAPACITY = {
    "hotel": (12, 60),
    "homestay": (2, 6),
    "guide": (4, 15),
    "travel_agent": (2, 12),
    "tour_operator": (10, 40),
    "transport": (1, 15),
    "adventure_operator": (10, 60),
    "restaurant": (20, 120),
}
YEAR_WEIGHTS = {2019: 6, 2020: 6, 2021: 7, 2022: 9, 2023: 11, 2024: 13, 2025: 15, 2026: 12}
ARRIVAL_BASE = {  # synthetic base domestic arrivals for 2019, in thousands
    "haridwar": 3000,
    "dehradun": 2500,
    "nainital": 1800,
    "rudraprayag": 1500,
    "chamoli": 1200,
    "uttarkashi": 1200,
    "tehri-garhwal": 800,
    "pauri-garhwal": 600,
    "almora": 600,
    "udham-singh-nagar": 500,
    "pithoragarh": 400,
    "bageshwar": 300,
    "champawat": 200,
}
IMPACT_BOOST = {"high": 0.06, "medium": 0.03, "low": 0.0}


def _anniversary_after(start: date, anchor: date) -> date:
    y = anchor.year
    while True:
        try:
            d = start.replace(year=y)
        except ValueError:  # 29 Feb
            d = date(y, 3, 1)
        if d >= anchor:
            return d
        y += 1


def _search_text(*parts) -> str:
    from ..services.search import normalize

    return normalize(*parts)


class Generator:
    def __init__(self, anchor: date | None = None):
        self.anchor = anchor or mongo.today()
        self.rng = random.Random(RNG_SEED)
        self.counters: dict[str, int] = defaultdict(int)

    # ---------------------------------------------------------------- helpers
    def reg_no(self, btype: str, district: str) -> str:
        code, dcode = catalog.BUSINESS_TYPES[btype][1], DISTRICTS[district]["code"]
        key = f"reg:{code}:{dcode}"
        self.counters[key] += 1
        return f"UK-{code}-{dcode}-{self.counters[key]:05d}"

    def rand_date(self, start: date, end: date) -> date:
        return start + timedelta(days=self.rng.randrange(max(1, (end - start).days)))

    # ---------------------------------------------------------------- businesses
    def businesses(self, demo_owner: str) -> list[dict]:
        r, out, n = self.rng, [], 0
        types, weights = list(TYPE_WEIGHTS), list(TYPE_WEIGHTS.values())
        years, yweights = list(YEAR_WEIGHTS), list(YEAR_WEIGHTS.values())
        for dest in DESTINATIONS:
            for _ in range(dest["seed_weight"]):
                n += 1
                btype = r.choices(types, weights)[0]
                label = catalog.BUSINESS_TYPES[btype][0]
                name = f"{WORDS[r.randrange(len(WORDS))]} Sample {label} {n:03d}, {dest['name']}"
                lo, hi = CAPACITY[btype]
                cap = r.randint(lo, hi)
                year = r.choices(years, yweights)[0]
                start = date(year, 1, 1)
                end = min(date(year, 12, 31), self.anchor - timedelta(days=20))
                registered = self.rand_date(start, end)
                roll = r.random()
                status = "active" if roll < 0.85 else "expired" if roll < 0.95 else "suspended"
                valid_until = _anniversary_after(registered, self.anchor)
                if status == "expired":
                    valid_until = self.anchor - timedelta(days=r.randint(5, 150))
                    valid_until = max(valid_until, registered + timedelta(days=30))
                langs = ["Hindi", "English"]
                if r.random() < 0.5:
                    langs.append("Garhwali" if dest["division"] == "Garhwal" else "Kumaoni")
                if r.random() < 0.1:
                    langs.append(r.choice(["Punjabi", "Bengali", "Nepali"]))
                b = {
                    "id": f"biz_{n:04d}",
                    "reg_no": self.reg_no(btype, dest["district"]),
                    "name": name,
                    "name_lc": name.lower(),
                    "type": btype,
                    "district": dest["district"],
                    "destination_id": dest["id"],
                    "status": status,
                    "verified": status == "active" and r.random() < 0.85,
                    "rating": round(r.uniform(3.2, 4.9), 1),
                    "capacity": cap,
                    "beds": cap * r.choice([2, 2, 3]) if btype in catalog.STAY_TYPES else None,
                    "languages": langs,
                    "registered_on": registered.isoformat(),
                    "valid_until": valid_until.isoformat(),
                    "hoi_connected": btype in catalog.STAY_TYPES and r.random() < 0.4,
                    "owner_user_id": None,
                    "synthetic": True,
                    "created_at": mongo.now(),
                }
                out.append(b)
        # Demo business owner: a Kedarnath homestay and a hotel in Rudraprayag (one due for renewal soon).
        rud = [b for b in out if b["district"] == "rudraprayag"]
        home = next(b for b in rud if b["type"] == "homestay")
        hotel = next(b for b in rud if b["type"] == "hotel")
        for b, days in ((home, 200), (hotel, 20)):
            b.update(owner_user_id=demo_owner, status="active", verified=True, valid_until=(self.anchor + timedelta(days=days)).isoformat())
        hotel["hoi_connected"] = True
        for b in out:
            b["search_text"] = _search_text(
                b["name"],
                b["reg_no"],
                catalog.BUSINESS_TYPES[b["type"]][0],
                DISTRICTS[b["district"]]["name"],
                next(d["name"] for d in DESTINATIONS if d["id"] == b["destination_id"]),
                " ".join(b["languages"]),
            )
        return out

    # ---------------------------------------------------------------- occupancy
    def occupancy(self, businesses: list[dict]) -> tuple[list[dict], list[dict]]:
        r = self.rng
        dest_by_id = {d["id"]: d for d in DESTINATIONS}
        boosts: dict[tuple[str, int], float] = {}
        for d in DESTINATIONS:
            for m in range(1, 13):
                vals = [
                    IMPACT_BOOST[f["crowd_impact"]]
                    for f in FESTIVALS
                    if m in f["months"] and (d["id"] in f["destination_ids"] or d["district"] in f["districts"])
                ]
                boosts[(d["id"], m)] = max(vals, default=0.0)
        first = self.anchor - timedelta(days=HISTORY_DAYS)
        last = self.anchor - timedelta(days=1)
        per_biz: dict[tuple[str, str], dict] = {}
        agg: dict[tuple[str, str, str], dict] = {}
        for b in businesses:
            if b["type"] not in catalog.STAY_TYPES:
                continue
            dest = dest_by_id[b["destination_id"]]
            prof = PROFILES[dest["profile"]]
            quality = r.gauss(0, 0.06)
            start = max(first, date.fromisoformat(b["registered_on"]))
            stop = last if b["status"] != "expired" else min(last, date.fromisoformat(b["valid_until"]))
            day = start
            while day <= stop:
                base = prof[day.month - 1]
                rate = base + boosts[(dest["id"], day.month)] + quality + r.gauss(0, 0.05)
                if day.weekday() >= 5:
                    rate += 0.08
                if day.year > first.year:
                    rate += 0.02
                rate = min(1.0, max(0.0, rate))
                avail = b["capacity"] - (1 if b["capacity"] > 8 and r.random() < 0.05 else 0)
                occ = min(avail, round(avail * rate))
                month = day.strftime("%Y-%m")
                ndays = calendar.monthrange(day.year, day.month)[1]
                key = (b["id"], month)
                doc = per_biz.get(key)
                if doc is None:
                    doc = per_biz[key] = {
                        "business_id": b["id"],
                        "month": month,
                        "destination_id": b["destination_id"],
                        "district": b["district"],
                        "stay_type": b["type"],
                        "avail": [None] * ndays,
                        "occ": [None] * ndays,
                        "src": [None] * ndays,
                        "synthetic": True,
                    }
                i = day.day - 1
                doc["avail"][i], doc["occ"][i], doc["src"][i] = avail, occ, "s"
                akey = (b["destination_id"], b["type"], month)
                a = agg.get(akey)
                if a is None:
                    a = agg[akey] = {
                        "destination_id": b["destination_id"],
                        "district": b["district"],
                        "stay_type": b["type"],
                        "month": month,
                        "avail": [0] * ndays,
                        "occ": [0] * ndays,
                    }
                a["avail"][i] += avail
                a["occ"][i] += occ
                day += timedelta(days=1)
        return list(per_biz.values()), list(agg.values())

    # ---------------------------------------------------------------- workforce (HOI-connected stays only)
    def workforce(self, businesses: list[dict]) -> list[dict]:
        r, out = self.rng, []
        months = []
        y, m = self.anchor.year, self.anchor.month
        for _ in range(12):
            y, m = (y - 1, 12) if m == 1 else (y, m - 1)
            months.append(f"{y:04d}-{m:02d}")
        shares = {"housekeeping": 0.35, "front_office": 0.15, "food_beverage": 0.25, "maintenance": 0.1}
        for b in businesses:
            if not b["hoi_connected"]:
                continue
            base = max(2, round(b["capacity"] * 0.7))
            for month in months:
                staff = max(2, base + r.randint(-2, 2))
                roles = {k: int(staff * v) for k, v in shares.items()}
                roles["other"] = staff - sum(roles.values())
                out.append(
                    {
                        "business_id": b["id"],
                        "month": month,
                        "district": b["district"],
                        "type": b["type"],
                        "destination_id": b["destination_id"],
                        "staff_count": staff,
                        "roles": roles,
                        "flagged": sum(1 for _ in range(staff) if r.random() < 0.08),
                        "separations": sum(1 for _ in range(staff) if r.random() < 0.03),
                        "source": "seed",
                        "synthetic": True,
                    }
                )
        return out

    # ---------------------------------------------------------------- arrivals 2019-2026
    def arrivals(self) -> list[dict]:
        r, out = self.rng, []
        for d in DISTRICT_LIST:
            dom = ARRIVAL_BASE[d["id"]] * 1000
            for year in range(2019, 2027):
                if year > 2019:
                    dom *= r.uniform(1.03, 1.12)
                foreign = dom * r.uniform(0.005, 0.03)
                partial = year == self.anchor.year
                months = (self.anchor.month - 1) if partial else 12
                factor = months / 12 if partial else 1
                out.append(
                    {
                        "district": d["id"],
                        "year": year,
                        "domestic": int(dom * factor),
                        "foreign": int(foreign * factor),
                        "partial_year": partial,
                        "months_covered": months,
                        "synthetic": True,
                    }
                )
        return out

    # ---------------------------------------------------------------- grievances
    def grievances(self, businesses: list[dict]) -> tuple[list[dict], int]:
        r, out = self.rng, []
        cats = list(catalog.GRIEVANCE_CATEGORIES)
        districts = [d["id"] for d in DISTRICT_LIST]
        weights = [6 if d == "rudraprayag" else 3 if d in ("haridwar", "dehradun", "nainital", "chamoli") else 1 for d in districts]
        now = mongo.now()
        for k in range(1, 41):
            district = r.choices(districts, weights)[0]
            cat = r.choice(cats)
            created = now - timedelta(days=r.randint(0, 120), hours=r.randint(0, 23))
            age = (now - created).days
            if age > 30:
                status = r.choice(["resolved", "resolved", "closed", "closed", "in_progress"])
            elif age > 7:
                status = r.choice(["resolved", "in_progress", "assigned", "received"])
            else:
                status = r.choice(["received", "received", "assigned", "in_progress"])
            biz = [b for b in businesses if b["district"] == district]
            linked = r.choice(biz) if biz and r.random() < 0.5 else None
            ticket = f"UTHP-G-{k:06d}"
            code = f"{r.randrange(1_000_000):06d}"
            history = [{"status": "received", "at": created, "note": "Grievance received.", "public": True, "by": "system"}]
            t = created
            resolved_at = None
            for st in ("assigned", "in_progress", "resolved", "closed"):
                if catalog.GRIEVANCE_STATUSES.index(st) > catalog.GRIEVANCE_STATUSES.index(status):
                    break
                t = t + timedelta(days=r.uniform(0.3, 5))
                t = min(t, now)
                note = {
                    "assigned": "Assigned to the district tourism office.",
                    "in_progress": "The office is looking into this (sample note).",
                    "resolved": "Resolved after contacting the business (sample note).",
                    "closed": "Closed.",
                }[st]
                history.append({"status": st, "at": t, "note": note, "public": True, "by": "sample.officer"})
                if st == "resolved":
                    resolved_at = t
            if status == "closed" and resolved_at is None:
                resolved_at = t
            out.append(
                {
                    "ticket_id": ticket,
                    "code_hash": security.tracking_hash(ticket, code),
                    "category": cat,
                    "district": district,
                    "business_reg_no": linked["reg_no"] if linked else None,
                    "business_id": linked["id"] if linked else None,
                    "description": f"Sample grievance about {catalog.GRIEVANCE_CATEGORIES[cat].lower()} (synthetic text for the prototype).",
                    "contact": None,
                    "status": status,
                    "assigned_to": "sample.officer" if status != "received" else None,
                    "created_at": created,
                    "updated_at": t,
                    "sla_due_at": created + timedelta(days=catalog.GRIEVANCE_SLA_DAYS),
                    "resolved_at": resolved_at,
                    "history": history,
                    "synthetic": True,
                }
            )
        return out, 40

    # ---------------------------------------------------------------- applications
    def applications(self, businesses: list[dict], demo_owner: str, applicants: list[str]) -> list[dict]:
        r, out, k = self.rng, [], 0
        now = mongo.now()
        districts = [d["id"] for d in DISTRICT_LIST]
        dests_by_district = defaultdict(list)
        for d in DESTINATIONS:
            dests_by_district[d["district"]].append(d)

        def new_app(status: str, district: str, owner: str, btype: str | None = None, changes: str | None = None) -> dict:
            nonlocal k
            k += 1
            btype = btype or r.choices(list(TYPE_WEIGHTS), list(TYPE_WEIGHTS.values()))[0]
            dest = r.choice(dests_by_district[district])
            lo, hi = CAPACITY[btype]
            req = catalog.REQUIRED_DOCS[btype]
            docs = {key: key in req for key in catalog.CHECKLIST}
            if status == "changes_requested":
                docs[req[-1]] = False
            submitted = now - timedelta(days=r.randint(1, 40))
            hist = [{"at": submitted, "by": owner, "action": "submitted", "reason": None}]
            app = {
                "id": f"APP-{k:06d}",
                "kind": "new",
                "status": status,
                "owner_user_id": owner,
                "business_id": None,
                "business_name": f"{r.choice(WORDS)} Sample {catalog.BUSINESS_TYPES[btype][0]} A{k:02d}, {dest['name']}",
                "type": btype,
                "district": district,
                "destination_id": dest["id"],
                "capacity": r.randint(lo, hi),
                "beds": None,
                "languages": ["Hindi", "English"],
                "documents": docs,
                "notes": None,
                "reason": None,
                "reg_no": None,
                "submitted_at": submitted,
                "updated_at": submitted,
                "decided_at": None,
                "history": hist,
                "synthetic": True,
            }
            if status in ("changes_requested", "rejected"):
                reason = changes or (
                    "Please tick and keep ready the missing document."
                    if status == "changes_requested"
                    else "Sample rejection: incomplete details."
                )
                t = submitted + timedelta(days=r.randint(1, 3))
                app.update(reason=reason, decided_at=t, updated_at=t)
                hist.append({"at": t, "by": "sample.officer", "action": status, "reason": reason})
            return app

        # Rudraprayag queue for the demo officer, two of them from the demo business owner.
        out.append(new_app("submitted", "rudraprayag", demo_owner, "homestay"))
        out.append(new_app("changes_requested", "rudraprayag", demo_owner, "guide"))
        out.append(new_app("submitted", "rudraprayag", applicants[0]))
        out.append(new_app("submitted", "rudraprayag", applicants[1], "hotel"))
        for i in range(5):
            out.append(new_app("submitted", r.choice(districts), applicants[(i + 2) % len(applicants)]))
        for i in range(2):
            out.append(new_app("changes_requested", r.choice(districts), applicants[i % len(applicants)]))
        for i in range(2):
            out.append(new_app("rejected", r.choice(districts), applicants[(i + 1) % len(applicants)]))
        # Approved: linked to recently registered seeded businesses.
        recent = sorted(
            (b for b in businesses if b["status"] == "active" and b["owner_user_id"] is None), key=lambda b: b["registered_on"]
        )[-4:]
        for i, b in enumerate(recent):
            app = new_app("approved", b["district"], applicants[i % len(applicants)], b["type"])
            reg = date.fromisoformat(b["registered_on"])
            t = mongo.now().replace(year=reg.year, month=reg.month, day=reg.day)
            app.update(
                business_name=b["name"],
                destination_id=b["destination_id"],
                capacity=b["capacity"],
                business_id=b["id"],
                reg_no=b["reg_no"],
                submitted_at=t - timedelta(days=5),
                decided_at=t,
                updated_at=t,
                history=[
                    {"at": t - timedelta(days=5), "by": app["owner_user_id"], "action": "submitted", "reason": None},
                    {"at": t, "by": "sample.officer", "action": "approved", "reason": None},
                ],
            )
            b["owner_user_id"] = app["owner_user_id"]
            out.append(app)
        # Renewals pending review: expired businesses move to `pending` (one in Rudraprayag).
        expired = [b for b in businesses if b["status"] == "expired" and b["owner_user_id"] is None]
        picks = [b for b in expired if b["district"] == "rudraprayag"][:1]
        picks += [b for b in expired if b["district"] != "rudraprayag"][: 3 - len(picks)]
        for i, b in enumerate(picks):
            app = new_app("submitted", b["district"], applicants[(i + 3) % len(applicants)], b["type"])
            app.update(
                kind="renewal",
                business_id=b["id"],
                business_name=b["name"],
                destination_id=b["destination_id"],
                capacity=b["capacity"],
                reg_no=b["reg_no"],
            )
            b["status"] = "pending"
            b["owner_user_id"] = app["owner_user_id"]
            out.append(app)
        return out

    # ---------------------------------------------------------------- advisories and sample events
    def advisories(self) -> list[dict]:
        now = mongo.now()
        raw = [
            (
                "rudraprayag",
                "kedarnath",
                "road",
                "caution",
                "Gaurikund approach",
                "SAMPLE: slow traffic near Gaurikund",
                "Illustrative sample advisory for the prototype; not real road status.",
                6,
            ),
            (
                "chamoli",
                "badrinath",
                "road",
                "caution",
                "Rishikesh-Badrinath corridor (NH-7)",
                "SAMPLE: caution on the NH-7 corridor",
                "Illustrative sample: debris clearance after rain. Not real road status.",
                4,
            ),
            (
                "uttarkashi",
                "gangotri",
                "road",
                "open",
                "Rishikesh-Gangotri route (NH-34)",
                "SAMPLE: NH-34 route open",
                "Illustrative sample advisory; not real road status.",
                5,
            ),
            (
                "uttarkashi",
                "yamunotri",
                "road",
                "closed",
                "Janki Chatti approach",
                "SAMPLE: Janki Chatti approach closed for repairs",
                "Illustrative sample advisory; not real road status.",
                2,
            ),
            (
                "dehradun",
                "mussoorie",
                "general",
                None,
                None,
                "SAMPLE: weekend crowding expected",
                "Illustrative sample: plan arrival early on weekends.",
                10,
            ),
            (
                "pithoragarh",
                "munsiyari",
                "weather",
                None,
                None,
                "SAMPLE: snow possible at higher places",
                "Illustrative sample weather advisory.",
                7,
            ),
            (
                "nainital",
                "jim-corbett-ramnagar",
                "general",
                None,
                None,
                "SAMPLE: check zone dates before booking",
                "Illustrative sample: Corbett zone dates change; verify before booking.",
                14,
            ),
            (
                "haridwar",
                "haridwar",
                "general",
                None,
                None,
                "SAMPLE: crowd management on festival days",
                "Illustrative sample advisory.",
                9,
            ),
            (
                "rudraprayag",
                "chopta",
                "road",
                "caution",
                None,
                "SAMPLE: road caution after rain (expired)",
                "Illustrative sample that has already expired.",
                -2,
            ),
        ]
        out = []
        for i, (district, dest, kind, status, segment, title, reason, days) in enumerate(raw, 1):
            doc = {
                "id": f"adv_sample{i:02d}",
                "district": district,
                "destination_id": dest,
                "kind": kind,
                "status": status,
                "segment": segment,
                "title": title,
                "reason": reason,
                "posted_at": now - timedelta(days=1, hours=i),
                "expires_at": now + timedelta(days=days),
                "posted_by": "seed",
                "posted_by_role": "district_officer",
                "sample": True,
            }
            dname = next(d["name"] for d in DESTINATIONS if d["id"] == dest)
            doc["search_text"] = _search_text(title, segment, reason, kind, DISTRICTS[district]["name"], dname)
            out.append(doc)
        return out

    def sample_events(self) -> list[dict]:
        out = []
        for i, (district, dests, name, offset, length, impact) in enumerate(
            [
                ("rudraprayag", ["chopta"], "SAMPLE: district tourism awareness camp", 5, 1, "low"),
                ("nainital", ["nainital"], "SAMPLE: lake-side cultural evening", 9, 2, "medium"),
            ],
            1,
        ):
            start = self.anchor + timedelta(days=offset)
            end = start + timedelta(days=length)
            doc = {
                "id": f"evt_sample{i:02d}",
                "name": name,
                "kind": "event",
                "months": sorted({start.month, end.month}),
                "window": f"{start.isoformat()} to {end.isoformat()}",
                "districts": [district],
                "destination_ids": dests,
                "crowd_impact": impact,
                "description": "Illustrative sample event for the prototype.",
                "date_note": "Sample event; not a real announcement.",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "curated": False,
                "sample": True,
                "posted_by": "seed",
                "created_at": mongo.now(),
                "updated_at": mongo.now(),
            }
            doc["search_text"] = _search_text(name, doc["description"], DISTRICTS[district]["name"], *dests)
            out.append(doc)
        return out


def _insert(col, docs: list[dict], batch: int = 1000) -> None:
    for i in range(0, len(docs), batch):
        col.insert_many(docs[i : i + batch], ordered=False)


def seed_demo(d, anchor: date | None = None) -> dict:
    """Insert all synthetic demo data. Caller guarantees the database is empty (see seed.ensure)."""
    from ..services import users

    users.ensure_demo_users()
    demo_owner = users.by_username("demo.business")["id"]
    applicants = []
    for i in range(1, 6):
        name = f"sample.applicant.{i:02d}"
        u = users.by_username(name) or users.create(name, None, "business", label=f"Sample applicant {i:02d} (synthetic)")
        applicants.append(u["id"])

    g = Generator(anchor)
    businesses = g.businesses(demo_owner)
    applications = g.applications(businesses, demo_owner, applicants)
    occupancy, agg = g.occupancy(businesses)
    workforce = g.workforce(businesses)
    arrivals = g.arrivals()
    grievances, n_griev = g.grievances(businesses)

    _insert(d.businesses, businesses)
    _insert(d.applications, applications)
    _insert(d.occupancy, occupancy)
    _insert(d.occupancy_agg, agg)
    _insert(d.workforce, workforce)
    _insert(d.arrivals, arrivals)
    _insert(d.grievances, grievances)
    _insert(d.advisories, g.advisories())
    _insert(d.events, g.sample_events())
    counters = [{"_id": k, "seq": v} for k, v in g.counters.items()]
    counters += [{"_id": "application", "seq": len(applications)}, {"_id": "grievance", "seq": n_griev}]
    for c in counters:
        d.counters.update_one({"_id": c["_id"]}, {"$max": {"seq": c["seq"]}}, upsert=True)
    stats = {
        "businesses": len(businesses),
        "applications": len(applications),
        "occupancy_docs": len(occupancy),
        "occupancy_agg_docs": len(agg),
        "workforce_docs": len(workforce),
        "grievances": len(grievances),
        "anchor": g.anchor.isoformat(),
    }
    log.info("seeded synthetic demo data: %s", stats)
    return stats
