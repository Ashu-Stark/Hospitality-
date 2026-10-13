"""HOI retention check: GET /api/v1/ingest/candidate-matches (X-API-Key). Count + anonymised previews only. SYNTHETIC data."""

from hoi_portal import mongo

FORBIDDEN = ("display_name", "headline", "bio", "phone", "email", "user_id", "contact")


def _hotel_key(client, owner) -> tuple[dict, str]:
    items = client.get("/api/v1/business/businesses", headers=owner).json()["items"]
    hotel = next(b for b in items if b["type"] == "hotel" and b["status"] == "active")
    raw = client.post(f"/api/v1/business/businesses/{hotel['id']}/api-keys", json={"label": "HOI retention"}, headers=owner).json()["api_key"]
    return hotel, raw


def _expected(skill: str, district: str) -> int:
    flt = {"visibility": "public", "skill_keys": skill, "$or": [{"districts": district}, {"districts": {"$size": 0}}]}
    return mongo.db().seeker_profiles.count_documents(flt)


def test_candidate_matches_needs_a_key(client):
    assert client.get("/api/v1/ingest/candidate-matches", params={"skill": "housekeeping"}).status_code == 401
    r = client.get("/api/v1/ingest/candidate-matches", params={"skill": "housekeeping"}, headers={"X-API-Key": "uthp_wrong"})
    assert r.status_code == 401


def test_candidate_matches_count_and_anonymised_previews(client, owner):
    hotel, raw = _hotel_key(client, owner)
    h = {"X-API-Key": raw}
    r = client.get("/api/v1/ingest/candidate-matches", params={"skill": "housekeeping"}, headers=h)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["district"]["id"] == hotel["district"] and j["skill"]["key"] == "housekeeping"
    assert j["total"] == _expected("housekeeping", hotel["district"])
    assert len(j["items"]) == min(5, j["total"])
    for it in j["items"]:
        assert set(it) == {"code", "skills", "districts", "availability", "available_from", "available_to", "match", "synthetic", "open_path"}
        assert it["open_path"].endswith(it["code"])
    text = str(j)
    for p in mongo.db().seeker_profiles.find({"code": {"$in": [i["code"] for i in j["items"]]}}):
        for k in ("phone", "email", "display_name"):
            if p.get(k):
                assert str(p[k]) not in text  # never leaked
    assert not any(f"'{k}'" in text for k in FORBIDDEN)
    # Scores are sorted best first; limit caps the previews but not the count.
    scores = [i["match"] or 0 for i in j["items"]]
    assert scores == sorted(scores, reverse=True)
    small = client.get("/api/v1/ingest/candidate-matches", params={"skill": "housekeeping", "limit": 1}, headers=h).json()
    assert small["total"] == j["total"] and len(small["items"]) == min(1, j["total"])


def test_candidate_matches_maps_hoi_departments_and_rejects_unknown(client, owner):
    hotel, raw = _hotel_key(client, owner)
    h = {"X-API-Key": raw}
    fb = client.get("/api/v1/ingest/candidate-matches", params={"skill": "fnb_service"}, headers=h).json()
    assert fb["skill"]["key"] == "fb_service" and fb["total"] == _expected("fb_service", hotel["district"])
    assert client.get("/api/v1/ingest/candidate-matches", params={"skill": "astronaut"}, headers=h).status_code == 422
    # Hidden profiles are never counted.
    was_public = [p["code"] for p in mongo.db().seeker_profiles.find({"skill_keys": "security_guard", "visibility": "public"})]
    mongo.db().seeker_profiles.update_many({"code": {"$in": was_public}}, {"$set": {"visibility": "hidden"}})
    try:
        none = client.get("/api/v1/ingest/candidate-matches", params={"skill": "security_guard"}, headers=h).json()
        assert none["total"] == 0 and none["items"] == []
    finally:
        mongo.db().seeker_profiles.update_many({"code": {"$in": was_public}}, {"$set": {"visibility": "public"}})
