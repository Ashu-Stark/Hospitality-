"""Startup seeding.

* Reference data (districts, destinations, dictionary, rules, helplines, curated festivals) is curated content:
  it is (re)loaded whenever its content hash changes, in every environment.
* Synthetic demo data (businesses, occupancy, workforce, arrivals, grievances, applications, sample advisories and
  events, demo accounts) is inserted once when PORTAL_SEED_DEMO is true and the database has no businesses.
  A `meta` document acts as a lock so two processes starting together do not both seed.
"""

from __future__ import annotations

import hashlib
import json
import logging

from pymongo.errors import DuplicateKeyError

from .. import config, mongo
from . import destinations, dictionary, districts, festivals, rules

log = logging.getLogger("hoi.portal.seed")


def _reference_docs() -> dict[str, list[dict]]:
    from ..services import events as ev
    from ..services.search import normalize

    dests = []
    for d in destinations.DESTINATIONS:
        doc = dict(d)
        doc["search_text"] = normalize(
            d["name"], districts.BY_ID[d["district"]]["name"], d["division"], " ".join(d["tags"]), " ".join(d["route_facts"])
        )
        dests.append(doc)
    terms = [dict(t, search_text=normalize(t["term"], t["hindi"], t["category"], t["definition"])) for t in dictionary.TERMS]
    cards = [
        dict(r, search_text=normalize(r["title"], r["who_needs_it"], r["what_it_covers"], r["where_to_apply"], " ".join(r["tags"])))
        for r in rules.RULES
    ]
    fests = [dict(f, search_text=ev.search_text(f)) for f in festivals.FESTIVALS]
    helplines = [dict(h, order=i) for i, h in enumerate(rules.HELPLINES)]
    return {
        "districts": [dict(d) for d in districts.DISTRICTS],
        "destinations": dests,
        "dictionary": terms,
        "rules": cards,
        "helplines": helplines,
        "events": fests,
    }


def ensure_reference(d) -> bool:
    docs = _reference_docs()
    version = hashlib.sha256(json.dumps(docs, sort_keys=True, default=str).encode()).hexdigest()[:16]
    meta = d.meta.find_one({"_id": "reference"})
    if meta and meta.get("version") == version:
        return False
    for name, items in docs.items():
        col = d[name]
        if name == "events":
            col.delete_many({"curated": True})
        else:
            col.delete_many({})
        col.insert_many([dict(x) for x in items])
    d.meta.update_one({"_id": "reference"}, {"$set": {"version": version, "loaded_at": mongo.now()}}, upsert=True)
    log.info("reference data loaded (version %s)", version)
    return True


def ensure_demo(d) -> dict | None:
    if d.businesses.estimated_document_count() > 0:
        return None
    try:
        d.meta.insert_one({"_id": "demo_seed", "state": "running", "started_at": mongo.now()})
    except DuplicateKeyError:
        log.info("demo seed already done or running elsewhere; skipping")
        return None
    from .generator import seed_demo

    try:
        stats = seed_demo(d)
    except Exception:
        d.meta.delete_one({"_id": "demo_seed"})
        raise
    d.meta.update_one({"_id": "demo_seed"}, {"$set": {"state": "done", "finished_at": mongo.now(), "stats": stats}})
    return stats


def ensure() -> None:
    from ..services import users

    d = mongo.db()
    s = config.settings
    ensure_reference(d)
    # Bulk demo inserts run before index creation: mongomock checks unique indexes in O(n^2) on insert_many.
    # Creating the unique indexes afterwards still fails loudly if the seed produced a duplicate.
    if s.seed_demo:
        ensure_demo(d)
    mongo.ensure_indexes(d)
    users.ensure_admin()
    if s.demo_login:
        users.ensure_demo_users()
