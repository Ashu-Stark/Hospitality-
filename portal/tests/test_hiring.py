"""Hiring board: profiles and privacy, contact reveal, match score, active-registration rule, application lifecycle,
messaging isolation, rate limits, k-anonymous officials view, seed idempotency."""

import dataclasses
import json
import re
import secrets
from datetime import date, timedelta

import pytest
from conftest import login
from hoi_portal import config, mongo, ratelimit, seed
from hoi_portal.services import matching

SKILLS = [{"key": "cook_pahadi", "years": 6}, {"key": "kitchen_helper", "years": 1}]


def _seeker(client, name: str | None = None) -> dict:
    name = name or "seeker." + secrets.token_hex(3)
    r = client.post("/api/v1/auth/register", json={"username": name, "password": "a-long-test-password", "role": "job_seeker"})
    assert r.status_code == 201, r.text
    assert r.json()["user"]["role"] == "job_seeker"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _profile_body(**kw) -> dict:
    body = {
        "display_name": "Meena",
        "headline": "Cook for pahadi food, six years",
        "skills": SKILLS,
        "certifications": ["Food safety training", "  First   aid "],
        "languages": ["Hindi", "Garhwali"],
        "districts": ["rudraprayag"],
        "availability": "seasonal",
        "available_from": (date.today() + timedelta(days=5)).isoformat(),
        "available_to": (date.today() + timedelta(days=200)).isoformat(),
        "pay_min": 14000,
        "pay_max": 18000,
        "bio": "Test profile.",
        "phone": "+91 98765 43210",
        "email": "meena@example.invalid",
        "consent": True,
    }
    body.update(kw)
    return body


def _with_profile(client, **kw) -> tuple[dict, dict]:
    h = _seeker(client)
    r = client.post("/api/v1/me/seeker/profile", json=_profile_body(**kw), headers=h)
    assert r.status_code == 201, r.text
    return h, r.json()


def _demo_job(client, owner) -> dict:
    mine = client.get("/api/v1/jobs/mine", headers=owner).json()
    assert mine["can_hire"]
    biz = mine["active_businesses"][0]
    body = {
        "business_id": biz["id"],
        "title": "Cook for the season",
        "skills": ["cook_pahadi"],
        "job_type": "seasonal",
        "season_from": (date.today() + timedelta(days=10)).isoformat(),
        "season_to": (date.today() + timedelta(days=120)).isoformat(),
        "pay_min": 15000,
        "pay_max": 20000,
        "accommodation": True,
        "food": True,
        "openings": 2,
        "languages": ["Hindi"],
        "description": "Cook pahadi and Indian meals for guests (test).",
        "closes_on": (date.today() + timedelta(days=20)).isoformat(),
    }
    r = client.post("/api/v1/jobs", json=body, headers=owner)
    assert r.status_code == 201, r.text
    return r.json()


