"""B1: skeleton endpoints, MOCK mode, MongoDB collections and seed (all data SYNTHETIC)."""

from backend.db import AUDIT, COLLECTIONS, EMPLOYEES, TASKS, snapshot_frame
from backend.schemas import AttritionScore, ForecastResult, RescoreResult


def test_health_lists_model_versions(client) -> None:
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["synthetic"] and not h["mock"]
    assert h["database"] == "mongomock"  # tests never touch Atlas
    assert "mongomock://" not in str(h)  # never the URI
    names = {m["name"] for m in h["models"]}
    assert {"attrition", "occupancy_forecast", "pulse", "workload"} <= names
    assert all(len(m["dataset_sha256"]) == 64 for m in h["models"])


def test_forecast_endpoint(client) -> None:
    r = client.get("/forecast", params={"from": "2029-12-24", "to": "2029-12-26"})
    assert r.status_code == 200
    f = ForecastResult.model_validate(r.json())
    assert len(f.days) == 3 and f.synthetic
    bad = client.get("/forecast", params={"from": "2031-01-01", "to": "2031-01-02"})
    assert bad.status_code == 422


def test_score_and_rescore(client) -> None:
    r = client.post("/attrition/score", json={"employee_ids": ["H901", "H905"]})
    assert r.status_code == 200
    scores = [AttritionScore.model_validate(x) for x in r.json()]
    assert {s.employee_id for s in scores} == {"H901", "H905"}
    rr = client.post("/attrition/rescore", json={"employee_id": "H901",
                                                 "protected_weekends_off": 2})
    res = RescoreResult.model_validate(rr.json())
    assert "SIMULATION" in res.note
    assert client.post("/attrition/score", json={"employee_ids": ["NOPE"]}).status_code == 422


def test_mock_mode_serves_the_mock_files(mock_client) -> None:
    assert mock_client.get("/health").json()["mock"]
    f = mock_client.get("/forecast", params={"from": "2029-12-24", "to": "2029-12-30"}).json()
    assert len(f["days"]) == 7
    scores = mock_client.post("/attrition/score", json={}).json()
    assert len(scores) == 60 and "band_basis" in scores[0]
    assert mock_client.post("/attrition/rescore", json={"employee_id": "H901"}).status_code == 200
    assert mock_client.post("/attrition/rescore", json={"employee_id": "E001"}).status_code == 404


def test_documents_have_id_created_at_and_source(client) -> None:
    client.post("/roster/generate", json={"use_cache": True})
    client.post("/tasks", json={"idempotency_key": "d1", "title": "t", "assignee": "a"})
    client.post("/loop/run")
    db = client.app.state.db
    for name in COLLECTIONS:
        docs = list(db[name].find({}, {"_id": 0}))
        assert docs, name
        assert all({"id", "created_at", "source"} <= set(d) for d in docs), name
        assert all(d["created_at"].tzinfo is not None for d in docs), name
        ids = [d["id"] for d in docs]
        assert len(ids) == len(set(ids)) and all(isinstance(i, int) for i in ids), name


def test_indexes_enforce_the_business_rules(client) -> None:
    db = client.app.state.db

    def unique(name: str) -> set[tuple[str, ...]]:
        return {tuple(k for k, _ in i["key"]) for i in db[name].index_information().values()
                if i.get("unique")}

    assert {("id",), ("idempotency_key",)} <= unique(TASKS)
    assert ("task_id", "kind") in unique("task_event")


def test_seed_matches_the_ml_snapshot(client) -> None:
    db = client.app.state.db
    rows = list(db[EMPLOYEES].find({}, {"_id": 0}))
    assert len(rows) == len(snapshot_frame())
    heroes = {r["employee_id"] for r in rows if r["is_demo_hero"]}
    assert heroes == {"H901", "H902", "H903", "H904", "H905"}
    assert all(r["source"] == "ml/data (SYNTHETIC)" for r in rows)
    assert all(isinstance(r["skills"], list) for r in rows)
    for banned in ("name", "gender", "age", "religion", "caste", "health", "family"):
        assert all(banned not in r for r in rows), banned
    client.post("/attrition/score", json={"employee_ids": ["H901"]})
    assert db[AUDIT].find_one({"action": "attrition.score"})
