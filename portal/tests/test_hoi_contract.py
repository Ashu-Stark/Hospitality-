"""Contract test: the HOI platform's REAL staffing payloads and portal client, posted to this portal app in-process.

platform_api/hoi_platform/services/staffing.payload builds the body and portal_client sends it; here portal_client's HTTP
call is routed into the portal's TestClient (no network). Covers the hotel portal's "Extra staff" form (every department,
free-text skill, long note), the roster-shortage prefill, the retention "post the job" body and the candidate-matches call.
SYNTHETIC data only.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from conftest import login

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "platform_api"))
from hoi_platform.services import portal_client, staffing  # noqa: E402

DASHBOARD_DEPTS = ["housekeeping", "front_office", "fnb_service", "kitchen", "maintenance", "security"]  # 20_Extra_Staff.py


@pytest.fixture(scope="module")
def hotel_key(client):
    owner = login(client, "demo.business")
    items = client.get("/api/v1/business/businesses", headers=owner).json()["items"]
    hotel = next(b for b in items if b["type"] == "hotel" and b["status"] == "active")
    r = client.post(f"/api/v1/business/businesses/{hotel['id']}/api-keys", json={"label": "HOI contract"}, headers=owner)
    return r.json()["api_key"]


@pytest.fixture
def wired(client, monkeypatch):
    """portal_client -> this app, through the client's own _call (headers, status handling, error text)."""

    def request(method, url, json=None, params=None, headers=None, timeout=None):  # noqa: ANN001, ANN202
        assert url.startswith(portal_client.base_url())
        return client.request(method, url[len(portal_client.base_url()) :], json=json, params=params, headers=headers)

    monkeypatch.setattr(portal_client.httpx, "request", request)


def _req(n: int, **kw) -> dict:
    d0 = date.today() + timedelta(days=3)
    return {
        "id": f"stf_contract_{n}",
        "department": "housekeeping",
        "skill": "",
        "date_from": d0.isoformat(),
        "date_to": (d0 + timedelta(days=2)).isoformat(),
        "openings": 2,
        "note": "",
        **kw,
    }


def test_extra_staff_form_payloads_are_accepted(wired, hotel_key):
    for n, dept in enumerate(DASHBOARD_DEPTS):
        out = portal_client.send(staffing.payload(_req(n, department=dept)), hotel_key)
        assert out["result"] == "created" and out["job_id"], (dept, out)
    # free-text skill (form allows 60 characters) and the longest note (500) still fit the portal's schema
    body = staffing.payload(_req(10, skill="room cleaning, turn-down service, linen and minibar", note="Wedding weekend. " * 40))
    assert portal_client.send(body, hotel_key)["result"] == "created"
    # a repeat of the same request is idempotent on the portal
    assert portal_client.send(staffing.payload(_req(0)), hotel_key)["result"] in ("unchanged", "updated")


def test_roster_shortage_and_retention_cover_payloads(wired, hotel_key):
    short = _req(20, department="fnb_service", openings=1, note="Shift plan short by about 8 hours.")
    assert portal_client.send(staffing.payload(short), hotel_key)["result"] == "created"
    d0 = date.today()
    cover = _req(
        21,
        department="kitchen",
        skill=staffing.portal_skill("kitchen", "Kitchen helper"),
        date_from=d0.isoformat(),
        date_to=(d0 + timedelta(days=staffing.COVER_DAYS)).isoformat(),
        openings=1,
        note=staffing.COVER_NOTE.format(dept="kitchen"),
    )
    cover["id"] = f"stf_ret_prop_demo_himsagar_HS07_{d0.isoformat()}"
    assert portal_client.send(staffing.payload(cover), hotel_key)["result"] == "created"


def test_candidate_matches_for_every_mapped_skill(wired, hotel_key):
    for skill in {*staffing.PORTAL_SKILL.values(), "kitchen_helper"}:
        out = portal_client.candidate_matches(skill, hotel_key)
        assert "total" in out and isinstance(out.get("items"), list), skill


def test_a_portal_rejection_shows_its_reason(wired, hotel_key):
    far = (date.today() + timedelta(days=400)).isoformat()  # e.g. the 2029 demo roster week
    with pytest.raises(portal_client.PortalError) as e:
        portal_client.send(staffing.payload(_req(30, date_from=far, date_to=far)), hotel_key)
    assert e.value.status == 422 and "180 days" in e.value.message and hotel_key not in e.value.message
