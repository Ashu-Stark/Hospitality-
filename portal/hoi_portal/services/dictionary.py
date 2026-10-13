"""Tourism & hospitality dictionary: A-Z letter index, category filter, search."""

from __future__ import annotations

from .. import mongo
from ..errors import Invalid, NotFound
from ..seed.dictionary import CATEGORIES
from . import search

FIELDS = ("id", "term", "hindi", "category", "definition", "example", "related", "related_terms", "letter")


def public(t: dict) -> dict:
    return {k: t.get(k) for k in FIELDS}


def list_terms(letter: str | None = None, category: str | None = None, q: str | None = None) -> dict:
    f: dict = {}
    if letter:
        letter = letter.strip().upper()[:1]
        if not letter.isalpha():
            raise Invalid("Letter must be A-Z.")
        f["letter"] = letter
    if category:
        if category not in CATEGORIES:
            raise Invalid("Unknown category.")
        f["category"] = category
    f.update(search.regex_filter(q))
    col = mongo.db().dictionary
    items = [public(t) for t in col.find(f).sort("term", 1)]
    return {
        "items": items,
        "total": len(items),
        "letters": sorted(set(col.distinct("letter"))),
        "categories": CATEGORIES,
        "note": "Plain-language explanations for orientation; not legal definitions. Hindi terms to be reviewed by native speakers.",
    }


def get(term_id: str) -> dict:
    t = mongo.db().dictionary.find_one({"id": term_id})
    if not t:
        raise NotFound("Term not found.")
    out = public(t)
    rel = mongo.db().dictionary.find({"id": {"$in": t.get("related", [])}})
    out["related_items"] = [{"id": r["id"], "term": r["term"]} for r in rel]
    return out