def _other_active_business(client) -> dict:
    """A second business owner with an ACTIVE registration (inserted directly; the approval flow is tested elsewhere)."""
    name = "owner." + secrets.token_hex(3)
    r = client.post("/api/v1/auth/register", json={"username": name, "password": "a-long-test-password"})
    uid = r.json()["user"]["id"]
    mongo.db().businesses.insert_one(
        {
            "id": "biz_t" + secrets.token_hex(3),
            "reg_no": f"UK-HMS-CHM-9{secrets.randbelow(9999):04d}",
            "name": "Test Sample Homestay, Auli",
            "name_lc": "test sample homestay, auli",
            "type": "homestay",
            "district": "chamoli",
            "destination_id": "auli",
            "status": "active",
            "verified": True,
            "valid_until": (date.today() + timedelta(days=200)).isoformat(),
            "owner_user_id": uid,
            "languages": ["Hindi"],
            "synthetic": True,
        }
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ------------------------------------------------------------------ profiles
def test_profile_create_update_hide_delete(client, owner):
    h = _seeker(client)
    empty = client.get("/api/v1/me/seeker/profile", headers=h).json()
    assert empty["profile"] is None and empty["consent_notice"]["points"]
    no_consent = client.post("/api/v1/me/seeker/profile", json=_profile_body(consent=False), headers=h)
    assert no_consent.status_code == 422 and "consent" in no_consent.json()["detail"]
    no_contact = client.post("/api/v1/me/seeker/profile", json=_profile_body(phone=None, email=None), headers=h)
    assert no_contact.status_code == 422
    r = client.post("/api/v1/me/seeker/profile", json=_profile_body(), headers=h)
    assert r.status_code == 201, r.text
    p = r.json()
    assert re.match(r"^C-\d{4}$", p["code"]) and p["phone"] == "+91 98765 43210" and p["visibility"] == "public"
    assert p["certifications"] == ["Food safety training", "First aid"] and p["consent"]["version"]
    assert client.post("/api/v1/me/seeker/profile", json=_profile_body(), headers=h).status_code == 409

    up = client.patch("/api/v1/me/seeker/profile", json={"headline": "Head cook, pahadi thali", "pay_max": 21000}, headers=h)
    assert up.status_code == 200 and up.json()["headline"] == "Head cook, pahadi thali" and up.json()["pay_max"] == 21000
    assert client.patch("/api/v1/me/seeker/profile", json={"pay_min": 30000}, headers=h).status_code == 422  # min > max
    assert client.patch("/api/v1/me/seeker/profile", json={"skills": [{"key": "astronaut", "years": 1}]}, headers=h).status_code == 422

    def in_search() -> bool:
        items = client.get("/api/v1/candidates", params={"skill": "cook_pahadi", "page_size": 50}, headers=owner).json()["items"]
        return p["code"] in {c["code"] for c in items}

    assert in_search()
    assert client.patch("/api/v1/me/seeker/profile", json={"visibility": "hidden"}, headers=h).json()["visibility"] == "hidden"
    assert not in_search()
    assert client.get(f"/api/v1/candidates/{p['code']}", headers=owner).status_code == 404
    client.patch("/api/v1/me/seeker/profile", json={"visibility": "public"}, headers=h)

    # Delete removes the profile and everything linked to it; the audit entry has no personal data.
    job = _demo_job(client, owner)
    a = client.post(f"/api/v1/jobs/{job['id']}/apply", json={"note": "Hello"}, headers=h).json()
    client.post(f"/api/v1/jobs/threads/{a['id']}", json={"text": "Is food provided?"}, headers=h)
    client.post(f"/api/v1/candidates/{p['code']}/interest", json={"message": "Hi"}, headers=owner)
    r = client.delete("/api/v1/me/seeker/profile", headers=h)
    assert r.status_code == 200 and r.json()["applications_removed"] == 1 and r.json()["interest_requests_removed"] == 1
    d = mongo.db()
    assert d.seeker_profiles.count_documents({"code": p["code"]}) == 0
    assert d.job_applications.count_documents({"candidate_id": p["code"]}) == 0
    assert d.interest_requests.count_documents({"candidate_id": p["code"]}) == 0
    assert d.job_messages.count_documents({"thread_id": a["id"]}) == 0
    entry = d.audit_log.find_one({"action": "seeker.profile.deleted", "target": p["code"]})
    assert entry and "Meena" not in json.dumps(entry, default=str) and "98765" not in json.dumps(entry, default=str)
    assert client.get("/api/v1/me/seeker/profile", headers=h).json()["profile"] is None


@pytest.mark.parametrize("field", ["gender", "age", "date_of_birth", "religion", "caste", "marital_status", "photo", "address"])
def test_protected_fields_rejected(client, field):
    h = _seeker(client)
    r = client.post("/api/v1/me/seeker/profile", json=_profile_body(**{field: "x"}), headers=h)
    assert r.status_code == 422
    assert "does not collect" in json.dumps(r.json())
    assert client.get("/api/v1/me/seeker/profile", headers=h).json()["profile"] is None
    client.post("/api/v1/me/seeker/profile", json=_profile_body(), headers=h)
    r = client.patch("/api/v1/me/seeker/profile", json={field: "x"}, headers=h)
    assert r.status_code == 422 and "does not collect" in json.dumps(r.json())
    stored = mongo.db().seeker_profiles.find_one({"user_id": client.get("/api/v1/auth/me", headers=h).json()["user"]["id"]})
    assert field not in stored


def test_seeded_profiles_have_no_protected_or_real_looking_data(client):
    from hoi_portal.schemas import PROTECTED_FIELDS

    for p in mongo.db().seeker_profiles.find({"synthetic": True}):
        assert not (set(p) & PROTECTED_FIELDS)
        if "user_id" not in p:
            assert re.match(r"^Candidate C-\d{4}$", p["display_name"])
            assert re.match(r"^\+91-90000-0\d{4}$", p["phone"]) and p["email"] is None


# ------------------------------------------------------------------ contact reveal
def test_contact_hidden_until_candidate_accepts(client, owner):
    h, p = _with_profile(client, phone="+91 91234 56789", email="hidden@example.invalid")
    secret_bits = ("91234", "hidden@example.invalid")

    def leaks(resp) -> bool:
        return any(s in resp.text for s in secret_bits)

    search = client.get("/api/v1/candidates", params={"skill": "cook_pahadi", "page_size": 50}, headers=owner)
    assert p["code"] in search.text and not leaks(search)
    assert not leaks(client.get("/api/v1/jobs", params={"page_size": 50}))
    detail = client.get(f"/api/v1/candidates/{p['code']}", headers=owner)
    assert detail.status_code == 200 and detail.json()["contact"] is None and not leaks(detail)

    sent = client.post(f"/api/v1/candidates/{p['code']}/interest", json={"message": "We are hiring cooks."}, headers=owner)
    assert sent.status_code == 201 and not leaks(sent)
    assert client.post(f"/api/v1/candidates/{p['code']}/interest", json={}, headers=owner).status_code == 409
    assert not leaks(client.get("/api/v1/candidates/interests", headers=owner))

    inbox = client.get("/api/v1/me/seeker/interests", headers=h).json()
    req = next(i for i in inbox["items"] if i["id"] == sent.json()["id"])
    assert req["status"] == "pending" and req["business_name"]
    assert client.post(f"/api/v1/me/seeker/interests/{req['id']}", json={"action": "accept"}, headers=h).json()["status"] == "accepted"
    assert client.post(f"/api/v1/me/seeker/interests/{req['id']}", json={"action": "decline"}, headers=h).status_code == 409

    after = client.get(f"/api/v1/candidates/{p['code']}", headers=owner).json()
    assert after["contact"]["phone"] == "+91 91234 56789" and after["contact"]["email"] == "hidden@example.invalid"
    sent_list = client.get("/api/v1/candidates/interests", headers=owner).json()
    assert next(i for i in sent_list["items"] if i["id"] == req["id"])["candidate"]["contact"]["phone"] == "+91 91234 56789"
    # Search results never carry contact details, even after acceptance; other businesses still see none.
    assert not leaks(client.get("/api/v1/candidates", params={"skill": "cook_pahadi", "page_size": 50}, headers=owner))
    other = _other_active_business(client)
    od = client.get(f"/api/v1/candidates/{p['code']}", headers=other)
    assert od.status_code == 200 and od.json()["contact"] is None and not leaks(od)


# ------------------------------------------------------------------ match score
def test_match_score_is_deterministic_and_explained():
    job = {
        "skills": ["trek_guide"],
        "district": "chamoli",
        "job_type": "seasonal",
        "season_from": "2027-05-01",
        "season_to": "2027-06-29",
        "languages": ["Hindi", "Garhwali"],
    }
    prof = {
        "skills": [{"key": "trek_guide", "years": 5}],
        "districts": ["chamoli"],
        "availability": "seasonal",
        "languages": ["Hindi"],
    }
    a, b = matching.score(job, prof), matching.score(job, prof)
    assert a == b
    assert a["score"] == 95  # skills 50 + district 20 + availability 20 + language 0.5 x 10
    texts = [w["text"] for w in a["why"]]
    assert "Trek guide: 5 yrs" in texts and "Prefers Chamoli" in texts and "No Garhwali" in texts
    assert [p["key"] for p in a["parts"]] == ["skills", "district", "availability", "language"]

    # Experience counts: 0 years earns half the skill credit; a same-category skill earns the related credit.
    zero = matching.score({"skills": ["trek_guide"]}, {"skills": [{"key": "trek_guide", "years": 0}]})
    assert zero["score"] == 50 and len(zero["parts"]) == 1  # only the criteria that are set are scored
    related = matching.score({"skills": ["trek_guide"]}, {"skills": [{"key": "rafting_guide", "years": 9}]})
    assert related["score"] == 25 and related["why"][0]["text"].startswith("Related skill")
    # District: any-district and same-division credits; availability: half the season, type mismatch.
    assert matching.score({"district": "chamoli"}, {"districts": []})["score"] == 75
    assert matching.score({"district": "chamoli"}, {"districts": ["rudraprayag"]})["score"] == 40
    assert matching.score({"district": "chamoli"}, {"districts": ["almora"]})["score"] == 0
    half = matching.score(
        {"job_type": "seasonal", "season_from": "2027-05-01", "season_to": "2027-05-30"},
        {"availability": "permanent", "available_from": "2027-05-16"},
    )
    assert half["score"] == 25  # 0.5 type factor x 0.5 of the season
    assert matching.score({}, prof)["score"] is None
    # Inputs other than the four criteria are ignored entirely.
    assert matching.score(job, {**prof, "display_name": "X", "bio": "anything"})["score"] == 95


def test_candidate_search_is_ranked_and_filtered(client, owner):
    params = {"skill": "housekeeping", "district": "rudraprayag", "exp_min": 1, "page_size": 50}
    r1 = client.get("/api/v1/candidates", params=params, headers=owner).json()
    r2 = client.get("/api/v1/candidates", params=params, headers=owner).json()
    assert r1 == r2 and r1["total"] > 0
    scores = [c["match"]["score"] for c in r1["items"]]
    assert scores == sorted(scores, reverse=True)
    for c in r1["items"]:
        hk = next(s for s in c["skills"] if s["key"] == "housekeeping")
        assert hk["years"] >= 1 and (c["any_district"] or "rudraprayag" in c["districts"])
        assert c["match"]["why"] and "contact" not in c
    assert client.get("/api/v1/candidates", params={"page_size": 12}, headers=owner).json()["page_size"] == 12


# ------------------------------------------------------------------ roles and the active-registration rule
def test_business_must_have_active_registration(client, officer):
    name = "owner." + secrets.token_hex(3)
    r = client.post("/api/v1/auth/register", json={"username": name, "password": "a-long-test-password"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    uid = r.json()["user"]["id"]
    assert client.get("/api/v1/jobs/mine", headers=h).json()["can_hire"] is False
    assert client.get("/api/v1/candidates", headers=h).status_code == 403
    mongo.db().businesses.insert_one(
        {
            "id": "biz_s" + secrets.token_hex(3),
            "reg_no": "UK-HTL-DDN-8" + f"{secrets.randbelow(9999):04d}",
            "name": "Suspended Sample Hotel",
            "name_lc": "suspended sample hotel",
            "type": "hotel",
            "district": "dehradun",
            "destination_id": "mussoorie",
            "status": "suspended",
            "valid_until": (date.today() + timedelta(days=100)).isoformat(),
            "owner_user_id": uid,
        }
    )
    biz = mongo.db().businesses.find_one({"owner_user_id": uid})
    body = {
        "business_id": biz["id"],
        "title": "Receptionist",
        "skills": ["front_office"],
        "job_type": "permanent",
        "description": "Front desk work, morning shift (test).",
        "closes_on": (date.today() + timedelta(days=10)).isoformat(),
    }
    r = client.post("/api/v1/jobs", json=body, headers=h)
    assert r.status_code == 403 and "active registration" in r.json()["detail"]
    assert client.post("/api/v1/candidates/C-0001/interest", json={}, headers=h).status_code == 403
    # Other roles cannot use business or seeker endpoints; officers never see candidates.
    seeker = _seeker(client)
    assert client.post("/api/v1/jobs", json=body, headers=seeker).status_code == 403
    assert client.get("/api/v1/candidates", headers=officer).status_code == 403
    assert client.get("/api/v1/me/seeker", headers=h).status_code == 403
    assert client.get("/api/v1/candidates").status_code == 401


def test_job_post_validation(client, owner):
    biz = client.get("/api/v1/jobs/mine", headers=owner).json()["active_businesses"][0]
    base = {
        "business_id": biz["id"],
        "title": "Helper",
        "skills": ["kitchen_helper"],
        "job_type": "seasonal",
        "description": "Kitchen help for the season (test).",
        "closes_on": (date.today() + timedelta(days=10)).isoformat(),
    }
    assert client.post("/api/v1/jobs", json=base, headers=owner).status_code == 422  # seasonal needs dates
    late = {**base, "job_type": "permanent", "closes_on": (date.today() + timedelta(days=400)).isoformat()}
    assert client.post("/api/v1/jobs", json=late, headers=owner).status_code == 422
    assert client.post("/api/v1/jobs", json={**base, "job_type": "permanent", "skills": ["pilot"]}, headers=owner).status_code == 422
    assert client.post("/api/v1/jobs", json={**base, "job_type": "permanent", "description": "x" * 1001}, headers=owner).status_code == 422


# ------------------------------------------------------------------ applications
def test_application_lifecycle(client, owner):
    job = _demo_job(client, owner)
    pub = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert pub["status"] == "open" and "applications" not in pub and "owner_user_id" not in pub
    no_profile = _seeker(client)
    assert client.post(f"/api/v1/jobs/{job['id']}/apply", json={}, headers=no_profile).status_code == 409

    h, p = _with_profile(client)
    seen = client.get(f"/api/v1/jobs/{job['id']}", headers=h).json()
    assert seen["match"]["score"] is not None and seen["my_application"] is None
    a = client.post(f"/api/v1/jobs/{job['id']}/apply", json={"note": "Available from next week."}, headers=h)
    assert a.status_code == 201 and a.json()["status"] == "applied"
    app_id = a.json()["id"]
    assert client.post(f"/api/v1/jobs/{job['id']}/apply", json={}, headers=h).status_code == 409

    listed = client.get(f"/api/v1/jobs/{job['id']}/applications", headers=owner).json()
    mine = next(x for x in listed["items"] if x["id"] == app_id)
    assert mine["status"] == "viewed" and mine["candidate"]["contact"] is None and mine["match"]["score"] is not None

    def move(status, code=200):
        r = client.post(f"/api/v1/jobs/applications/{app_id}/status", json={"status": status}, headers=owner)
        assert r.status_code == code, r.text

    move("shortlisted")
    move("contacted")
    move("viewed", 409)
    status = next(x for x in client.get("/api/v1/me/seeker/applications", headers=h).json()["items"] if x["id"] == app_id)
    assert status["status"] == "contacted" and [s["status"] for s in status["history"]] == ["applied", "viewed", "shortlisted", "contacted"]
    other = _other_active_business(client)
    assert client.post(f"/api/v1/jobs/applications/{app_id}/status", json={"status": "not_selected"}, headers=other).status_code == 404
    assert client.get(f"/api/v1/jobs/{job['id']}/applications", headers=other).status_code == 404

    assert client.post(f"/api/v1/me/seeker/applications/{app_id}/withdraw", headers=h).json()["status"] == "withdrawn"
    assert client.post(f"/api/v1/me/seeker/applications/{app_id}/withdraw", headers=h).status_code == 409
    assert app_id not in {x["id"] for x in client.get(f"/api/v1/jobs/{job['id']}/applications", headers=owner).json()["items"]}

    # Closing the post removes it from the public board; applying is refused.
    closed = client.patch(f"/api/v1/jobs/{job['id']}", json={"status": "closed", "closed_reason": "filled"}, headers=owner).json()
    assert closed["status"] == "closed" and closed["closed_reason"] == "filled"
    assert job["id"] not in {j["id"] for j in client.get("/api/v1/jobs", params={"page_size": 50}).json()["items"]}
    h2, _ = _with_profile(client)
    assert client.post(f"/api/v1/jobs/{job['id']}/apply", json={}, headers=h2).status_code == 409


def test_public_job_board_filters(client):
    r = client.get("/api/v1/jobs").json()
    assert r["total"] >= 25 and len(r["items"]) == 12 and r["matched_to_profile"] is False
    assert all("match" not in j and j["status"] == "open" for j in r["items"])
    by_d = client.get("/api/v1/jobs", params={"district": "rudraprayag", "page_size": 50}).json()
    assert all(j["district"] == "rudraprayag" for j in by_d["items"])
    sk = client.get("/api/v1/jobs", params={"skill": "cook_pahadi", "page_size": 50}).json()
    assert all(any(s["key"] == "cook_pahadi" for s in j["skills"]) for j in sk["items"])
    meta = client.get("/api/v1/jobs/meta").json()
    assert len(meta["skills"]) >= 25 and "Garhwali" in meta["languages"] and meta["consent_notice"]["version"]


# ------------------------------------------------------------------ messages
def test_messaging_isolation(client, owner, officer):
    job = _demo_job(client, owner)
    h, p = _with_profile(client)
    app_id = client.post(f"/api/v1/jobs/{job['id']}/apply", json={}, headers=h).json()["id"]
    assert (
        client.post(f"/api/v1/jobs/threads/{app_id}", json={"text": "Namaste, when does the season start?"}, headers=h).status_code == 201
    )
    assert client.post(f"/api/v1/jobs/threads/{app_id}", json={"text": "From the 1st. Can you join?"}, headers=owner).status_code == 201
    t = client.get(f"/api/v1/jobs/threads/{app_id}", headers=h).json()
    assert [m["from"] for m in t["items"]] == ["job_seeker", "business"] and t["items"][0]["mine"] is True
    assert client.get(f"/api/v1/jobs/threads/{app_id}", headers=owner).json()["total"] == 2
    intruder_seeker, _ = _with_profile(client)
    other_business = _other_active_business(client)
    for hh in (intruder_seeker, other_business):
        assert client.get(f"/api/v1/jobs/threads/{app_id}", headers=hh).status_code == 404
        assert client.post(f"/api/v1/jobs/threads/{app_id}", json={"text": "hi"}, headers=hh).status_code == 404
    assert client.get(f"/api/v1/jobs/threads/{app_id}", headers=officer).status_code == 403
    assert client.get(f"/api/v1/jobs/threads/{app_id}").status_code == 401
    assert client.post(f"/api/v1/jobs/threads/{app_id}", json={"text": "x" * 1001}, headers=h).status_code == 422
    assert client.post(f"/api/v1/jobs/threads/{app_id}", json={"text": "   "}, headers=h).status_code in (422,)

    # Interest threads open only after acceptance.
    iid = client.post(f"/api/v1/candidates/{p['code']}/interest", json={"job_id": job["id"]}, headers=owner).json()["id"]
    assert client.post(f"/api/v1/jobs/threads/{iid}", json={"text": "Hello"}, headers=owner).status_code == 409
    client.post(f"/api/v1/me/seeker/interests/{iid}", json={"action": "accept"}, headers=h)
    assert client.post(f"/api/v1/jobs/threads/{iid}", json={"text": "Hello"}, headers=owner).status_code == 201
    assert client.get(f"/api/v1/jobs/threads/{iid}", headers=intruder_seeker).status_code == 404


# ------------------------------------------------------------------ rate limits
def test_profile_and_message_rate_limits(client, owner, monkeypatch):
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, profile_rate_per_hour=1, message_rate_per_hour=2))
    ratelimit.reset()
    try:
        h = _seeker(client)
        assert client.post("/api/v1/me/seeker/profile", json=_profile_body(), headers=h).status_code == 201
        again = client.post("/api/v1/me/seeker/profile", json=_profile_body(), headers=h)
        assert again.status_code == 429 and again.headers["retry-after"]
        job = _demo_job(client, owner)
        app_id = client.post(f"/api/v1/jobs/{job['id']}/apply", json={}, headers=h).json()["id"]
        codes = [client.post(f"/api/v1/jobs/threads/{app_id}", json={"text": f"m{i}"}, headers=h).status_code for i in range(3)]
        assert codes == [201, 201, 429]
    finally:
        ratelimit.reset()


# ------------------------------------------------------------------ officials analytics (k-anonymity)
def test_workforce_market_aggregates_and_k_anonymity(client, admin, officer):
    d = mongo.db()
    w = client.get("/api/v1/analytics/workforce-market", headers=admin).json()
    assert w["synthetic"] is True and "SYNTHETIC" in w["note"] and w["k_min"] == 5
    assert w["totals"]["open_posts"] > 0 and len(w["by_district"]) == 13 and len(w["seasonal"]["openings"]) == 12
    for row in w["by_skill"] + w["by_district"]:
        assert row["suppressed"] == (row["candidates"] is None)
        assert row["candidates"] is None or row["candidates"] >= 5
        assert (row["gap"] is None) == row["suppressed"]
    text = json.dumps(w)
    assert "C-00" not in text and "Candidate " not in text and "+91" not in text

    # Force a small group: hide all but 3 profiles with the best-supplied skill -> that row is suppressed.
    top = max((r for r in w["by_skill"] if not r["suppressed"]), key=lambda r: r["candidates"])
    keep = [p["code"] for p in d.seeker_profiles.find({"visibility": "public", "skill_keys": top["key"]}).limit(3)]
    hide = {"visibility": "public", "skill_keys": top["key"], "code": {"$nin": keep}}
    hidden = [p["code"] for p in d.seeker_profiles.find(hide)]
    d.seeker_profiles.update_many({"code": {"$in": hidden}}, {"$set": {"visibility": "hidden"}})
    try:
        w2 = client.get("/api/v1/analytics/workforce-market", headers=admin).json()
        row = next((r for r in w2["by_skill"] if r["key"] == top["key"]), None)
        assert row is not None and row["suppressed"] and row["candidates"] is None and row["gap"] is None
    finally:
        d.seeker_profiles.update_many({"code": {"$in": hidden}}, {"$set": {"visibility": "public"}})

    o = client.get("/api/v1/analytics/workforce-market", headers=officer).json()
    assert o["scope"]["district"] == "rudraprayag" and [r["key"] for r in o["by_district"]] == ["rudraprayag"]
    assert client.get("/api/v1/analytics/workforce-market", params={"district": "chamoli"}, headers=officer).status_code == 403
    assert client.get("/api/v1/analytics/workforce-market", headers=login(client, "demo.business")).status_code == 403


# ------------------------------------------------------------------ seed
def test_hiring_seed_is_idempotent_and_does_not_touch_other_data(client):
    d = mongo.db()
    before = {c: d[c].count_documents({}) for c in ("seeker_profiles", "job_posts", "job_applications", "interest_requests", "businesses")}
    assert before["seeker_profiles"] >= 121 and before["job_posts"] >= 44
    assert seed.ensure_hiring(d) is None
    d.meta.delete_one({"_id": "hiring_seed"})  # even without the lock, non-empty collections stop a re-seed
    assert seed.ensure_hiring(d) is None
    after = {c: d[c].count_documents({}) for c in before}
    assert after == before
    stats = mongo.db().meta.find_one({"_id": "demo_seed"})
    assert stats and stats["state"] == "done"
    demo = client.get("/api/v1/me/seeker", headers=login(client, "demo.seeker")).json()
    assert demo["profile"]["code"] == "C-0121" and demo["summary"]["interests_pending"] >= 1
