"""Rules, licences & schemes explainer cards and helplines (orientation only, verify with the issuing authority)."""

from __future__ import annotations

from .. import catalog, mongo
from ..errors import Invalid, NotFound
from . import search

FIELDS = ("id", "title", "who_needs_it", "what_it_covers", "typical_documents", "where_to_apply", "business_types", "tags", "verify_note")
HELPLINE_FIELDS = ("id", "name", "number", "scope", "note")


def public(r: dict) -> dict:
    return {k: r.get(k) for k in FIELDS}


def list_rules(business_type: str | None = None, q: str | None = None) -> dict:
    f: dict = {}
    if business_type:
        if business_type not in catalog.BUSINESS_TYPES:
            raise Invalid("Unknown business type.")
        f["business_types"] = business_type
    f.update(search.regex_filter(q))
    items = [public(r) for r in mongo.db().rules.find(f).sort("title", 1)]
    return {
        "items": items,
        "total": len(items),
        "note": "Summary for orientation, verify with the issuing authority. No fees, thresholds or section numbers are given here.",
    }


def get(rule_id: str) -> dict:
    r = mongo.db().rules.find_one({"id": rule_id})
    if not r:
        raise NotFound("Card not found.")
    return public(r)


def helplines() -> dict:
    items = [{k: h.get(k) for k in HELPLINE_FIELDS} for h in mongo.db().helplines.find({}).sort("order", 1)]
    return {"items": items, "note": "Verify numbers locally. Blank numbers are placeholders to be filled by the department."}
