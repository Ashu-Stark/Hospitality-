"""Unified search across registry, destinations, dictionary, rules, events and advisories.

mongomock does not implement `$text`, so every searchable document carries a normalised lowercase `search_text`
field and queries use case-insensitive regexes built from escaped user tokens (all tokens must match). This works
the same on Atlas and mongomock. Queries are capped at MAX_QUERY characters and MAX_TOKENS tokens.
"""

from __future__ import annotations

import re
import unicodedata

from .. import mongo
from ..errors import Invalid

MAX_QUERY, MAX_TOKENS, MIN_QUERY = 80, 6, 2
GROUPS = ("destinations", "businesses", "events", "dictionary", "rules", "advisories")


def normalize(*parts) -> str:
    text = " ".join(str(p) for p in parts if p)
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^\w\s\-/]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(q: str) -> list[str]:
    q = normalize(q[:MAX_QUERY])
    toks = [t for t in re.split(r"[\s\-/]+", q) if t][:MAX_TOKENS]
    return toks


def regex_filter(q: str | None, field: str = "search_text") -> dict:
    """Mongo filter where every token appears in `field` (escaped, case-insensitive). Empty query = no filter."""
    if not q or not q.strip():
        return {}
    toks = tokens(q)
    if not toks:  # only punctuation: match nothing rather than everything
        return {field: {"$in": []}}
    return {"$and": [{field: {"$regex": re.escape(t), "$options": "i"}} for t in toks]}


def _rank(name: str, q: str) -> tuple:
    n, ql = (name or "").lower(), q.lower().strip()
    return (0 if n == ql else 1 if n.startswith(ql) else 2 if ql in n else 3, n)


def search(q: str, limit: int = 8) -> dict:
    from . import advisories, destinations, dictionary, events, registry, rules

    q = (q or "").strip()
    if len(q) < MIN_QUERY:
        raise Invalid(f"Type at least {MIN_QUERY} characters.")
    q = q[:MAX_QUERY]
    if not tokens(q):
        return {"query": q, "total": 0, "counts": dict.fromkeys(GROUPS, 0), "groups": {g: [] for g in GROUPS}}
    f = regex_filter(q)
    d = mongo.db()
    out: dict[str, list] = {}

    dests = [destinations.summary(x) for x in d.destinations.find(f)]
    out["destinations"] = sorted(dests, key=lambda x: _rank(x["name"], q))[:limit]

    biz = list(d.businesses.find(f).limit(200))
    out["businesses"] = sorted((registry.public(b) for b in biz), key=lambda x: _rank(x["name"], q))[:limit]

    evs = [events.public(e) for e in d.events.find(f)]
    out["events"] = sorted(evs, key=lambda x: _rank(x["name"], q))[:limit]

    terms = [dictionary.public(t) for t in d.dictionary.find(f)]
    out["dictionary"] = sorted(terms, key=lambda x: _rank(x["term"], q))[:limit]

    rl = [rules.public(r) for r in d.rules.find(f)]
    out["rules"] = sorted(rl, key=lambda x: _rank(x["title"], q))[:limit]

    adv = [advisories.public(a) for a in d.advisories.find({**f, **advisories.active_filter()})]
    out["advisories"] = adv[:limit]

    counts = {
        "destinations": len(dests),
        "businesses": len(biz),
        "events": len(evs),
        "dictionary": len(terms),
        "rules": len(rl),
        "advisories": len(adv),
    }
    return {"query": q, "total": sum(counts.values()), "counts": counts, "groups": out}
