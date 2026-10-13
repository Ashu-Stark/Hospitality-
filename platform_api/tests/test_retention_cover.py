"""Retention cover: someone's chance of leaving is HIGH -> look for job seekers on the tourism portal; nobody fits -> the
owner posts one job (idempotent). The portal is faked (no network). Staff are ids only; all data SYNTHETIC."""

from __future__ import annotations

import pytest
from conftest import auth

from hoi_platform import mongo
from hoi_platform.services import portal_client, staffing

KEY = "pk_test_RETENTION_456"
EMP = "HS05"  # housekeeping attendant in the demo hotel


class FakeMatches:
    def __init__(self, total: int = 0, fail: bool = False):
        self.total, self.fail, self.calls = total, fail, []

    def __call__(self, skill: str, api_key: str, limit: int = 5) -> dict:
        self.calls.append((skill, api_key))
        if self.fail:
            raise portal_client.PortalError("The tourism portal could not be reached (ConnectError).")
        items = [
            {
                "code": f"C-{i:03d}",
                "skills": [{"label": "Housekeeping", "years": 2}],
                "districts": ["Dehradun"],
                "availability": "Permanent",
                "match": 90 - i,
                "synthetic": True,
                "open_path": f"#/business/hiring/candidates/C-{i:03d}",
                "display_name": "Should Not Pass",  # extra fields from the portal are dropped
                "phone": "9876543210",
            }
            for i in range(min(self.total, 5))
        ]
        return {"total": self.total, "items": items, "search_path": f"#/business/hiring/candidates?skill={skill}"}


class FakeSend:
    def __init__(self, fail: bool = False):
        self.fail, self.calls = fail, []

    def __call__(self, payload: dict, api_key: str) -> dict:
        self.calls.append((payload, api_key))
        if self.fail:
            raise portal_client.PortalError("The tourism portal could not be reached (ConnectError).")
        return {"result": "created", "job_id": "JOB-000123", "status": "open"}


def _hotel(client, owner) -> str:
    return next(p for p in client.get("/workspace/properties", headers=owner).json() if p["mode"] == "hotel")["id"]


@pytest.fixture
def hotel_with_key(client, owner):
    pid = _hotel(client, owner)
    assert client.patch(f"/workspace/properties/{pid}", json={"portal_api_key": KEY}, headers=owner).status_code == 200
    yield pid
    client.patch(f"/workspace/properties/{pid}", json={"portal_api_key": ""}, headers=owner)
    mongo.col("staffing_requests").delete_many({"source": "retention"})


def test_high_risk_with_matches_shows_anonymised_profiles(client, owner, hotel_with_key, monkeypatch):
    fake = FakeMatches(total=7)
    monkeypatch.setattr(staffing.portal_client, "candidate_matches", fake)
    r = client.get(f"/staffing/cover/{EMP}", headers=owner)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "matches" and j["matches"] == 7 and len(j["candidates"]) == 5
    assert fake.calls == [("housekeeping", KEY)]
    assert "7 job seekers" in j["message"] and j["job"] is None and j["synthetic"]
    c = j["candidates"][0]
    assert c["code"] == "C-000" and c["open_url"].endswith("#/business/hiring/candidates/C-000")
    assert "display_name" not in c and "phone" not in c and "9876543210" not in r.text and "Should Not Pass" not in r.text
    assert KEY not in r.text and j["search_url"].endswith("skill=housekeeping")


