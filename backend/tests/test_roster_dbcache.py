"""MongoDB roster cache (hoi_ops.roster_cache) on mongomock, fictional Himsagar hotel."""

from __future__ import annotations

import time
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.config import load_backend_config, make_settings
from backend.main import create_app
from backend.mongo import get_database
from backend.roster import dbcache, service

WEEK = date(2029, 12, 24)


@pytest.fixture()
def hs() -> TestClient:
    settings = make_settings(
        f"hoi_ops_test_{uuid.uuid4().hex[:12]}",
        mock=False,
        mongodb_uri="mongomock://",
        hotel="himsagar",
    )
    with TestClient(create_app(settings)) as c:
        c.post("/demo/reset")
        yield c
    get_database(settings).client.drop_database(settings.database_name)


def no_solver(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
    raise AssertionError("the solver must not run on a cache hit")


def test_miss_solves_and_stores_then_hit_skips_the_solver(hs, monkeypatch):
    db = hs.app.state.db
    assert db[dbcache.ROSTER_CACHE].count_documents({}) == 0
    first = hs.post("/roster/generate", json={"deterministic": True}).json()
    assert first["hard_violations"] == [] and first["method"] in ("cached", "cp_sat")
    doc = db[dbcache.ROSTER_CACHE].find_one({}, {"_id": 0})
    assert (
        doc["week_start"] == str(WEEK) and doc["hotel"] == "himsagar" and doc["protected_ids"] == []
    )
    assert doc["quality"]["coverage_pct"] > 90 and doc["solved_on"] in ("local", "render")
    monkeypatch.setattr(service, "solve", no_solver)
    monkeypatch.setattr(service, "make_problem", no_solver)
    t = time.perf_counter()
    hit = hs.post("/roster/generate", json={"week_start": str(WEEK)})
    assert time.perf_counter() - t < 2 and hit.status_code == 200
    hit = hit.json()
    assert hit["method"] == "cached_db" and hit["hard_violations"] == []
    assert hit["assignments"] == first["assignments"] and hit["coverage"] == first["coverage"]
    assert hs.get(f"/roster/{hit['id']}").json()["method"] == "cached_db"


def test_rosters_with_violations_or_infeasible_are_never_cached(hs):
    db, cfg = hs.app.state.db, hs.app.state.settings.config.roster
    base = {
        "status": "optimal",
        "method": "cp_sat",
        "assignments": [{"employee_id": "HS02"}],
        "coverage": [],
        "objective": 1.0,
    }
    assert not dbcache.put(db, cfg, WEEK, [], {**base, "hard_violations": ["HS02: 2 shifts"]}, True)
    assert not dbcache.put(
        db, cfg, WEEK, [], {**base, "status": "infeasible", "hard_violations": []}, True
    )
    assert not dbcache.put(
        db, cfg, WEEK, [], {**base, "assignments": [], "hard_violations": []}, True
    )
    assert db[dbcache.ROSTER_CACHE].count_documents({}) == 0
    # a worse roster never replaces a better one
    assert dbcache.put(db, cfg, WEEK, [], {**base, "hard_violations": [], "objective": 10.0}, True)
    assert not dbcache.put(
        db, cfg, WEEK, [], {**base, "status": "feasible", "hard_violations": []}, True
    )
    assert not dbcache.put(
        db, cfg, WEEK, [], {**base, "hard_violations": [], "objective": 11.0}, True
    )
    assert dbcache.get(db, cfg, WEEK, [])["objective"] == 10.0


def test_reset_keeps_the_cache_and_the_loop_reads_it(hs, monkeypatch):
    first = hs.post("/loop/run").json()  # fills the cache with baseline + protected rosters
    db = hs.app.state.db
    assert db[dbcache.ROSTER_CACHE].count_documents({}) == 2
    assert hs.post("/demo/reset").status_code == 200
    assert db[dbcache.ROSTER_CACHE].count_documents({}) == 2  # precomputed data survives a reset
    monkeypatch.setattr(service, "solve", no_solver)
    again = hs.post("/loop/run").json()
    assert {t["method"] for t in again["totals"].values()} == {"cached_db"}
    assert [p["risk_change"] for p in again["people"]] == [
        p["risk_change"] for p in first["people"]
    ]


def test_other_weeks_are_served_only_from_the_cache(hs):
    db, cfg = hs.app.state.db, hs.app.state.settings.config.roster
    nxt = date(2029, 12, 31)
    assert (
        hs.post("/roster/generate", json={"week_start": str(nxt)}).status_code == 422
    )  # not cached
    r = hs.post("/roster/generate", json={"deterministic": True}).json()
    stored = dbcache.get(db, cfg, WEEK, [])["result"]
    shifted = [{**a, "date": "2029-12-31"} for a in stored["assignments"][:3]]
    assert dbcache.put(db, cfg, nxt, [], {**stored, "assignments": shifted}, True, "test")
    got = hs.post("/roster/generate", json={"week_start": str(nxt)}).json()
    assert got["method"] == "cached_db" and got["week_start"] == str(nxt) and r["id"] != got["id"]


def test_key_ignores_solver_effort_but_not_rules():
    cfg = load_backend_config(hotel="himsagar").roster
    effort = cfg.model_copy(update={"time_limit_seconds": 120, "num_workers": 1})
    assert dbcache.rules_hash(effort) == dbcache.rules_hash(cfg)
    stricter = cfg.model_copy(update={"min_rest_hours": 11})
    assert dbcache.rules_hash(stricter) != dbcache.rules_hash(cfg)
    other = load_backend_config(hotel="original").roster
    assert (
        dbcache.cache_key(other, WEEK, [])["data_id"] != dbcache.cache_key(cfg, WEEK, [])["data_id"]
    )
    assert dbcache.cache_key(cfg, WEEK, ["B", "A", "A"])["protected_ids"] == ["A", "B"]
