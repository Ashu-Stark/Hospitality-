"""Regenerate docs/PORTAL_API.md with real (abbreviated) example responses from the app on mongomock.

    python portal/scripts/gen_api_doc.py            (from the repo root, with the project venv)

Offline: forces MONGODB_URI=mongomock:// and a fake weather fetcher (the live Open-Meteo shape).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

PORTAL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PORTAL))
os.environ.update(
    MONGODB_URI="mongomock://", HOI_PORTAL_DB="hoi_portal_docs", HOI_ENV="development", PORTAL_DEMO_LOGIN="true", PORTAL_SEED_DEMO="true"
)
os.environ.pop("PORTAL_ADMIN_PASSWORD", None)

from fastapi.testclient import TestClient  # noqa: E402
from hoi_portal import config, mongo  # noqa: E402

config.reload()
from hoi_portal.main import create_app  # noqa: E402
from hoi_portal.services import weather  # noqa: E402

OUT = PORTAL.parent / "docs" / "PORTAL_API.md"
HEADER = (PORTAL / "scripts" / "api_doc_header.md").read_text(encoding="utf-8")


def fake_forecast(lat, lon):
    days = [(date.today() + timedelta(days=i)).isoformat() for i in range(7)]
    return {
        "current": {"time": days[0] + "T10:00", "temperature_2m": 6.1, "weather_code": 3, "wind_speed_10m": 9.4},
        "daily": {
            "time": days,
            "temperature_2m_max": [9.5, 8.0, 7.2, 6.0, 8.8, 9.9, 10.4],
            "temperature_2m_min": [-1.2, -2.0, -3.1, -2.5, -1.0, 0.2, 0.4],
            "precipitation_probability_max": [15, 85, 60, 20, 10, 5, 5],
            "precipitation_sum": [0.0, 55.2, 8.1, 0.4, 0.0, 0.0, 0.0],
            "snowfall_sum": [0.0, 0.0, 6.3, 0.0, 0.0, 0.0, 0.0],
            "weather_code": [3, 65, 73, 2, 1, 0, 0],
        },
    }


def abbreviate(v, depth=0, list_keep=2, nums_keep=6):
    if isinstance(v, dict):
        return {k: abbreviate(x, depth + 1, list_keep, nums_keep) for k, x in v.items()}
    if isinstance(v, list):
        if v and all(isinstance(x, int | float) or x is None for x in v):
            return v if len(v) <= nums_keep else v[:nums_keep] + [f"... {len(v) - nums_keep} more"]
        if v and all(isinstance(x, str) for x in v) and len(v) <= 8:
            return v
        out = [abbreviate(x, depth + 1, list_keep, nums_keep) for x in v[:list_keep]]
        if len(v) > list_keep:
            out.append(f"... {len(v) - list_keep} more")
        return out
    if isinstance(v, str) and len(v) > 140:
        return v[:137] + "..."
    return v


SECTIONS: list[tuple[str, list[dict]]] = []


def section(title):
    SECTIONS.append((title, []))


CLIENT: dict = {}


def ep(method, path, auth, desc, *, call=None, params=None, body=None, headers=None, status=None, keep=2):
    """Call the endpoint now (later examples may depend on it) and record the example."""
    c = CLIENT["c"]
    kw = {"headers": headers} if headers else {}
    if body is not None:
        kw["json"] = body
    r = c.request(method, call or path, **kw)
    expected = status or 200
    assert r.status_code == expected, (method, call or path, r.status_code, r.text[:300])
    SECTIONS[-1][1].append(
        dict(
            method=method,
            path=path,
            auth=auth,
            desc=desc,
            call=call or path,
            params=params,
            body=body,
            keep=keep,
            code=r.status_code,
            resp=r.json() if r.content else None,
        )
    )


def run():
    weather.set_fetcher(fake_forecast)
    mongo.reset()
    with TestClient(create_app()) as c:
        CLIENT["c"] = c

        def tok(u):
            return {"Authorization": "Bearer " + c.post(f"/api/v1/auth/demo/{u}").json()["access_token"]}

        admin, officer, owner = tok("demo.admin"), tok("demo.officer.rudraprayag"), tok("demo.business")
        d = mongo.db()
        biz = c.get("/api/v1/registry", params={"district": "rudraprayag", "status": "active", "page_size": 1}).json()["items"][0]
        mine = c.get("/api/v1/business/businesses", headers=owner).json()["items"]
        stay = next(b for b in mine if b["reports_occupancy"])
        due = next(b for b in mine if b["renewal_due"])
        app_rud = d.applications.find_one({"district": "rudraprayag", "status": "submitted", "kind": "new"})
        g_rud = d.grievances.find_one({"district": "rudraprayag", "status": "received"}) or d.grievances.find_one(
            {"district": "rudraprayag"}
        )
        users = {u["username"]: u["id"] for u in d.users.find({})}
        prev_month = (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

        # Grievance and API key are created first so later examples can use them.
        filed = c.post(
            "/api/v1/grievances",
            json={
                "category": "overcharging",
                "district": "rudraprayag",
                "description": "Taxi charged more than the agreed fare.",
                "contact": "optional, kept private",
            },
        ).json()
        key = c.post(f"/api/v1/business/businesses/{stay['id']}/api-keys", json={"label": "HOI ingest"}, headers=owner).json()

        section("Meta")
        ep("GET", "/health", "none", "Liveness.")
        ep("GET", "/ready", "none", "Readiness (pings MongoDB). 503 when the database is unreachable.")

        section("Public: reference and search")
        ep(
            "GET",
            "/api/v1/meta",
            "none",
            "Vocabularies for forms and filters: districts, destinations, business types, checklist, categories, bands.",
        )
        ep("GET", "/api/v1/districts", "none", "The 13 districts with prototype codes and division.")
        ep("GET", "/api/v1/stats/public", "none", "Home-page counters.")
        ep(
            "GET",
            "/api/v1/search",
            "none (60/min/IP)",
            "Unified search, grouped by type. All tokens must match (case-insensitive). Groups: destinations, businesses, events, dictionary, rules, advisories.",
            call="/api/v1/search?q=kedarnath&limit=2",
            params="`q` (2-200 chars, required; only the first 80 chars / 6 words are used), `limit` (1-25 per group, default 8)",
            keep=1,
        )

        section("Public: registry (A-Z directory)")
        ep(
            "GET",
            "/api/v1/registry",
            "none",
            "List businesses. `letters` = letters that have at least one business (for the A-Z index).",
            call="/api/v1/registry?district=rudraprayag&type=homestay&page_size=2",
            params="`type`, `district`, `destination`, `status` (active|expired|suspended|pending), `letter` (A-Z), `q`, `verified` (true), `page` (>=1), `page_size` (1-100, default 24)",
        )
        ep(
            "GET",
            "/api/v1/registry/verify",
            "none (60/min/IP)",
            "Verify a registration number. Always 200; check `found` and `valid`.",
            call=f"/api/v1/registry/verify?reg_no={biz['reg_no']}",
            params="`reg_no` (case and spaces ignored)",
        )
        ep(
            "GET",
            "/api/v1/registry/{id_or_reg_no}",
            "none",
            "One business by id or registration number. 404 if unknown.",
            call=f"/api/v1/registry/{biz['reg_no']}",
        )

        section("Public: destinations, weather, crowd")
        ep(
            "GET",
            "/api/v1/destinations",
            "none",
            "All 24 destinations with today's crowd estimate.",
            call="/api/v1/destinations?district=rudraprayag",
            params="`district`, `tag`, `q`",
        )
        ep(
            "GET",
            "/api/v1/destinations/{id}",
            "none",
            "Destination page in one call: destination, weather, crowd (today, 14-day outlook, usual by month), roads (facts + road advisories), all active advisories, nearby registered businesses grouped (stays, guides, transport, other), events. Weather may take up to 6 s on a cache miss.",
            call="/api/v1/destinations/kedarnath",
            keep=1,
        )
        ep(
            "GET",
            "/api/v1/destinations/{id}/weather",
            "none",
            'Weather only. Unavailable shape: `{"available": false, "reason": "..."}`.',
            call="/api/v1/destinations/kedarnath/weather",
        )
        ep("GET", "/api/v1/destinations/{id}/crowd", "none", "Crowd estimate only.", call="/api/v1/destinations/kedarnath/crowd", keep=1)
        ep(
            "GET",
            "/api/v1/destinations/{id}/nearby",
            "none",
            "Other curated destinations by straight-line distance from approximate coordinates (`distance_km`), with today's crowd band and cached weather. Not road distance.",
            call="/api/v1/destinations/kedarnath/nearby?limit=3",
            params="`limit` 1-23 (default 6)",
        )

        section("Public: plan (experiences, circuits, sample itineraries, map, official links)")
        ep("GET", "/api/v1/experiences", "none", "The 6 experiences (themes) with destination ids.", keep=6)
        ep(
            "GET",
            "/api/v1/experiences/{id}",
            "none",
            "One experience: intro (our own words), destinations with crowd band and `weather_now` (cache only; null until loaded), related festivals, dictionary terms, itineraries, circuits.",
            call="/api/v1/experiences/spiritual",
            keep=1,
        )
        ep("GET", "/api/v1/circuits", "none", "Circuits as ordered destination lists.", keep=1)
        ep(
            "GET",
            "/api/v1/itineraries",
            "none",
            "Sample multi-stop trips built only from curated destinations. `suggested_days` is a planning suggestion; no distances, times or prices.",
            params="`theme`",
            keep=1,
        )
        ep(
            "GET",
            "/api/v1/itineraries/{id}",
            "none",
            "One sample trip: per stop crowd today (estimate), weather (live, fetched in parallel within a 6 s budget, else cache), worst road advisory; `best_start` = start date in the next 14 days with the lowest average crowd estimate over all trip days.",
            call="/api/v1/itineraries/do-dham",
            keep=2,
        )
        ep(
            "GET",
            "/api/v1/map",
            "none",
            "Points for a schematic dot map (not to scale, no boundaries), with circuits, experiences and districts for filters.",
            keep=1,
        )
        ep("GET", "/api/v1/official-services", "none", "Official external services (open in a new tab; not part of this concept).")
        ep(
            "GET",
            "/api/v1/district-offices",
            "none",
            "District tourism office placeholders: contacts are to be filled by the department.",
            keep=2,
        )

        section("Public: calendar, dictionary, rules, helplines, advisories")
        ep(
            "GET",
            "/api/v1/events",
            "none",
            "Festivals (curated, usual months) and dated officer events. `by_month` maps '1'..'12' to event ids for a month view.",
            call="/api/v1/events?month=10",
            params="`month` (1-12), `district`, `destination`, `q`",
        )
        ep(
            "GET",
            "/api/v1/dictionary",
            "none",
            "Dictionary terms.",
            call="/api/v1/dictionary?letter=R",
            params="`letter`, `category` (exact label from `categories`), `q`",
        )
        ep("GET", "/api/v1/dictionary/{id}", "none", "One term with resolved related terms.", call="/api/v1/dictionary/revpar")
        ep(
            "GET",
            "/api/v1/rules",
            "none",
            "Rules, licences and schemes cards (orientation only).",
            call="/api/v1/rules?business_type=homestay",
            params="`business_type`, `q`",
        )
        ep("GET", "/api/v1/rules/{id}", "none", "One card.", call="/api/v1/rules/form-c")
        ep("GET", "/api/v1/helplines", "none", "Helplines. `number: null` = placeholder to be filled by the department.", keep=6)
        ep(
            "GET",
            "/api/v1/advisories",
            "none",
            "Active advisories, closed first. `sample: true` items are illustrative.",
            call="/api/v1/advisories?district=rudraprayag",
            params="`district`, `destination` (also returns district-wide advisories without a destination), `kind` (road|weather|general)",
        )

        section("Public: grievances")
        SECTIONS[-1][1].append(
            dict(
                method="POST",
                path="/api/v1/grievances",
                auth="none (5/hour/IP)",
                desc="File a grievance. Returns 201 with `ticket_id` and the 6-digit `tracking_code` (shown once; store only on the user's screen).",
                body={
                    "category": "overcharging",
                    "district": "rudraprayag",
                    "business_reg_no": None,
                    "description": "Taxi charged more than the agreed fare.",
                    "contact": "optional, kept private",
                },
                code=201,
                resp=filed,
                call="/api/v1/grievances",
                keep=2,
                params="`category` (see /meta), `district`, `business_reg_no` (optional, format checked), `description` (10-2000), `contact` (optional, officers only)",
            )
        )
        ep(
            "POST",
            "/api/v1/grievances/track",
            "none (20/min/IP)",
            "Track. 404 with a generic message when the ticket or code is wrong. Public timeline shows only public notes.",
            body={"ticket_id": filed["ticket_id"], "tracking_code": filed["tracking_code"]},
        )

        section("Auth")
        ep("GET", "/api/v1/auth/demo-accounts", "none", "Demo accounts for one-click login. Empty list when demo login is off.", keep=3)
        ep(
            "POST",
            "/api/v1/auth/demo/{username}",
            "none (10/min/IP)",
            "One-click demo sign-in. 404 when disabled, in production, or for non-demo usernames.",
            call="/api/v1/auth/demo/demo.officer.rudraprayag",
        )
        ep(
            "POST",
            "/api/v1/auth/register",
            "none (10/min/IP)",
            "Business owner self-registration (role `business`). 201 + session. 409 if the username is taken.",
            body={"username": "my.homestay", "password": "at-least-10-chars"},
            status=201,
        )
        ep(
            "POST",
            "/api/v1/auth/login",
            "none (10/min per IP and per username)",
            "Password sign-in. 401 `Wrong username or password.`; 5 failures lock the account for 5 minutes.",
            body={"username": "my.homestay", "password": "at-least-10-chars"},
        )
        sess = c.post("/api/v1/auth/login", json={"username": "my.homestay", "password": "at-least-10-chars"}).json()
        ep(
            "POST",
            "/api/v1/auth/refresh",
            "none",
            "Rotate: returns a new access token AND a new refresh token; the old refresh token stops working.",
            body={"refresh_token": sess["refresh_token"]},
        )
        ep("GET", "/api/v1/auth/me", "any signed-in", "Current user.", headers=officer)
        sess2 = c.post("/api/v1/auth/login", json={"username": "my.homestay", "password": "at-least-10-chars"}).json()
        ep(
            "POST",
            "/api/v1/auth/logout",
            "none",
            "Revoke a refresh token. 204, empty body.",
            body={"refresh_token": sess2["refresh_token"]},
            status=204,
        )

        section("Business owner (role `business`)")
        ep(
            "GET",
            "/api/v1/business/dashboard",
            "business",
            "Everything for the dashboard: own businesses, own applications, summary counts.",
            headers=owner,
            keep=1,
        )
        ep("GET", "/api/v1/business/businesses", "business", "Own businesses with renewal info.", headers=owner, keep=1)
        ep(
            "GET",
            "/api/v1/business/businesses/{id}",
            "business (owner)",
            "One own business; stays include `occupancy_months` (last 12).",
            call=f"/api/v1/business/businesses/{stay['id']}",
            headers=owner,
            keep=2,
        )
        ep(
            "POST",
            "/api/v1/business/businesses/{id}/occupancy",
            "business (owner)",
            "Monthly occupancy form. Spreads `occupied_room_nights` evenly across the month's days (to today for the current month), skipping days already reported by HOI ingest. 422 for future months, capacity overflow, or nights > rooms x days.",
            call=f"/api/v1/business/businesses/{stay['id']}/occupancy",
            body={"month": prev_month, "rooms_available": min(4, stay["capacity"]), "occupied_room_nights": 60},
            headers=owner,
        )
        ep(
            "GET",
            "/api/v1/business/businesses/{id}/occupancy",
            "business (owner)",
            "Monthly occupancy history (24 months). `sources`: s=seed, m=monthly form, i=HOI ingest.",
            call=f"/api/v1/business/businesses/{stay['id']}/occupancy",
            headers=owner,
        )
        SECTIONS[-1][1].append(
            dict(
                method="POST",
                path="/api/v1/business/businesses/{id}/api-keys",
                auth="business (owner, stays only)",
                desc="Create an ingest API key. `api_key` is returned ONCE; only its SHA-256 is stored. Max 3 active keys per business (409).",
                body={"label": "HOI ingest"},
                code=201,
                resp=key,
                call="/api/v1/business/businesses/{id}/api-keys",
                params=None,
                keep=2,
            )
        )
        ep(
            "GET",
            "/api/v1/business/businesses/{id}/api-keys",
            "business (owner)",
            "List keys (prefix only, never the key).",
            call=f"/api/v1/business/businesses/{stay['id']}/api-keys",
            headers=owner,
        )
        ep(
            "POST",
            "/api/v1/business/businesses/{id}/renew",
            "business (owner)",
            "Start a renewal (opens 60 days before expiry, or after expiry). 409 if too early or one is already open; 403 if suspended. An expired business shows `pending` while under review.",
            call=f"/api/v1/business/businesses/{due['id']}/renew",
            headers=owner,
            status=201,
        )
        ep(
            "POST",
            "/api/v1/business/applications",
            "business",
            "New registration application (no file upload; documents are checklist ticks). Unknown languages are dropped.",
            body={
                "business_name": "My Sample Homestay, Chopta",
                "type": "homestay",
                "district": "rudraprayag",
                "destination_id": "chopta",
                "capacity": 4,
                "beds": 8,
                "languages": ["Hindi", "English", "Garhwali"],
                "documents": {"identity_proof": True, "address_proof": True, "property_papers": False},
                "notes": "Two family rooms",
            },
            headers=owner,
            status=201,
        )
        ep("GET", "/api/v1/business/applications", "business", "Own applications, newest first.", headers=owner, keep=1)
        own_app = c.get("/api/v1/business/applications", headers=owner).json()["items"]
        cr = next(a for a in own_app if a["status"] == "changes_requested")
        ep(
            "GET",
            "/api/v1/business/applications/{id}",
            "business (owner)",
            "One own application.",
            call=f"/api/v1/business/applications/{cr['id']}",
            headers=owner,
        )
        ep(
            "PUT",
            "/api/v1/business/applications/{id}",
            "business (owner)",
            "Edit an application in `changes_requested` and resubmit it (status back to `submitted`). Send only the fields to change. 409 in other states.",
            call=f"/api/v1/business/applications/{cr['id']}",
            body={"documents": {k: True for k in cr["required_documents"]}},
            headers=owner,
        )
        ep(
            "DELETE",
            "/api/v1/business/businesses/{id}/api-keys/{key_id}",
            "business (owner)",
            "Revoke a key (kept, `revoked: true`).",
            call=f"/api/v1/business/businesses/{stay['id']}/api-keys/{key['id']}",
            headers=owner,
        )
        key2 = c.post(f"/api/v1/business/businesses/{stay['id']}/api-keys", json={}, headers=owner).json()

        section("HOI ingest (API key)")
        ep(
            "POST",
            "/api/v1/ingest/occupancy",
            "`X-API-Key: uthp_...` (120/min/IP)",
            "Daily occupancy from HOI-run stays. Idempotent per (business, date): `result` is `created`, `replaced` or `unchanged`. 401 for a missing/wrong/revoked key; 403 if the registration is not active; 422 for future dates, > 400 days old, rooms_available > capacity, occupied > available, staff_flagged > staff_count.",
            body={
                "date": (date.today() - timedelta(days=1)).isoformat(),
                "rooms_available": min(4, stay["capacity"]),
                "rooms_occupied": 3,
                "staff_count": 7,
                "staff_flagged": 1,
            },
            headers={"X-API-Key": key2["api_key"]},
        )

        section("Officials: applications (district_officer scoped, state_admin all)")
        ep(
            "GET",
            "/api/v1/officer/applications",
            "district_officer / state_admin",
            "Queue, oldest first. `counts` per status in scope.",
            call="/api/v1/officer/applications?status=submitted",
            params="`district` (admin; officer may only pass own), `status`, `kind` (new|renewal), `page`, `page_size`",
            headers=officer,
            keep=1,
        )
        ep(
            "GET",
            "/api/v1/officer/applications/{id}",
            "official",
            "One application (404 outside the officer's district).",
            call=f"/api/v1/officer/applications/{app_rud['id']}",
            headers=officer,
        )
        ep(
            "POST",
            "/api/v1/officer/applications/{id}/decision",
            "official",
            "`action`: approve | request_changes | reject. `reason` required unless approving. Approve needs every required document ticked (422) and issues `reg_no` UK-<TYPE>-<DISTRICT>-<NNNNN> (new) or extends `valid_until` by a year (renewal). 409 if not `submitted`.",
            call=f"/api/v1/officer/applications/{app_rud['id']}/decision",
            body={"action": "approve", "reason": None},
            headers=officer,
        )

        section("Officials: grievances")
        ep(
            "GET",
            "/api/v1/officer/grievances",
            "official",
            "Grievances with private details. Also returns `open` and `overdue` counts.",
            call="/api/v1/officer/grievances?status=open",
            params="`district`, `status` (a status or `open`), `overdue` (true|false), `category`, `page`, `page_size`",
            headers=officer,
            keep=1,
        )
        ep(
            "GET",
            "/api/v1/officer/grievances/{ticket_id}",
            "official",
            "One grievance incl. description and contact.",
            call=f"/api/v1/officer/grievances/{g_rud['ticket_id']}",
            headers=officer,
        )
        ep(
            "POST",
            "/api/v1/officer/grievances/{ticket_id}",
            "official",
            "Update: any of `status`, `note`, `public` (default true; false = internal note), `assign_to`. Transitions: received->assigned|in_progress|resolved|closed, assigned->in_progress|resolved|closed, in_progress->resolved|closed, resolved->closed|in_progress. Resolving/closing needs a note. 409 for an invalid transition.",
            call=f"/api/v1/officer/grievances/{filed['ticket_id']}",
            body={"status": "in_progress", "note": "Contacted the operator.", "public": True},
            headers=officer,
        )

        section("Officials: advisories and events")
        ep("GET", "/api/v1/officer/advisories", "official", "All advisories in scope incl. expired (max 200).", headers=officer, keep=1)
        adv_body = {
            "kind": "road",
            "status": "caution",
            "title": "Caution near Gaurikund",
            "segment": "Gaurikund approach",
            "reason": "Slow traffic",
            "destination_id": "kedarnath",
            "expires_at": (mongo.now() + timedelta(days=2)).isoformat().replace("+00:00", "Z"),
        }
        ep(
            "POST",
            "/api/v1/officer/advisories",
            "official",
            "Post an advisory. Officers post for their own district (403 for another); state admin must pass `district`. Road advisories need `status`. `expires_at` default +3 days, max +60 days.",
            body=adv_body,
            headers=officer,
            status=201,
        )
        adv_id = d.advisories.find_one({"title": "Caution near Gaurikund"})["id"]
        ep(
            "PATCH",
            "/api/v1/officer/advisories/{id}",
            "official",
            "Update fields.",
            call=f"/api/v1/officer/advisories/{adv_id}",
            body={"status": "closed", "reason": "Road closed for clearance"},
            headers=officer,
        )
        ep(
            "DELETE",
            "/api/v1/officer/advisories/{id}",
            "official",
            "Withdraw now (sets `expires_at` to now; record kept).",
            call=f"/api/v1/officer/advisories/{adv_id}",
            headers=officer,
        )
        ev_body = {
            "name": "Trail clean-up drive",
            "description": "Volunteers welcome.",
            "start_date": (date.today() + timedelta(days=20)).isoformat(),
            "end_date": (date.today() + timedelta(days=21)).isoformat(),
            "destination_ids": ["chopta"],
            "crowd_impact": "low",
        }
        ep(
            "POST",
            "/api/v1/officer/events",
            "official",
            "Post a dated event (feeds the calendar and crowd estimate). State admin passes `district`.",
            body=ev_body,
            headers=officer,
            status=201,
        )
        ev_id = d.events.find_one({"name": "Trail clean-up drive"})["id"]
        ep(
            "GET",
            "/api/v1/officer/events",
            "official",
            "Officer-posted events in scope (curated festivals are not editable).",
            headers=officer,
            keep=1,
        )
        ep(
            "PATCH",
            "/api/v1/officer/events/{id}",
            "official",
            "Update fields.",
            call=f"/api/v1/officer/events/{ev_id}",
            body={"crowd_impact": "medium"},
            headers=officer,
        )
        ep(
            "DELETE",
            "/api/v1/officer/events/{id}",
            "official",
            "Delete. 204.",
            call=f"/api/v1/officer/events/{ev_id}",
            headers=officer,
            status=204,
        )

        section("Officials: businesses")
        ep(
            "GET",
            "/api/v1/officer/businesses",
            "official",
            "Registry view in scope (same shape as /registry).",
            call="/api/v1/officer/businesses?status=expired&page_size=1",
            params="`district`, `status`, `type`, `q`, `page`, `page_size`",
            headers=officer,
        )
        ep(
            "POST",
            "/api/v1/officer/businesses/{id}/status",
            "official",
            "Suspend or reinstate (`active` only from `suspended`).",
            call=f"/api/v1/officer/businesses/{biz['id']}/status",
            body={"status": "suspended", "reason": "Safety inspection pending"},
            headers=officer,
        )

        section("Analytics (official; officer = own district, admin = state or `?district=`)")
        ep(
            "GET",
            "/api/v1/analytics/kpis",
            "official",
            "KPI tiles + businesses by status + crowd alerts (outlook >= 85 within 14 days).",
            headers=admin,
            keep=8,
        )
        ep(
            "GET",
            "/api/v1/analytics/rush",
            "official",
            "Heatmap destination x week (8 past + current + 7 outlook weeks, weekly mean index), top busiest (next 14 days), daily alerts >= 85.",
            params="`district`, `top` (1-24, default 10)",
            headers=admin,
            keep=2,
        )
        ep(
            "GET",
            "/api/v1/analytics/occupancy",
            "official",
            "Occupancy % trend: overall, by district, by stay type. `values[i]` belongs to `dates[i]` (bucket start); null = no data.",
            call="/api/v1/analytics/occupancy?granularity=monthly&days=365",
            params="`district`, `type` (hotel|homestay), `days` (7-730, default 365), `granularity` (daily|weekly|monthly)",
            headers=admin,
            keep=2,
        )
        ep(
            "GET",
            "/api/v1/analytics/market",
            "official",
            "SYNTHETIC tourist arrivals and registrations by year (2019-2026) and district with YoY %. Current year is partial (no YoY).",
            headers=admin,
            keep=2,
        )
        ep(
            "GET",
            "/api/v1/analytics/registrations",
            "official",
            "New registrations and applications submitted per month.",
            call="/api/v1/analytics/registrations?months=12",
            params="`district`, `months` (1-60, default 24)",
            headers=admin,
        )
        ep(
            "GET",
            "/api/v1/analytics/grievances",
            "official",
            "Grievances by category, district and status; SLA breach rate; median resolution days.",
            headers=admin,
            keep=3,
        )
        ep(
            "GET",
            "/api/v1/analytics/workforce",
            "official",
            "HOI workforce aggregates for the latest complete month, k-anonymity: a group with fewer than 5 contributing businesses is suppressed with a reason (no numbers).",
            call="/api/v1/analytics/workforce?group_by=district",
            params="`district`, `group_by` (district|type)",
            headers=admin,
            keep=13,
        )

        # ---- hiring board
        seeker = c.post(
            "/api/v1/auth/register", json={"username": "doc.seeker", "password": "at-least-10-chars", "role": "job_seeker"}
        ).json()
        sk = {"Authorization": "Bearer " + seeker["access_token"]}
        demo_seeker = tok("demo.seeker")
        own_biz = c.get("/api/v1/jobs/mine", headers=owner).json()["active_businesses"][0]
        soon = (date.today() + timedelta(days=40)).isoformat()
        later = (date.today() + timedelta(days=150)).isoformat()
        profile_body = {
            "display_name": "Meena",
            "headline": "Cook for pahadi food, 6 years",
            "skills": [{"key": "cook_pahadi", "years": 6}, {"key": "kitchen_helper", "years": 2}],
            "certifications": ["Food safety training"],
            "languages": ["Hindi", "Garhwali"],
            "districts": ["rudraprayag", "chamoli"],
            "availability": "seasonal",
            "available_from": soon,
            "available_to": later,
            "pay_min": 14000,
            "pay_max": 18000,
            "bio": "Cooked for pilgrim groups.",
            "visibility": "public",
            "phone": "+91 90000 00000",
            "email": None,
            "consent": True,
        }

        section("Hiring board: public job board")
        ep(
            "GET",
            "/api/v1/jobs/meta",
            "none",
            "Vocabularies: skills taxonomy with categories, job types, languages, certificate suggestions, statuses, the consent notice text and the ASSUMED match weights.",
            keep=3,
        )
        ep(
            "GET",
            "/api/v1/jobs",
            "none (optional bearer: a job seeker with a profile gets `match` per job, sorted by it, and `applied`)",
            "Open jobs (status open and `closes_on` >= today), newest first. `openings` = total openings in the result.",
            call="/api/v1/jobs?district=rudraprayag&page_size=2",
            params="`skill`, `district`, `type` (seasonal|permanent|part_time), `month` (1-12, season covers it), `q` (title, business, district, skill), `page`, `page_size` (1-50, default 12)",
            keep=1,
        )
        ep(
            "GET",
            "/api/v1/jobs",
            "job_seeker (optional)",
            "Same list with `match` (score 0-100 or null, `parts`, `why` chips, `basis`).",
            call="/api/v1/jobs?page_size=1",
            headers=demo_seeker,
            keep=1,
        )
        any_job = c.get("/api/v1/jobs", params={"page_size": 1}).json()["items"][0]
        ep(
            "GET",
            "/api/v1/jobs/{id}",
            "none (optional bearer)",
            "One job. Seekers also get `has_profile`, `match`, `my_application`; the owning business gets application counts.",
            call=f"/api/v1/jobs/{any_job['id']}",
        )

        section("Hiring board: job seeker (role `job_seeker`)")
        ep(
            "POST",
            "/api/v1/auth/register",
            "none (10/min/IP)",
            "Job seekers register with `role: job_seeker` (default `business`).",
            body={"username": "my.name", "password": "at-least-10-chars", "role": "job_seeker"},
            status=201,
        )
        ep(
            "GET",
            "/api/v1/me/seeker/profile",
            "job_seeker",
            "Own profile (incl. private phone/email) or `null`, plus the consent notice to show before creating one.",
            headers=sk,
        )
        ep(
            "POST",
            "/api/v1/me/seeker/profile",
            "job_seeker (5/hour per user, 20/hour per IP)",
            "Create the profile. `consent: true` required (422 otherwise); phone or email required. Sending gender, age/date_of_birth, religion, caste, marital_status, photo, address (and similar) is rejected with 422 `This portal does not collect ...`. 409 if one exists.",
            body=profile_body,
            headers=sk,
            status=201,
        )
        ep(
            "PATCH",
            "/api/v1/me/seeker/profile",
            "job_seeker",
            "Update any fields, incl. `visibility` public|hidden. Same validation; protected fields rejected.",
            body={"headline": "Head cook, pahadi thali", "visibility": "public"},
            headers=sk,
        )
        ep("GET", "/api/v1/me/seeker", "job_seeker", "Dashboard: profile, counts, applications by status.", headers=demo_seeker)
        ep(
            "POST",
            "/api/v1/jobs/{id}/apply",
            "job_seeker (20/day)",
            "Apply with an optional note (<= 500). 409 without a profile, for a closed job or a second application.",
            call=f"/api/v1/jobs/{any_job['id']}/apply",
            body={"note": "Available from next week."},
            headers=sk,
            status=201,
        )
        my_app = c.get("/api/v1/me/seeker/applications", headers=sk).json()["items"][0]
        ep(
            "GET",
            "/api/v1/me/seeker/applications",
            "job_seeker",
            "Own applications with job, status and `history` (applied -> viewed -> shortlisted -> contacted / not_selected; withdrawn).",
            headers=demo_seeker,
            keep=1,
        )
        ep(
            "GET",
            "/api/v1/me/seeker/interests",
            "job_seeker",
            "Interest requests from businesses. `pending` = awaiting the seeker.",
            headers=demo_seeker,
            keep=1,
        )
        pend = next(i for i in c.get("/api/v1/me/seeker/interests", headers=demo_seeker).json()["items"] if i["status"] == "pending")
        ep(
            "POST",
            "/api/v1/me/seeker/interests/{id}",
            "job_seeker",
            "`action`: accept | decline. Accepting reveals phone/email to THAT business only. 409 if already answered.",
            call=f"/api/v1/me/seeker/interests/{pend['id']}",
            body={"action": "accept"},
            headers=demo_seeker,
        )
        ep(
            "POST",
            "/api/v1/me/seeker/applications/{id}/withdraw",
            "job_seeker",
            "Withdraw an application (409 if already withdrawn).",
            call=f"/api/v1/me/seeker/applications/{my_app['id']}/withdraw",
            headers=sk,
        )

        section("Hiring board: business (role `business`, ACTIVE registration required to post, search and send requests)")
        ep(
            "GET",
            "/api/v1/jobs/mine",
            "business",
            "Own job posts with application counts, `can_hire`, `active_businesses`, summary.",
            headers=owner,
            keep=1,
        )
        job_body = {
            "business_id": own_biz["id"],
            "title": "Cook for the winter season",
            "skills": ["cook_pahadi", "kitchen_helper"],
            "district": None,
            "destination_id": None,
            "job_type": "seasonal",
            "season_from": soon,
            "season_to": later,
            "pay_min": 15000,
            "pay_max": 19000,
            "accommodation": True,
            "food": True,
            "openings": 2,
            "languages": ["Hindi", "Garhwali"],
            "description": "Cook pahadi and simple Indian meals for homestay guests.",
            "closes_on": (date.today() + timedelta(days=30)).isoformat(),
        }
        ep(
            "POST",
            "/api/v1/jobs",
            "business (20/day)",
            "Post a job. 403 unless `business_id` is an own business with an ACTIVE registration. Seasonal jobs need season dates; `closes_on` within 180 days; description <= 1000; max 20 open posts.",
            body=job_body,
            headers=owner,
            status=201,
        )
        new_job = c.get("/api/v1/jobs/mine", headers=owner).json()["items"][0]
        c.post(f"/api/v1/jobs/{new_job['id']}/apply", json={}, headers=sk)
        ep(
            "GET",
            "/api/v1/jobs/{id}/applications",
            "business (owner)",
            "Applicants, best match first, with public candidate fields, `match`, `next_statuses`. Listing marks `applied` as `viewed`. `contact` only for candidates who accepted this business's request.",
            call=f"/api/v1/jobs/{new_job['id']}/applications",
            headers=owner,
            keep=1,
        )
        app_id = c.get(f"/api/v1/jobs/{new_job['id']}/applications", headers=owner).json()["items"][0]["id"]
        ep(
            "POST",
            "/api/v1/jobs/applications/{id}/status",
            "business (owner)",
            "`status`: viewed | shortlisted | contacted | not_selected (409 for an invalid transition).",
            call=f"/api/v1/jobs/applications/{app_id}/status",
            body={"status": "shortlisted"},
            headers=owner,
        )
        ep(
            "PATCH",
            "/api/v1/jobs/{id}",
            "business (owner)",
            "Close (`status: closed`, `closed_reason` filled|withdrawn), reopen, or change `closes_on`, `openings`, `description`.",
            call=f"/api/v1/jobs/{new_job['id']}",
            body={"openings": 3},
            headers=owner,
        )
        ep(
            "GET",
            "/api/v1/candidates",
            "business (active registration)",
            "Search public profiles. Never returns contact details (not even after acceptance). Sorted by match score against the filters or `job_id`.",
            call="/api/v1/candidates?skill=cook_pahadi&district=rudraprayag&page_size=2",
            params="`skill`, `district` (preferred or any), `available_from`, `available_to`, `exp_min` (years in the skill), `language`, `job_id` (own post), `page`, `page_size` (default 12)",
            headers=owner,
            keep=1,
        )
        doc_code = c.get("/api/v1/me/seeker/profile", headers=sk).json()["profile"]["code"]
        ep(
            "GET",
            "/api/v1/candidates/{code}",
            "business (active registration)",
            "One candidate (404 for hidden profiles without a relation). `contact` is null until the candidate accepts this business's interest request.",
            call=f"/api/v1/candidates/{doc_code}",
            headers=owner,
        )
        ep(
            "POST",
            "/api/v1/candidates/{code}/interest",
            "business (40/day)",
            "Send an interest request (one per business owner and candidate; 409 on repeat).",
            call=f"/api/v1/candidates/{doc_code}/interest",
            body={"job_id": new_job["id"], "message": "We liked your profile. Would you like to talk?"},
            headers=owner,
            status=201,
        )
        ep(
            "GET",
            "/api/v1/candidates/interests",
            "business",
            "Sent requests with status; accepted ones include the candidate's `contact`.",
            headers=owner,
            keep=1,
        )
        ep(
            "PUT",
            "/api/v1/candidates/{code}/shortlist",
            "business (active registration)",
            "Add to shortlist (idempotent). `DELETE` removes.",
            call=f"/api/v1/candidates/{doc_code}/shortlist",
            headers=owner,
        )
        ep("GET", "/api/v1/candidates/shortlist", "business", "Shortlisted candidates.", headers=owner, keep=1)

        section("Hiring board: message threads (the two parties only)")
        ep(
            "POST",
            "/api/v1/jobs/threads/{id}",
            "job_seeker or business party (30/hour)",
            "Post a text message (1-1000 chars). Thread id = application id (`JA-...`) or interest id (`INT-...`, only once accepted). Anyone else gets 404; officials 403.",
            call=f"/api/v1/jobs/threads/{app_id}",
            body={"text": "When does the season start?"},
            headers=sk,
            status=201,
        )
        ep(
            "GET",
            "/api/v1/jobs/threads/{id}",
            "job_seeker or business party",
            "Thread meta + messages (oldest first, max 300).",
            call=f"/api/v1/jobs/threads/{app_id}",
            headers=owner,
        )
        ep(
            "DELETE",
            "/api/v1/me/seeker/profile",
            "job_seeker",
            "Hard delete: profile, applications, interest requests, shortlist entries and messages. Audit entry keeps only the pseudonymous user id and code.",
            headers=sk,
        )

        section("Analytics: workforce market (official, aggregates only)")
        ep(
            "GET",
            "/api/v1/analytics/workforce-market",
            "official (officer = own district)",
            "Open openings vs visible candidates by skill and district, seasonal demand vs supply by month, time to fill. Candidate counts below 5 are null with `suppressed: true` (k-anonymity). SYNTHETIC.",
            headers=admin,
            keep=3,
        )

        section("State admin")
        ep(
            "GET",
            "/api/v1/admin/users",
            "state_admin",
            "Accounts.",
            call="/api/v1/admin/users?role=district_officer",
            params="`role`",
            headers=admin,
        )
        ep(
            "POST",
            "/api/v1/admin/officers",
            "state_admin",
            "Create a district officer.",
            body={
                "username": "officer.chamoli",
                "password": "a-strong-password",
                "district": "chamoli",
                "label": "District tourism officer, Chamoli",
            },
            headers=admin,
            status=201,
        )
        ep(
            "PATCH",
            "/api/v1/admin/users/{id}",
            "state_admin",
            "Enable/disable an account (disabling revokes sessions; tokens stop working at once). 409 for your own account.",
            call=f"/api/v1/admin/users/{users['sample.applicant.05']}",
            body={"active": False},
            headers=admin,
        )
        ep(
            "GET",
            "/api/v1/admin/audit",
            "state_admin",
            "Audit log, newest first.",
            call="/api/v1/admin/audit?limit=2",
            params="`limit` (1-500), `district`",
            headers=admin,
        )

        # ---- execute and render
        lines = [HEADER.rstrip(), "", "## 9. Endpoints", ""]
        n = 0
        for title, eps in SECTIONS:
            lines += [f"### {title}", ""]
            for e in eps:
                n += 1
                resp, code = e["resp"], e["code"]
                lines.append(f"#### `{e['method']} {e['path']}`")
                lines.append("")
                lines.append(f"Auth: {e['auth']}. {e['desc']}")
                if e.get("params"):
                    lines.append("")
                    lines.append(f"Query/body fields: {e['params']}")
                lines.append("")
                if e["call"] != e["path"]:
                    lines.append(f"Example: `{e['method']} {e['call']}` -> {code}")
                else:
                    lines.append(f"Example -> {code}")
                if e.get("body") is not None:
                    lines += ["", "Request body:", "```json", json.dumps(e["body"], indent=1, ensure_ascii=False), "```"]
                if resp is not None:
                    lines += [
                        "",
                        "Response (abbreviated):",
                        "```json",
                        json.dumps(abbreviate(resp, list_keep=e["keep"]), indent=1, ensure_ascii=False),
                        "```",
                    ]
                lines.append("")
        lines.append(
            f"_{n} endpoints documented. Generated by `portal/scripts/gen_api_doc.py` on {date.today().isoformat()} from the app running on mongomock._"
        )
        OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {OUT} ({n} endpoints)")


if __name__ == "__main__":
    run()