def test_high_risk_no_matches_then_one_click_posts_a_job(client, owner, hotel_with_key, monkeypatch):
    monkeypatch.setattr(staffing.portal_client, "candidate_matches", FakeMatches(total=0))
    send = FakeSend()
    monkeypatch.setattr(staffing.portal_client, "send", send)
    j = client.get(f"/staffing/cover/{EMP}", headers=owner).json()
    assert j["status"] == "no_matches" and j["matches"] == 0 and j["candidates"] == []
    assert send.calls == []  # looking never posts: the owner decides
    out = client.post(f"/staffing/cover/{EMP}/post", headers=owner)
    assert out.status_code == 200, out.text
    p = out.json()
    assert p["created"] and p["message"] == "Job posted on the Uttarakhand Travel Guide."
    assert p["job"]["status"] == "sent" and p["job"]["portal_job_id"] == "JOB-000123"
    assert p["job"]["job_url"].endswith("/#/jobs/JOB-000123")
    ((payload, key),) = send.calls
    assert key == KEY and set(payload) == {"external_id", "department", "skill", "date_from", "date_to", "openings", "note"}
    assert payload["department"] == "housekeeping" and payload["skill"] == "housekeeping" and payload["openings"] == 1
    assert EMP not in payload["note"] and "leav" not in payload["note"].lower()  # the post never says why
    # Idempotent re-run: the open post is returned, nothing is sent again.
    again = client.post(f"/staffing/cover/{EMP}/post", headers=owner).json()
    assert not again["created"] and again["job"]["id"] == p["job"]["id"] and len(send.calls) == 1
    assert "already on the Uttarakhand Travel Guide" in again["message"]
    # The lookup now shows the open post, so the page can show the link instead of the button.
    assert client.get(f"/staffing/cover/{EMP}", headers=owner).json()["job"]["id"] == p["job"]["id"]
    assert mongo.col("staffing_requests").count_documents({"source": "retention", "for_employee": EMP}) == 1


def test_post_failure_stays_pending_and_a_retry_sends_it(client, owner, hotel_with_key, monkeypatch):
    monkeypatch.setattr(staffing.portal_client, "send", FakeSend(fail=True))
    first = client.post(f"/staffing/cover/{EMP}/post", headers=owner).json()
    assert first["created"] and first["job"]["status"] == "pending_send" and first["job"]["job_url"] is None
    assert "not on the portal yet" in first["message"]
    ok = FakeSend()
    monkeypatch.setattr(staffing.portal_client, "send", ok)
    second = client.post(f"/staffing/cover/{EMP}/post", headers=owner).json()
    assert not second["created"] and second["job"]["status"] == "sent" and len(ok.calls) == 1
    assert second["job"]["id"] == first["job"]["id"]


def test_cover_without_key_portal_error_and_access(client, owner, monkeypatch):
    pid = _hotel(client, owner)
    client.patch(f"/workspace/properties/{pid}", json={"portal_api_key": ""}, headers=owner)
    j = client.get(f"/staffing/cover/{EMP}", headers=owner).json()
    assert j["status"] == "no_key" and "API key" in j["message"]
    client.patch(f"/workspace/properties/{pid}", json={"portal_api_key": KEY}, headers=owner)
    try:
        monkeypatch.setattr(staffing.portal_client, "candidate_matches", FakeMatches(fail=True))
        assert client.get(f"/staffing/cover/{EMP}", headers=owner).json()["status"] == "error"
        assert client.get("/staffing/cover/HS99", headers=owner).status_code == 404
        assert client.get(f"/staffing/cover/{EMP}", headers=auth(client, "HS05")).status_code == 403  # workers never
        assert client.get(f"/staffing/cover/{EMP}", headers=auth(client, "demo.frontoffice")).status_code == 403  # other dept
        assert client.get("/staffing/cover/HS01", headers=owner).json()["status"] == "no_skill"  # manager: not on the portal
    finally:
        client.patch(f"/workspace/properties/{pid}", json={"portal_api_key": ""}, headers=owner)


def test_portal_skill_mapping():
    assert staffing.portal_skill("fnb_service") == "fb_service"
    assert staffing.portal_skill("kitchen", "Kitchen helper") == "kitchen_helper"
    assert staffing.portal_skill("kitchen", "Cook") == "cook_indian"
    assert staffing.portal_skill("management") is None
