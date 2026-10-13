# UTHP API contract (`hoi_portal`)

Uttarakhand Tourism & Hospitality Portal (concept), short name **UTHP**. Concept prototype for the AI-Tourism
Hackathon 2026, **not an official Government of Uttarakhand website**. Data is sample/synthetic unless marked otherwise.

This file is the contract for the web frontend. Section 9 is generated from real responses of the running app
(mongomock, synthetic seed) by `portal/scripts/gen_api_doc.py`; examples are abbreviated (`"... N more"` marks cut
lists, long strings end in `...`). Ids, registration numbers, dates and numbers in examples will differ per seed date.

## 1. Basics

- Service: FastAPI app `hoi_portal.main:app`, port **8200**. The web app is served by the same server from `/`
  (static files in `portal/hoi_portal/static/`), so the frontend calls the API **same-origin** with relative URLs
  such as `/api/v1/meta`. No CORS setup is needed for the bundled frontend.
- All endpoints are under `/api/v1` except `GET /health` and `GET /ready`. JSON in, JSON out (UTF-8).
- Timestamps: ISO 8601 UTC with `Z` (e.g. `2026-10-13T06:30:00.123Z`). Dates: `YYYY-MM-DD`. Months: `YYYY-MM`.
  Month numbers in calendars: 1-12.
- Never any `_id` in responses. Ids are strings (`biz_0001`, `APP-000021`, `UTHP-G-000041`, `adv_...`, `evt_...`,
  `usr_...`, `key_...`). Destination and district ids are slugs (`kedarnath`, `pauri-garhwal`).
- Lists return `{"items": [...], "total": n, ...}`. Paged lists also return `page` and `page_size` (`page` starts at 1).
- Synthetic labelling: business records carry `synthetic: true`; every analytics response carries
  `"synthetic": true` and `"note": "SYNTHETIC data ... Not official statistics."`. Show it. Sample advisories/events
  carry `sample: true` and titles starting `SAMPLE:`.
- Approximate facts: destinations carry `facts_note` ("Approximate, verify ..."), rules cards carry `verify_note`,
  festivals carry `date_note`, crowd data carries `label: "estimate"` and a `note`. Show these next to the content.
- `altitude_m` is always `null` for now (not in the curated reference set); show `altitude_note` or hide the field.

## 2. Roles

| Role | How to get it | Scope |
|---|---|---|
| (public) | no token | public endpoints only |
| `business` | `POST /auth/register` or demo `demo.business` | own businesses and applications |
| `district_officer` | created by state admin; demo `demo.officer.rudraprayag` | **one district** (from the account, never from the client) |
| `state_admin` | `admin` (password from env `PORTAL_ADMIN_PASSWORD`) or demo `demo.admin` | all districts |

District scoping for officers: list/analytics endpoints accept `?district=`; an officer may omit it or pass their
own district, anything else is **403** `You can only see your own district.`. Fetching or changing a single item from
another district is **404**. The state admin may pass any district or none (= whole state).

## 3. Sessions and tokens

- Sign-in endpoints return a session:
  ```json
  {"access_token": "<JWT>", "token_type": "bearer", "expires_in": 1800, "refresh_token": "<opaque>", "user": {...}}
  ```
- Send `Authorization: Bearer <access_token>` on every signed-in call. The access token lives **30 minutes**
  (`expires_in` seconds). Keep it in memory (or `sessionStorage`); do not put tokens in URLs.
- When a call returns **401** (or shortly before `expires_in` runs out) call `POST /api/v1/auth/refresh` with
  `{"refresh_token": ...}`. The response is a full new session: **replace both tokens**. The refresh token is rotated
  on every use and lives 14 days; presenting an already-used refresh token revokes all of the user's sessions
  (theft detection), so never send the same refresh token twice (serialize refreshes in the client).
- Sign out: `POST /api/v1/auth/logout` with `{"refresh_token": ...}` (204), then drop both tokens.
- The account is re-checked on every request: disabling a user makes their access token fail immediately (401).
- `user` object: `{id, username, role, role_label, district, district_name, label, active, created_at, last_login}`.

### Demo login flow (development and demos only)

1. `GET /api/v1/auth/demo-accounts` -> list of `{username, role, district, label, description}`. An **empty list**
   means demo login is off (always off in production): hide the demo buttons.
2. `POST /api/v1/auth/demo/{username}` (no body) -> session (same shape as login). 404 when disabled.
3. Demo accounts: `demo.admin` (state admin), `demo.officer.rudraprayag` (district officer, Rudraprayag),
   `demo.business` (owns a Kedarnath homestay and a Rudraprayag hotel whose registration is due for renewal, plus
   one submitted and one changes-requested application).

## 4. Errors

Every error is JSON with a human-readable `detail` string, safe to show to the user:

```json
{"detail": "Application is approved; only submitted applications can be decided."}
```

| Status | Meaning |
|---|---|
| 400 | Bad request |
| 401 | Not signed in, session expired/invalid, wrong API key (`detail` says which) |
| 403 | Signed in but not allowed (role, other district, suspended registration) |
| 404 | Not found (also: item outside your district; wrong grievance ticket/code; unknown `/api/...` path) |
| 409 | Conflict with current state (already decided, duplicate username, renewal not open yet, invalid transition) |
| 422 | Validation. Body/query schema errors add an `errors` list: `{"detail": "Some fields are missing or invalid.", "errors": [{"field": "description", "message": "String should have at least 10 characters"}]}`. Business-rule 422s have only `detail`. Unknown body fields are rejected. |
| 429 | Rate limited. `Retry-After` header (seconds). |
| 500 | `{"detail": "Internal error. Reference: <request id>"}` |
| 503 | `/ready` only: database unreachable |

Every response has an `X-Request-ID` header (send your own `X-Request-ID` to correlate).

## 5. Rate limits (per client IP, sliding window, single process)

| What | Limit |
|---|---|
| `POST /auth/login` | 10/min per IP and 10/min per username |
| `POST /auth/register`, `/auth/refresh`, `/auth/demo/{u}` | 10/min per IP each |
| `POST /grievances` (file) | 5/hour per IP |
| `POST /grievances/track` | 20/min per IP |
| `GET /registry/verify` | 60/min per IP |
| `GET /search` | 60/min per IP |
| `POST /ingest/occupancy` | 120/min per IP |

Limits are configurable (`PORTAL_*_RATE_*` env vars). Debounce search-as-you-type (300 ms+).

## 6. Security headers the frontend must live with

All responses carry this Content-Security-Policy:

```
default-src 'self'; img-src 'self' data:; connect-src 'self';
style-src 'self' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com;
script-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'
```

So: no inline `<script>`, no `onclick=` attributes, no `style="..."` attributes or `<style>` blocks (put CSS in
files; set dynamic styles through the DOM, e.g. `el.style.width = ...`), no third-party scripts, API calls only to
the same origin. Google Fonts (Inter Tight) is allowed. Also: `X-Frame-Options: DENY`, `nosniff`,
`Referrer-Policy: no-referrer`, `Cache-Control: no-store` on `/api/*`.

## 7. Domain notes for the UI

- **Crowd bands** (from `/meta` `crowd_bands`): low < 40, moderate 40-64, high 65-84, very_high >= 85. Index 0-100.
  `basis` per day: `reported` (real reported occupancy), `estimate`, or `seasonal pattern`. Always label "estimate".
  Usual-by-month: 12 entries, `month` 1-12.
- **Weather**: `available: false` + `reason` when Open-Meteo fails; show "live weather unavailable". `warnings` are
  plain-language heavy rain / snow messages (thresholds are ASSUMED, in `thresholds`). `cached`/`stale` flags and
  `fetched_at` let you show "updated N min ago". Source attribution: `source`.
- **Registration number**: `UK-<TYPE>-<DISTRICT>-<NNNNN>`, type and district codes in `/meta` (prototype codes).
- **Business status**: active | expired | suspended | pending (renewal under review). `verified` is only ever true
  for active businesses. `contact` is a placeholder sentence.
- **Grievance**: SLA 7 days (ASSUMED) -> `sla_due_at`, `overdue`. Status chain received -> assigned -> in_progress ->
  resolved / closed. The tracking code is shown once at filing; the public never sees `contact` or `description`.
- **Applications**: statuses submitted | changes_requested | approved | rejected; kinds new | renewal.
  `required_documents` and `missing_documents` drive the checklist UI (labels in `/meta.documents_checklist`).
- **Analytics charts**: series are `{key, label, values[]}` aligned with a sibling axis array (`dates`, `weeks`,
  `months`, `years`). `null` values = no data (draw a gap). Workforce groups with `suppressed: true` have only
  `reason` and must be shown as "hidden (fewer than 5 businesses)".
- **Rules/helplines**: `number: null` means "to be filled by the department"; never fill in a number.

## 8. Environment (server)

`MONGODB_URI` (unset or `mongomock://` = in-memory dev DB), `HOI_PORTAL_DB` (default `hoi_portal`), `HOI_ENV`
(`production` turns on the guard), `PORTAL_JWT_SECRET`, `PORTAL_ADMIN_PASSWORD`, `PORTAL_DEMO_LOGIN`,
`PORTAL_SEED_DEMO`, `PORTAL_CORS_ORIGINS`, `PORTAL_WEATHER_ENABLED`, `PORTAL_ACCESS_TTL_MINUTES` (30),
`PORTAL_REFRESH_TTL_DAYS` (14), rate-limit variables. See `portal/README.md`.

## 9. Endpoints

### Meta

#### `GET /health`

Auth: none. Liveness.

Example -> 200

Response (abbreviated):
```json
{
 "status": "ok",
 "service": "hoi-portal",
 "version": "0.1.0",
 "env": "development",
 "demo_login": true
}
```

#### `GET /ready`

Auth: none. Readiness (pings MongoDB). 503 when the database is unreachable.

Example -> 200

Response (abbreviated):
```json
{
 "status": "ready"
}
```

### Public: reference and search

#### `GET /api/v1/meta`

Auth: none. Vocabularies for forms and filters: districts, destinations, business types, checklist, categories, bands.

Example -> 200

Response (abbreviated):
```json
{
 "service": "Uttarakhand Tourism & Hospitality Portal (concept)",
 "banner": "Concept prototype for the AI-Tourism Hackathon 2026, not an official Government of Uttarakhand website. Data is sample/synthetic unless m...",
 "districts": [
  {
   "id": "almora",
   "name": "Almora",
   "code": "ALM",
   "division": "Kumaon"
  },
  {
   "id": "bageshwar",
   "name": "Bageshwar",
   "code": "BAG",
   "division": "Kumaon"
  },
  "... 11 more"
 ],
 "destinations": [
  {
   "id": "kedarnath",
   "name": "Kedarnath",
   "district": "rudraprayag"
  },
  {
   "id": "badrinath",
   "name": "Badrinath",
   "district": "chamoli"
  },
  "... 22 more"
 ],
 "business_types": [
  {
   "key": "hotel",
   "label": "Hotel",
   "code": "HTL",
   "capacity_unit": "rooms"
  },
  {
   "key": "homestay",
   "label": "Homestay",
   "code": "HMS",
   "capacity_unit": "rooms"
  },
  "... 6 more"
 ],
 "business_statuses": [
  "active",
  "expired",
  "suspended",
  "pending"
 ],
 "documents_checklist": [
  {
   "key": "identity_proof",
   "label": "Identity proof of the owner or operator"
  },
  {
   "key": "address_proof",
   "label": "Address proof of the premises or office"
  },
  "... 7 more"
 ],
 "required_documents": {
  "hotel": [
   "identity_proof",
   "address_proof",
   "property_papers",
   "trade_licence",
   "fssai"
  ],
  "homestay": [
   "identity_proof",
   "address_proof",
   "property_papers"
  ],
  "guide": [
   "identity_proof",
   "guide_training"
  ],
  "travel_agent": [
   "identity_proof",
   "address_proof",
   "property_papers",
   "trade_licence"
  ],
  "tour_operator": [
   "identity_proof",
   "address_proof",
   "property_papers",
   "trade_licence"
  ],
  "transport": [
   "identity_proof",
   "vehicle_papers"
  ],
  "adventure_operator": [
   "identity_proof",
   "address_proof",
   "property_papers",
   "adventure_permit"
  ],
  "restaurant": [
   "identity_proof",
   "address_proof",
   "property_papers",
   "trade_licence",
   "fssai"
  ]
 },
 "grievance_categories": [
  {
   "key": "overcharging",
   "label": "Overcharging / price not as displayed"
  },
  {
   "key": "cleanliness",
   "label": "Cleanliness / hygiene"
  },
  "... 7 more"
 ],
 "grievance_statuses": [
  "received",
  "assigned",
  "in_progress",
  "resolved",
  "closed"
 ],
 "grievance_sla_days": 7,
 "application_statuses": [
  "submitted",
  "changes_requested",
  "approved",
  "rejected"
 ],
 "advisory_kinds": [
  "road",
  "weather",
  "general"
 ],
 "road_statuses": [
  "open",
  "caution",
  "closed"
 ],
 "crowd_bands": [
  {
   "key": "low",
   "label": "Low",
   "min": 0,
   "max": 39
  },
  {
   "key": "moderate",
   "label": "Moderate",
   "min": 40,
   "max": 64
  },
  "... 2 more"
 ],
 "dictionary_categories": [
  "Hospitality operations",
  "Revenue & metrics",
  "Tourism",
  "Regulation & compliance",
  "Trekking & safety",
  "Local terms"
 ],
 "languages": [
  "Hindi",
  "English",
  "Garhwali",
  "Kumaoni",
  "Punjabi",
  "Bengali",
  "Nepali"
 ],
 "reg_no_format": "UK-<TYPE CODE>-<DISTRICT CODE>-<NNNNN> (prototype codes, not official)",
 "demo_login": true,
 "experiences": [
  {
   "id": "spiritual",
   "name": "Spiritual & Char Dham"
  },
  {
   "id": "adventure",
   "name": "Adventure & Treks"
  },
  "... 4 more"
 ],
 "official_services": {
  "items": [
   {
    "id": "char-dham-registration",
    "name": "Char Dham yatra registration",
    "url": "https://registrationandtouristcare.uk.gov.in/",
    "description": "Official registration for Char Dham pilgrims.",
    "external": true
   },
   {
    "id": "homestay-booking",
    "name": "Homestay booking",
    "url": "https://uttarastays.com/",
    "description": "Official homestay booking site.",
    "external": true
   }
  ],
  "note": "Official site, opens in a new tab; not part of this concept."
 }
}
```

#### `GET /api/v1/districts`

Auth: none. The 13 districts with prototype codes and division.

Example -> 200

Response (abbreviated):
```json
{
 "items": [
  {
   "id": "almora",
   "name": "Almora",
   "code": "ALM",
   "division": "Kumaon"
  },
  {
   "id": "bageshwar",
   "name": "Bageshwar",
   "code": "BAG",
   "division": "Kumaon"
  },
  "... 11 more"
 ],
 "total": 13
}
```

#### `GET /api/v1/stats/public`

Auth: none. Home-page counters.

Example -> 200

Response (abbreviated):
```json
{
 "businesses_listed": 304,
 "destinations": 24,
 "dictionary_terms": 108,
 "active_advisories": 8,
 "synthetic": true
}
```

#### `GET /api/v1/search`

Auth: none (60/min/IP). Unified search, grouped by type. All tokens must match (case-insensitive). Groups: destinations, businesses, events, dictionary, rules, advisories.

Query/body fields: `q` (2-200 chars, required; only the first 80 chars / 6 words are used), `limit` (1-25 per group, default 8)

Example: `GET /api/v1/search?q=kedarnath&limit=2` -> 200

Response (abbreviated):
```json
{
 "query": "kedarnath",
 "total": 17,
 "counts": {
  "destinations": 1,
  "businesses": 12,
  "events": 2,
  "dictionary": 1,
  "rules": 0,
  "advisories": 1
 },
 "groups": {
  "destinations": [
   {
    "id": "kedarnath",
    "name": "Kedarnath",
    "district": "rudraprayag",
    "division": "Garhwal",
    "lat": 30.735,
    "lon": 79.067,
    "altitude_m": null,
    "altitude_note": "Altitude not in the curated reference set yet; to be added from an official source.",
    "tags": [
     "Char Dham",
     "pilgrimage",
     "trek"
    ],
    "themes": [
     "spiritual",
     "adventure"
    ],
    "best_months": [
     5,
     6,
     9,
     10
    ],
    "season_notes": [
     "Char Dham shrines usually open around late April-May and close around October-November; dates are announced each year.",
     "Monsoon (July-September) brings landslide risk on hill roads."
    ],
    "route_facts": [
     "Road to Gaurikund, then a trek of roughly 16-18 km.",
     "Helicopter services also operate from the valley.",
     "Jolly Grant (Dehradun) is the nearest major airport for Garhwal.",
     "Major railheads in Garhwal: Dehradun, Haridwar, Rishikesh (Yog Nagari Rishikesh)."
    ],
    "facts_note": "Approximate, verify with official sources before travel.",
    "district_name": "Rudraprayag"
   }
  ],
  "businesses": [
   {
    "id": "biz_0004",
    "reg_no": "UK-HTL-RUD-00003",
    "name": "Elm Sample Hotel 004, Kedarnath",
    "type": "hotel",
    "district": "rudraprayag",
    "destination_id": "kedarnath",
    "status": "active",
    "verified": true,
    "rating": 4.1,
    "capacity": 47,
    "beds": 141,
    "languages": [
     "Hindi",
     "English"
    ],
    "registered_on": "2023-09-20",
    "valid_until": "2027-09-20",
    "hoi_connected": false,
    "type_label": "Hotel",
    "capacity_unit": "rooms",
    "district_name": "Rudraprayag",
    "destination_name": "Kedarnath",
    "letter": "E",
    "contact": "Contact details are shown to verified visitors in the full product (placeholder in this prototype).",
    "synthetic": true
   },
   "... 1 more"
  ],
  "events": [
   {
    "id": "char-dham-closing",
    "name": "Char Dham closing",
    "kind": "festival",
    "months": [
     10,
     11
    ],
    "window": "October-November",
    "districts": [
     "rudraprayag",
     "chamoli",
     "uttarkashi"
    ],
    "destination_ids": [
     "kedarnath",
     "badrinath",
     "gangotri",
     "yamunotri"
    ],
    "crowd_impact": "high",
    "description": "The shrines close for winter; closing dates are announced each year.",
    "date_note": "Dates follow the lunar calendar and are announced annually; check the official notice.",
    "start_date": null,
    "end_date": null,
    "curated": true,
    "sample": false,
    "district_names": [
     "Rudraprayag",
     "Chamoli",
     "Uttarkashi"
    ],
    "destination_names": [
     "Kedarnath",
     "Badrinath",
     "Gangotri",
     "Yamunotri"
    ],
    "statewide": false,
    "updated_at": null
   },
   "... 1 more"
  ],
  "dictionary": [
   {
    "id": "char-dham",
    "term": "Char Dham",
    "hindi": "चार धाम",
    "category": "Local terms",
    "definition": "The four Himalayan shrines of Yamunotri, Gangotri, Kedarnath and Badrinath.",
    "example": "Char Dham opening and closing dates are announced each year.",
    "related": [
     "dham",
     "yatra"
    ],
    "related_terms": [
     "Dham",
     "Yatra"
    ],
    "letter": "C"
   }
  ],
  "rules": [],
  "advisories": [
   {
    "id": "adv_sample01",
    "kind": "road",
    "status": "caution",
    "district": "rudraprayag",
    "district_name": "Rudraprayag",
    "destination_id": "kedarnath",
    "destination_name": "Kedarnath",
    "segment": "Gaurikund approach",
    "title": "SAMPLE: slow traffic near Gaurikund",
    "reason": "Illustrative sample advisory for the prototype; not real road status.",
    "posted_at": "2026-10-12T07:02:59.683000Z",
    "expires_at": "2026-10-19T08:02:59.683000Z",
    "active": true,
    "sample": true,
    "posted_by_role": "district_officer"
   }
  ]
 }
}
```

### Public: registry (A-Z directory)

#### `GET /api/v1/registry`

Auth: none. List businesses. `letters` = letters that have at least one business (for the A-Z index).

Query/body fields: `type`, `district`, `destination`, `status` (active|expired|suspended|pending), `letter` (A-Z), `q`, `verified` (true), `page` (>=1), `page_size` (1-100, default 24)

Example: `GET /api/v1/registry?district=rudraprayag&type=homestay&page_size=2` -> 200

Response (abbreviated):
```json
{
 "items": [
  {
   "id": "biz_0209",
   "reg_no": "UK-HMS-RUD-00002",
   "name": "Juniper Sample Homestay 209, Chopta",
   "type": "homestay",
   "district": "rudraprayag",
   "destination_id": "chopta",
   "status": "active",
   "verified": true,
   "rating": 4.3,
   "capacity": 5,
   "beds": 10,
   "languages": [
    "Hindi",
    "English"
   ],
   "registered_on": "2025-03-02",
   "valid_until": "2027-03-02",
   "hoi_connected": false,
   "type_label": "Homestay",
   "capacity_unit": "rooms",
   "district_name": "Rudraprayag",
   "destination_name": "Chopta",
   "letter": "J",
   "contact": "Contact details are shown to verified visitors in the full product (placeholder in this prototype).",
   "synthetic": true
  },
  {
   "id": "biz_0010",
   "reg_no": "UK-HMS-RUD-00001",
   "name": "Lotus Sample Homestay 010, Kedarnath",
   "type": "homestay",
   "district": "rudraprayag",
   "destination_id": "kedarnath",
   "status": "active",
   "verified": true,
   "rating": 4.2,
   "capacity": 6,
   "beds": 12,
   "languages": [
    "Hindi",
    "English",
    "Garhwali"
   ],
   "registered_on": "2024-06-07",
   "valid_until": "2027-05-01",
   "hoi_connected": true,
   "type_label": "Homestay",
   "capacity_unit": "rooms",
   "district_name": "Rudraprayag",
   "destination_name": "Kedarnath",
   "letter": "L",
   "contact": "Contact details are shown to verified visitors in the full product (placeholder in this prototype).",
   "synthetic": true
  }
 ],
 "total": 3,
 "page": 1,
 "page_size": 2,
 "letters": [
  "A",
  "B",
  "... 23 more"
 ],
 "synthetic": true
}
```

#### `GET /api/v1/registry/verify`

Auth: none (60/min/IP). Verify a registration number. Always 200; check `found` and `valid`.

Query/body fields: `reg_no` (case and spaces ignored)

Example: `GET /api/v1/registry/verify?reg_no=UK-HTL-RUD-00003` -> 200

Response (abbreviated):
```json
{
 "reg_no": "UK-HTL-RUD-00003",
 "found": true,
 "valid": true,
 "status": "active",
 "message": "Registration is active.",
 "business": {
  "id": "biz_0004",
  "reg_no": "UK-HTL-RUD-00003",
  "name": "Elm Sample Hotel 004, Kedarnath",
  "type": "hotel",
  "district": "rudraprayag",
  "destination_id": "kedarnath",
  "status": "active",
  "verified": true,
  "rating": 4.1,
  "capacity": 47,
  "beds": 141,
  "languages": [
   "Hindi",
   "English"
  ],
  "registered_on": "2023-09-20",
  "valid_until": "2027-09-20",
  "hoi_connected": false,
  "type_label": "Hotel",
  "capacity_unit": "rooms",
  "district_name": "Rudraprayag",
  "destination_name": "Kedarnath",
  "letter": "E",
  "contact": "Contact details are shown to verified visitors in the full product (placeholder in this prototype).",
  "synthetic": true
 },
 "note": "Prototype register with SYNTHETIC businesses."
}
```

#### `GET /api/v1/registry/{id_or_reg_no}`

Auth: none. One business by id or registration number. 404 if unknown.

Example: `GET /api/v1/registry/UK-HTL-RUD-00003` -> 200

Response (abbreviated):
```json
{
 "id": "biz_0004",
 "reg_no": "UK-HTL-RUD-00003",
 "name": "Elm Sample Hotel 004, Kedarnath",
 "type": "hotel",
 "district": "rudraprayag",
 "destination_id": "kedarnath",
 "status": "active",
 "verified": true,
 "rating": 4.1,
 "capacity": 47,
 "beds": 141,
 "languages": [
  "Hindi",
  "English"
 ],
 "registered_on": "2023-09-20",
 "valid_until": "2027-09-20",
 "hoi_connected": false,
 "type_label": "Hotel",
 "capacity_unit": "rooms",
 "district_name": "Rudraprayag",
 "destination_name": "Kedarnath",
 "letter": "E",
 "contact": "Contact details are shown to verified visitors in the full product (placeholder in this prototype).",
 "synthetic": true
}
```

### Public: destinations, weather, crowd

#### `GET /api/v1/destinations`

Auth: none. All 24 destinations with today's crowd estimate.

Query/body fields: `district`, `tag`, `q`

Example: `GET /api/v1/destinations?district=rudraprayag` -> 200

Response (abbreviated):
```json
{
 "items": [
  {
   "id": "chopta",
   "name": "Chopta",
   "district": "rudraprayag",
   "division": "Garhwal",
   "lat": 30.486,
   "lon": 79.211,
   "altitude_m": null,
   "altitude_note": "Altitude not in the curated reference set yet; to be added from an official source.",
   "tags": [
    "snow",
    "trek"
   ],
   "themes": [
    "adventure"
   ],
   "best_months": null,
   "season_notes": [
    "Snow is usual here in winter.",
    "Monsoon (July-September) brings landslide risk on hill roads."
   ],
   "route_facts": [
    "Jolly Grant (Dehradun) is the nearest major airport for Garhwal.",
    "Major railheads in Garhwal: Dehradun, Haridwar, Rishikesh (Yog Nagari Rishikesh)."
   ],
   "facts_note": "Approximate, verify with official sources before travel.",
   "district_name": "Rudraprayag",
   "crowd_today": {
    "index": 68,
    "band": "high",
    "label": "estimate"
   }
  },
  {
   "id": "kedarnath",
   "name": "Kedarnath",
   "district": "rudraprayag",
   "division": "Garhwal",
   "lat": 30.735,
   "lon": 79.067,
   "altitude_m": null,
   "altitude_note": "Altitude not in the curated reference set yet; to be added from an official source.",
   "tags": [
    "Char Dham",
    "pilgrimage",
    "trek"
   ],
   "themes": [
    "spiritual",
    "adventure"
   ],
   "best_months": [
    5,
    6,
    9,
    10
   ],
   "season_notes": [
    "Char Dham shrines usually open around late April-May and close around October-November; dates are announced each year.",
    "Monsoon (July-September) brings landslide risk on hill roads."
   ],
   "route_facts": [
    "Road to Gaurikund, then a trek of roughly 16-18 km.",
    "Helicopter services also operate from the valley.",
    "Jolly Grant (Dehradun) is the nearest major airport for Garhwal.",
    "Major railheads in Garhwal: Dehradun, Haridwar, Rishikesh (Yog Nagari Rishikesh)."
   ],
   "facts_note": "Approximate, verify with official sources before travel.",
   "district_name": "Rudraprayag",
   "crowd_today": {
    "index": 84,
    "band": "high",
    "label": "estimate"
   }
  }
 ],
 "total": 2,
 "tags": [
  "Char Dham",
  "city",
  "... 9 more"
 ],
 "note": "Coordinates and facts are approximate; verify before travel."
}
```

#### `GET /api/v1/destinations/{id}`

Auth: none. Destination page in one call: destination, weather, crowd (today, 14-day outlook, usual by month), roads (facts + road advisories), all active advisories, nearby registered businesses grouped (stays, guides, transport, other), events. Weather may take up to 6 s on a cache miss.

Example: `GET /api/v1/destinations/kedarnath` -> 200

Response (abbreviated):
```json
{
 "destination": {
  "id": "kedarnath",
  "name": "Kedarnath",
  "district": "rudraprayag",
  "division": "Garhwal",
  "lat": 30.735,
  "lon": 79.067,
  "altitude_m": null,
  "altitude_note": "Altitude not in the curated reference set yet; to be added from an official source.",
  "tags": [
   "Char Dham",
   "pilgrimage",
   "trek"
  ],
  "themes": [
   "spiritual",
   "adventure"
  ],
  "best_months": [
   5,
   6,
   9,
   10
  ],
  "season_notes": [
   "Char Dham shrines usually open around late April-May and close around October-November; dates are announced each year.",
   "Monsoon (July-September) brings landslide risk on hill roads."
  ],
  "route_facts": [
   "Road to Gaurikund, then a trek of roughly 16-18 km.",
   "Helicopter services also operate from the valley.",
   "Jolly Grant (Dehradun) is the nearest major airport for Garhwal.",
   "Major railheads in Garhwal: Dehradun, Haridwar, Rishikesh (Yog Nagari Rishikesh)."
  ],
  "facts_note": "Approximate, verify with official sources before travel.",
  "district_name": "Rudraprayag"
 },
 "weather": {
  "available": true,
  "current": {
   "temperature_c": 6.1,
   "weather_code": 3,
   "summary": "Overcast",
   "wind_kmh": 9.4,
   "time": "2026-10-13T10:00"
  },
  "daily": [
   {
    "date": "2026-10-13",
    "max_c": 9.5,
    "min_c": -1.2,
    "precip_probability": 15,
    "precip_mm": 0.0,
    "snow_cm": 0.0,
    "weather_code": 3,
    "summary": "Overcast"
   },
   "... 6 more"
  ],
  "warnings": [
   {
    "date": "2026-10-14",
    "kind": "heavy_rain",
    "message": "Heavy rain is forecast on 2026-10-14 (55.2 mm). Hill roads can be blocked by landslides; check road advisories before setting out."
   },
   "... 1 more"
  ],
  "thresholds": {
   "heavy_rain_mm": 50.0,
   "rain_likely_mm": 20.0,
   "snow_cm": 5.0,
   "note": "ASSUMED thresholds, not official warning criteria."
  },
  "fetched_at": "2026-10-13T08:02:59.943496Z",
  "cached": false,
  "stale": false,
  "source": "Open-Meteo (open-meteo.com), forecast model data",
  "timezone": "Asia/Kolkata"
 },
 "crowd": {
  "label": "estimate",
  "note": "Estimate based on synthetic and reported occupancy, festivals, weekends and season. Not a headcount; plan with care.",
  "bands": [
   {
    "key": "low",
    "label": "Low",
    "min": 0,
    "max": 39
   },
   "... 3 more"
  ],
  "today": {
   "date": "2026-10-13",
   "index": 84,
   "band": "high",
   "occupancy_pct": 84.4,
   "basis": "estimate",
   "events": [
    "Char Dham closing"
   ],
   "weekend": false
  },
  "outlook": [
   {
    "date": "2026-10-13",
    "index": 84,
    "band": "high",
    "occupancy_pct": 84.4,
    "basis": "estimate",
    "events": [
     "Char Dham closing"
    ],
    "weekend": false
   },
   "... 13 more"
  ],
  "outlook_peak": {
   "date": "2026-10-17",
   "index": 90,
   "band": "very_high",
   "occupancy_pct": 85.0,
   "basis": "estimate",
   "events": [
    "Char Dham closing"
   ],
   "weekend": true
  },
  "alert": true,
  "usual_by_month": [
   {
    "month": 1,
    "index": 0,
    "band": "low"
   },
   "... 11 more"
  ],
  "method": "0.8 x occupancy% + event (+12/+6/+2) + weekend (+5) + season (+5 peak / -10 closed); ASSUMED weights."
 },
 "roads": {
  "facts": [
   "Road to Gaurikund, then a trek of roughly 16-18 km.",
   "Helicopter services also operate from the valley.",
   "Jolly Grant (Dehradun) is the nearest major airport for Garhwal.",
   "Major railheads in Garhwal: Dehradun, Haridwar, Rishikesh (Yog Nagari Rishikesh)."
  ],
  "facts_note": "Approximate, verify with official sources before travel.",
  "advisories": [
   {
    "id": "adv_sample01",
    "kind": "road",
    "status": "caution",
    "district": "rudraprayag",
    "district_name": "Rudraprayag",
    "destination_id": "kedarnath",
    "destination_name": "Kedarnath",
    "segment": "Gaurikund approach",
    "title": "SAMPLE: slow traffic near Gaurikund",
    "reason": "Illustrative sample advisory for the prototype; not real road status.",
    "posted_at": "2026-10-12T07:02:59.683000Z",
    "expires_at": "2026-10-19T08:02:59.683000Z",
    "active": true,
    "sample": true,
    "posted_by_role": "district_officer"
   }
  ]
 },
 "advisories": [
  {
   "id": "adv_sample01",
   "kind": "road",
   "status": "caution",
   "district": "rudraprayag",
   "district_name": "Rudraprayag",
   "destination_id": "kedarnath",
   "destination_name": "Kedarnath",
   "segment": "Gaurikund approach",
   "title": "SAMPLE: slow traffic near Gaurikund",
   "reason": "Illustrative sample advisory for the prototype; not real road status.",
   "posted_at": "2026-10-12T07:02:59.683000Z",
   "expires_at": "2026-10-19T08:02:59.683000Z",
   "active": true,
   "sample": true,
   "posted_by_role": "district_officer"
  }
 ],
 "nearby": {
  "stays": {
   "items": [
    {
     "id": "biz_0006",
     "reg_no": "UK-HTL-RUD-00005",
     "name": "Rhododendron Sample Hotel 006, Kedarnath",
     "type": "hotel",
     "district": "rudraprayag",
     "destination_id": "kedarnath",
     "status": "active",
     "verified": true,
     "rating": 4.7,
     "capacity": 25,
     "beds": 50,
     "languages": [
      "Hindi",
      "English",
      "Garhwali"
     ],
     "registered_on": "2022-10-13",
     "valid_until": "2026-10-13",
     "hoi_connected": false,
     "type_label": "Hotel",
     "capacity_unit": "rooms",
     "district_name": "Rudraprayag",
     "destination_name": "Kedarnath",
     "letter": "R",
     "contact": "Contact details are shown to verified visitors in the full product (placeholder in this prototype).",
     "synthetic": true
    },
    "... 5 more"
   ],
   "total": 7
  },
  "guides": {
   "items": [
    {
     "id": "biz_0011",
     "reg_no": "UK-TOP-RUD-00002",
     "name": "Pine Sample Tour operator 011, Kedarnath",
     "type": "tour_operator",
     "district": "rudraprayag",
     "destination_id": "kedarnath",
     "status": "active",
     "verified": false,
     "rating": 4.7,
     "capacity": 34,
     "beds": null,
     "languages": [
      "Hindi",
      "English",
      "Garhwali"
     ],
     "registered_on": "2019-02-25",
     "valid_until": "2027-02-25",
     "hoi_connected": false,
     "type_label": "Tour operator",
     "capacity_unit": "guests per departure",
     "district_name": "Rudraprayag",
     "destination_name": "Kedarnath",
     "letter": "P",
     "contact": "Contact details are shown to verified visitors in the full product (placeholder in this prototype).",
     "synthetic": true
    }
   ],
   "total": 1
  },
  "transport": {
   "items": [
    {
     "id": "biz_0003",
     "reg_no": "UK-TRN-RUD-00001",
     "name": "Quartz Sample Taxi / transport 003, Kedarnath",
     "type": "transport",
     "district": "rudraprayag",
     "destination_id": "kedarnath",
     "status": "active",
     "verified": true,
     "rating": 4.1,
     "capacity": 1,
     "beds": null,
     "languages": [
      "Hindi",
      "English",
      "Nepali"
     ],
     "registered_on": "2026-04-25",
     "valid_until": "2027-04-25",
     "hoi_connected": false,
     "type_label": "Taxi / transport",
     "capacity_unit": "vehicles",
     "district_name": "Rudraprayag",
     "destination_name": "Kedarnath",
     "letter": "Q",
     "contact": "Contact details are shown to verified visitors in the full product (placeholder in this prototype).",
     "synthetic": true
    },
    "... 1 more"
   ],
   "total": 2
  },
  "other": {
   "items": [
    {
     "id": "biz_0012",
     "reg_no": "UK-RST-RUD-00001",
     "name": "Iris Sample Restaurant 012, Kedarnath",
     "type": "restaurant",
     "district": "rudraprayag",
     "destination_id": "kedarnath",
     "status": "active",
     "verified": true,
     "rating": 4.7,
     "capacity": 80,
     "beds": null,
     "languages": [
      "Hindi",
      "English"
     ],
     "registered_on": "2021-07-15",
     "valid_until": "2027-07-15",
     "hoi_connected": false,
     "type_label": "Restaurant",
     "capacity_unit": "seats",
     "district_name": "Rudraprayag",
     "destination_name": "Kedarnath",
     "letter": "I",
     "contact": "Contact details are shown to verified visitors in the full product (placeholder in this prototype).",
     "synthetic": true
    }
   ],
   "total": 1
  }
 },
 "events": [
  {
   "id": "char-dham-closing",
   "name": "Char Dham closing",
   "kind": "festival",
   "months": [
    10,
    11
   ],
   "window": "October-November",
   "districts": [
    "rudraprayag",
    "chamoli",
    "uttarkashi"
   ],
   "destination_ids": [
    "kedarnath",
    "badrinath",
    "gangotri",
    "yamunotri"
   ],
   "crowd_impact": "high",
   "description": "The shrines close for winter; closing dates are announced each year.",
   "date_note": "Dates follow the lunar calendar and are announced annually; check the official notice.",
   "start_date": null,
   "end_date": null,
   "curated": true,
   "sample": false,
   "district_names": [
    "Rudraprayag",
    "Chamoli",
    "Uttarkashi"
   ],
   "destination_names": [
    "Kedarnath",
    "Badrinath",
    "Gangotri",
    "Yamunotri"
   ],
   "statewide": false,
   "updated_at": null
  },
  "... 5 more"
 ],
 "last_updated": "2026-10-13T08:02:59.959030Z"
}
```

#### `GET /api/v1/destinations/{id}/weather`

Auth: none. Weather only. Unavailable shape: `{"available": false, "reason": "..."}`.

Example: `GET /api/v1/destinations/kedarnath/weather` -> 200

Response (abbreviated):
```json
{
 "available": true,
 "current": {
  "temperature_c": 6.1,
  "weather_code": 3,
  "summary": "Overcast",
  "wind_kmh": 9.4,
  "time": "2026-10-13T10:00"
 },
 "daily": [
  {
   "date": "2026-10-13",
   "max_c": 9.5,
   "min_c": -1.2,
   "precip_probability": 15,
   "precip_mm": 0.0,
   "snow_cm": 0.0,
   "weather_code": 3,
   "summary": "Overcast"
  },
  {
   "date": "2026-10-14",
   "max_c": 8.0,
   "min_c": -2.0,
   "precip_probability": 85,
   "precip_mm": 55.2,
   "snow_cm": 0.0,
   "weather_code": 65,
   "summary": "Heavy rain"
  },
  "... 5 more"
 ],
 "warnings": [
  {
   "date": "2026-10-14",
   "kind": "heavy_rain",
   "message": "Heavy rain is forecast on 2026-10-14 (55.2 mm). Hill roads can be blocked by landslides; check road advisories before setting out."
  },
  {
   "date": "2026-10-15",
   "kind": "snow",
   "message": "Snowfall is forecast on 2026-10-15 (6.3 cm). Roads to higher places may close; carry warm layers and check advisories."
  }
 ],
 "thresholds": {
  "heavy_rain_mm": 50.0,
  "rain_likely_mm": 20.0,
  "snow_cm": 5.0,
  "note": "ASSUMED thresholds, not official warning criteria."
 },
 "fetched_at": "2026-10-13T08:02:59.943000Z",
 "cached": true,
 "stale": false,
 "source": "Open-Meteo (open-meteo.com), forecast model data",
 "timezone": "Asia/Kolkata"
}
```

#### `GET /api/v1/destinations/{id}/crowd`

Auth: none. Crowd estimate only.

Example: `GET /api/v1/destinations/kedarnath/crowd` -> 200

Response (abbreviated):
```json
{
 "label": "estimate",
 "note": "Estimate based on synthetic and reported occupancy, festivals, weekends and season. Not a headcount; plan with care.",
 "bands": [
  {
   "key": "low",
   "label": "Low",
   "min": 0,
   "max": 39
  },
  "... 3 more"
 ],
 "today": {
  "date": "2026-10-13",
  "index": 84,
  "band": "high",
  "occupancy_pct": 84.4,
  "basis": "estimate",
  "events": [
   "Char Dham closing"
  ],
  "weekend": false
 },
 "outlook": [
  {
   "date": "2026-10-13",
   "index": 84,
   "band": "high",
   "occupancy_pct": 84.4,
   "basis": "estimate",
   "events": [
    "Char Dham closing"
   ],
   "weekend": false
  },
  "... 13 more"
 ],
 "outlook_peak": {
  "date": "2026-10-17",
  "index": 90,
  "band": "very_high",
  "occupancy_pct": 85.0,
  "basis": "estimate",
  "events": [
   "Char Dham closing"
  ],
  "weekend": true
 },
 "alert": true,
 "usual_by_month": [
  {
   "month": 1,
   "index": 0,
   "band": "low"
  },
  "... 11 more"
 ],
 "method": "0.8 x occupancy% + event (+12/+6/+2) + weekend (+5) + season (+5 peak / -10 closed); ASSUMED weights."
}
```

#### `GET /api/v1/destinations/{id}/nearby`

Auth: none. Other curated destinations by straight-line distance from approximate coordinates (`distance_km`), with today's crowd band and cached weather. Not road distance.

Query/body fields: `limit` 1-23 (default 6)

Example: `GET /api/v1/destinations/kedarnath/nearby?limit=3` -> 200

Response (abbreviated):
```json
{
 "destination_id": "kedarnath",
 "items": [
  {
   "id": "chopta",
   "name": "Chopta",
   "district": "rudraprayag",
   "district_name": "Rudraprayag",
   "division": "Garhwal",
   "lat": 30.486,
   "lon": 79.211,
   "themes": [
    "adventure"
   ],
   "tags": [
    "snow",
    "trek"
   ],
   "best_months": null,
   "crowd_today": {
    "index": 68,
    "band": "high",
    "label": "estimate"
   },
   "weather_now": null,
   "distance_km": 31
  },
  {
   "id": "gangotri",
   "name": "Gangotri",
   "district": "uttarkashi",
   "district_name": "Uttarkashi",
   "division": "Garhwal",
   "lat": 30.994,
   "lon": 78.94,
   "themes": [
    "spiritual"
   ],
   "tags": [
    "Char Dham",
    "pilgrimage"
   ],
   "best_months": [
    5,
    6,
    9,
    10
   ],
   "crowd_today": {
    "index": 86,
    "band": "very_high",
    "label": "estimate"
   },
   "weather_now": null,
   "distance_km": 31
  },
  "... 1 more"
 ],
 "total": 3,
 "distance_note": "Straight-line distance between approximate coordinates, not road distance or travel time."
}
```

### Public: plan (experiences, circuits, sample itineraries, map, official links)

#### `GET /api/v1/experiences`

Auth: none. The 6 experiences (themes) with destination ids.

Example -> 200

Response (abbreviated):
```json
{
 "items": [
  {
   "id": "spiritual",
   "name": "Spiritual & Char Dham",
   "short": "Shrines, ghats and the yatra season.",
   "icon": "temple",
   "destination_count": 6,
   "destination_ids": [
    "kedarnath",
    "badrinath",
    "gangotri",
    "yamunotri",
    "rishikesh",
    "haridwar"
   ]
  },
  {
   "id": "adventure",
   "name": "Adventure & Treks",
   "short": "Treks, snow and high meadows.",
   "icon": "peak",
   "destination_count": 7,
   "destination_ids": [
    "kedarnath",
    "yamunotri",
    "rishikesh",
    "auli",
    "valley-of-flowers",
    "chopta",
    "munsiyari"
   ]
  },
  {
   "id": "wildlife",
   "name": "Wildlife & Nature",
   "short": "National parks and flower meadows.",
   "icon": "leaf",
   "destination_count": 2,
   "destination_ids": [
    "jim-corbett-ramnagar",
    "valley-of-flowers"
   ]
  },
  {
   "id": "wellness",
   "name": "Yoga & Wellness",
   "short": "Yoga, the river and slow days.",
   "icon": "lotus",
   "destination_count": 2,
   "destination_ids": [
    "rishikesh",
    "haridwar"
   ]
  },
  {
   "id": "leisure",
   "name": "Hill towns & Leisure",
   "short": "Lakes, ridges and family breaks.",
   "icon": "lake",
   "destination_count": 10,
   "destination_ids": [
    "mussoorie",
    "dehradun",
    "nainital",
    "almora",
    "kausani",
    "lansdowne",
    "... 4 more"
   ]
  },
  {
   "id": "culture",
   "name": "Culture & Fairs",
   "short": "Fairs, seasonal festivals and local life.",
   "icon": "drum",
   "destination_count": 3,
   "destination_ids": [
    "nainital",
    "almora",
    "bageshwar"
   ]
  }
 ],
 "total": 6
}
```

#### `GET /api/v1/experiences/{id}`

Auth: none. One experience: intro (our own words), destinations with crowd band and `weather_now` (cache only; null until loaded), related festivals, dictionary terms, itineraries, circuits.

Example: `GET /api/v1/experiences/spiritual` -> 200

Response (abbreviated):
```json
{
 "id": "spiritual",
 "name": "Spiritual & Char Dham",
 "short": "Shrines, ghats and the yatra season.",
 "intro": "Uttarakhand is one of India's best-known pilgrimage regions. The four Char Dham shrines open for a season each year and close for winter,...",
 "icon": "temple",
 "destinations": [
  {
   "id": "kedarnath",
   "name": "Kedarnath",
   "district": "rudraprayag",
   "district_name": "Rudraprayag",
   "division": "Garhwal",
   "lat": 30.735,
   "lon": 79.067,
   "themes": [
    "spiritual",
    "adventure"
   ],
   "tags": [
    "Char Dham",
    "pilgrimage",
    "trek"
   ],
   "best_months": [
    5,
    6,
    9,
    10
   ],
   "crowd_today": {
    "index": 84,
    "band": "high",
    "label": "estimate"
   },
   "weather_now": {
    "available": true,
    "temperature_c": 6.1,
    "summary": "Overcast",
    "warning": {
     "date": "2026-10-14",
     "kind": "heavy_rain",
     "message": "Heavy rain is forecast on 2026-10-14 (55.2 mm). Hill roads can be blocked by landslides; check road advisories before setting out."
    },
    "fetched_at": "2026-10-13T08:02:59.943000Z",
    "stale": false
   }
  },
  "... 5 more"
 ],
 "festivals": [
  {
   "id": "char-dham-opening",
   "name": "Char Dham yatra opening",
   "kind": "festival",
   "months": [
    4,
    5
   ],
   "window": "April-May",
   "districts": [
    "rudraprayag",
    "chamoli",
    "uttarkashi"
   ],
   "destination_ids": [
    "kedarnath",
    "badrinath",
    "gangotri",
    "yamunotri"
   ],
   "crowd_impact": "high",
   "description": "The four Char Dham shrines open for the season; opening dates are announced each year.",
   "date_note": "Dates follow the lunar calendar and are announced annually; check the official notice.",
   "start_date": null,
   "end_date": null,
   "curated": true,
   "sample": false,
   "district_names": [
    "Rudraprayag",
    "Chamoli",
    "Uttarkashi"
   ],
   "destination_names": [
    "Kedarnath",
    "Badrinath",
    "Gangotri",
    "Yamunotri"
   ],
   "statewide": false,
   "updated_at": null
  },
  "... 3 more"
 ],
 "terms": [
  {
   "id": "char-dham",
   "term": "Char Dham",
   "hindi": "चार धाम",
   "definition": "The four Himalayan shrines of Yamunotri, Gangotri, Kedarnath and Badrinath."
  },
  "... 7 more"
 ],
 "itineraries": [
  {
   "id": "char-dham-yatra",
   "name": "Char Dham yatra",
   "theme": "spiritual",
   "theme_name": "Spiritual & Char Dham",
   "circuit_id": "char-dham",
   "summary": "All four shrines, starting and ending at the river towns.",
   "stops": [
    {
     "destination_id": "haridwar",
     "name": "Haridwar",
     "suggested_days": 1
    },
    "... 5 more"
   ],
   "suggested_days_total": 10,
   "sample": true,
   "note": "Sample plan for orientation. Suggested days are a planning suggestion, not a schedule. Verify routes, road status, shrine and park dates,..."
  },
  "... 1 more"
 ],
 "circuits": [
  {
   "id": "char-dham",
   "name": "Char Dham",
   "theme": "spiritual",
   "description": "The four shrines, usually visited west to east: Yamunotri, Gangotri, Kedarnath, Badrinath.",
   "destination_ids": [
    "yamunotri",
    "gangotri",
    "kedarnath",
    "badrinath"
   ],
   "destinations": [
    {
     "id": "yamunotri",
     "name": "Yamunotri",
     "lat": 31.014,
     "lon": 78.46
    },
    "... 3 more"
   ]
  }
 ],
 "crowd_note": "Crowd level is an estimate. Weather shown only when recently loaded; open a destination for the live forecast."
}
```

#### `GET /api/v1/circuits`

Auth: none. Circuits as ordered destination lists.

Example -> 200

Response (abbreviated):
```json
{
 "items": [
  {
   "id": "char-dham",
   "name": "Char Dham",
   "theme": "spiritual",
   "description": "The four shrines, usually visited west to east: Yamunotri, Gangotri, Kedarnath, Badrinath.",
   "destination_ids": [
    "yamunotri",
    "gangotri",
    "kedarnath",
    "badrinath"
   ],
   "destinations": [
    {
     "id": "yamunotri",
     "name": "Yamunotri",
     "lat": 31.014,
     "lon": 78.46
    },
    "... 3 more"
   ]
  },
  "... 4 more"
 ],
 "total": 5,
 "note": "Groupings for planning; the order is a suggestion. Verify routes."
}
```

#### `GET /api/v1/itineraries`

Auth: none. Sample multi-stop trips built only from curated destinations. `suggested_days` is a planning suggestion; no distances, times or prices.

Query/body fields: `theme`

Example -> 200

Response (abbreviated):
```json
{
 "items": [
  {
   "id": "char-dham-yatra",
   "name": "Char Dham yatra",
   "theme": "spiritual",
   "theme_name": "Spiritual & Char Dham",
   "circuit_id": "char-dham",
   "summary": "All four shrines, starting and ending at the river towns.",
   "stops": [
    {
     "destination_id": "haridwar",
     "name": "Haridwar",
     "suggested_days": 1
    },
    "... 5 more"
   ],
   "suggested_days_total": 10,
   "sample": true,
   "note": "Sample plan for orientation. Suggested days are a planning suggestion, not a schedule. Verify routes, road status, shrine and park dates,..."
  },
  "... 7 more"
 ],
 "total": 8,
 "note": "Sample plan for orientation. Suggested days are a planning suggestion, not a schedule. Verify routes, road status, shrine and park dates,..."
}
```

#### `GET /api/v1/itineraries/{id}`

Auth: none. One sample trip: per stop crowd today (estimate), weather (live, fetched in parallel within a 6 s budget, else cache), worst road advisory; `best_start` = start date in the next 14 days with the lowest average crowd estimate over all trip days.

Example: `GET /api/v1/itineraries/do-dham` -> 200

Response (abbreviated):
```json
{
 "id": "do-dham",
 "name": "Do Dham: Kedarnath and Badrinath",
 "theme": "spiritual",
 "theme_name": "Spiritual & Char Dham",
 "circuit_id": "char-dham",
 "summary": "The two eastern shrines from Rishikesh.",
 "stops": [
  {
   "order": 1,
   "destination_id": "rishikesh",
   "name": "Rishikesh",
   "district_name": "Dehradun",
   "suggested_days": 1,
   "best_months": null,
   "route_facts": [
    "Jolly Grant (Dehradun) is the nearest major airport for Garhwal.",
    "Major railheads in Garhwal: Dehradun, Haridwar, Rishikesh (Yog Nagari Rishikesh)."
   ],
   "crowd_today": {
    "index": 67,
    "band": "high",
    "label": "estimate"
   },
   "weather": {
    "available": true,
    "temperature_c": 6.1,
    "summary": "Overcast",
    "warning": {
     "date": "2026-10-14",
     "kind": "heavy_rain",
     "message": "Heavy rain is forecast on 2026-10-14 (55.2 mm). Hill roads can be blocked by landslides; check road advisories before setting out."
    }
   },
   "road": null
  },
  {
   "order": 2,
   "destination_id": "kedarnath",
   "name": "Kedarnath",
   "district_name": "Rudraprayag",
   "suggested_days": 2,
   "best_months": [
    5,
    6,
    9,
    10
   ],
   "route_facts": [
    "Road to Gaurikund, then a trek of roughly 16-18 km.",
    "Helicopter services also operate from the valley.",
    "Jolly Grant (Dehradun) is the nearest major airport for Garhwal.",
    "Major railheads in Garhwal: Dehradun, Haridwar, Rishikesh (Yog Nagari Rishikesh)."
   ],
   "crowd_today": {
    "index": 84,
    "band": "high",
    "label": "estimate"
   },
   "weather": {
    "available": true,
    "temperature_c": 6.1,
    "summary": "Overcast",
    "warning": {
     "date": "2026-10-14",
     "kind": "heavy_rain",
     "message": "Heavy rain is forecast on 2026-10-14 (55.2 mm). Hill roads can be blocked by landslides; check road advisories before setting out."
    }
   },
   "road": {
    "status": "caution",
    "title": "SAMPLE: slow traffic near Gaurikund",
    "segment": "Gaurikund approach",
    "count": 1,
    "sample": true
   }
  },
  "... 1 more"
 ],
 "suggested_days_total": 5,
 "sample": true,
 "note": "Sample plan for orientation. Suggested days are a planning suggestion, not a schedule. Verify routes, road status, shrine and park dates,...",
 "best_start": {
  "date": "2026-10-26",
  "offset_days": 13,
  "avg_index": 74,
  "band": "high",
  "peak_index": 83,
  "if_start_today": {
   "avg_index": 84,
   "band": "high"
  },
  "window_days": 14,
  "label": "estimate",
  "method": "Lowest average crowd estimate over all trip days, for start dates in the next 14 days, following the suggested days per stop."
 },
 "generated_at": "2026-10-13T08:03:00.004688Z"
}
```

#### `GET /api/v1/map`

Auth: none. Points for a schematic dot map (not to scale, no boundaries), with circuits, experiences and districts for filters.

Example -> 200

Response (abbreviated):
```json
{
 "items": [
  {
   "id": "kedarnath",
   "name": "Kedarnath",
   "district": "rudraprayag",
   "district_name": "Rudraprayag",
   "division": "Garhwal",
   "lat": 30.735,
   "lon": 79.067,
   "themes": [
    "spiritual",
    "adventure"
   ],
   "tags": [
    "Char Dham",
    "pilgrimage",
    "trek"
   ],
   "best_months": [
    5,
    6,
    9,
    10
   ],
   "crowd_today": {
    "index": 84,
    "band": "high",
    "label": "estimate"
   },
   "weather_now": {
    "available": true,
    "temperature_c": 6.1,
    "summary": "Overcast",
    "warning": {
     "date": "2026-10-14",
     "kind": "heavy_rain",
     "message": "Heavy rain is forecast on 2026-10-14 (55.2 mm). Hill roads can be blocked by landslides; check road advisories before setting out."
    },
    "fetched_at": "2026-10-13T08:02:59.943000Z",
    "stale": false
   },
   "circuits": [
    "char-dham"
   ]
  },
  "... 23 more"
 ],
 "circuits": [
  {
   "id": "char-dham",
   "name": "Char Dham",
   "theme": "spiritual",
   "description": "The four shrines, usually visited west to east: Yamunotri, Gangotri, Kedarnath, Badrinath.",
   "destination_ids": [
    "yamunotri",
    "gangotri",
    "kedarnath",
    "badrinath"
   ],
   "destinations": [
    {
     "id": "yamunotri",
     "name": "Yamunotri",
     "lat": 31.014,
     "lon": 78.46
    },
    "... 3 more"
   ]
  },
  "... 4 more"
 ],
 "experiences": [
  {
   "id": "spiritual",
   "name": "Spiritual & Char Dham"
  },
  "... 5 more"
 ],
 "districts": [
  {
   "id": "almora",
   "name": "Almora",
   "code": "ALM",
   "division": "Kumaon"
  },
  "... 12 more"
 ],
 "bounds": {
  "lat": [
   29.21,
   31.014
  ],
  "lon": [
   78.032,
   80.238
  ]
 },
 "note": "Schematic dot map from approximate coordinates; not to scale; no boundaries shown."
}
```

#### `GET /api/v1/official-services`

Auth: none. Official external services (open in a new tab; not part of this concept).

Example -> 200

Response (abbreviated):
```json
{
 "items": [
  {
   "id": "char-dham-registration",
   "name": "Char Dham yatra registration",
   "url": "https://registrationandtouristcare.uk.gov.in/",
   "description": "Official registration for Char Dham pilgrims.",
   "external": true
  },
  {
   "id": "homestay-booking",
   "name": "Homestay booking",
   "url": "https://uttarastays.com/",
   "description": "Official homestay booking site.",
   "external": true
  }
 ],
 "note": "Official site, opens in a new tab; not part of this concept."
}
```

#### `GET /api/v1/district-offices`

Auth: none. District tourism office placeholders: contacts are to be filled by the department.

Example -> 200

Response (abbreviated):
```json
{
 "items": [
  {
   "district": "almora",
   "district_name": "Almora",
   "division": "Kumaon",
   "office": "District tourism office, Almora",
   "contact": null,
   "note": "Contact details to be filled by the department."
  },
  {
   "district": "bageshwar",
   "district_name": "Bageshwar",
   "division": "Kumaon",
   "office": "District tourism office, Bageshwar",
   "contact": null,
   "note": "Contact details to be filled by the department."
  },
  "... 11 more"
 ],
 "total": 13,
 "note": "Placeholders: names and numbers are to be filled by the department."
}
```

### Public: calendar, dictionary, rules, helplines, advisories

#### `GET /api/v1/events`

Auth: none. Festivals (curated, usual months) and dated officer events. `by_month` maps '1'..'12' to event ids for a month view.

Query/body fields: `month` (1-12), `district`, `destination`, `q`

Example: `GET /api/v1/events?month=10` -> 200

Response (abbreviated):
```json
{
 "items": [
  {
   "id": "char-dham-closing",
   "name": "Char Dham closing",
   "kind": "festival",
   "months": [
    10,
    11
   ],
   "window": "October-November",
   "districts": [
    "rudraprayag",
    "chamoli",
    "uttarkashi"
   ],
   "destination_ids": [
    "kedarnath",
    "badrinath",
    "gangotri",
    "yamunotri"
   ],
   "crowd_impact": "high",
   "description": "The shrines close for winter; closing dates are announced each year.",
   "date_note": "Dates follow the lunar calendar and are announced annually; check the official notice.",
   "start_date": null,
   "end_date": null,
   "curated": true,
   "sample": false,
   "district_names": [
    "Rudraprayag",
    "Chamoli",
    "Uttarkashi"
   ],
   "destination_names": [
    "Kedarnath",
    "Badrinath",
    "Gangotri",
    "Yamunotri"
   ],
   "statewide": false,
   "updated_at": null
  },
  {
   "id": "dussehra-diwali",
   "name": "Dussehra and Diwali",
   "kind": "festival",
   "months": [
    10,
    11
   ],
   "window": "October-November",
   "districts": [
    "almora",
    "bageshwar",
    "... 11 more"
   ],
   "destination_ids": [],
   "crowd_impact": "medium",
   "description": "Festive season across the state; holiday travel rises.",
   "date_note": "Dates follow the lunar calendar and are announced annually; check the official notice.",
   "start_date": null,
   "end_date": null,
   "curated": true,
   "sample": false,
   "district_names": [
    "Almora",
    "Bageshwar",
    "... 11 more"
   ],
   "destination_names": [],
   "statewide": true,
   "updated_at": null
  },
  "... 2 more"
 ],
 "total": 4,
 "by_month": {
  "1": [],
  "2": [],
  "3": [],
  "4": [],
  "5": [],
  "6": [],
  "7": [],
  "8": [],
  "9": [],
  "10": [
   "char-dham-closing",
   "dussehra-diwali",
   "evt_sample01",
   "evt_sample02"
  ],
  "11": [
   "char-dham-closing",
   "dussehra-diwali"
  ],
  "12": []
 },
 "note": "Usual timing only. Lunar-calendar dates are announced annually; check the official notice."
}
```

#### `GET /api/v1/dictionary`

Auth: none. Dictionary terms.

Query/body fields: `letter`, `category` (exact label from `categories`), `q`

Example: `GET /api/v1/dictionary?letter=R` -> 200

Response (abbreviated):
```json
{
 "items": [
  {
   "id": "rack-rate",
   "term": "Rack rate",
   "hindi": null,
   "category": "Revenue & metrics",
   "definition": "The standard published price of a room before any discount.",
   "example": "Online rates are often below the rack rate.",
   "related": [
    "seasonal-pricing"
   ],
   "related_terms": [
    "Seasonal pricing"
   ],
   "letter": "R"
  },
  {
   "id": "registration",
   "term": "Registration",
   "hindi": "पंजीकरण",
   "category": "Regulation & compliance",
   "definition": "Recording a business with the relevant authority so it can operate and be listed.",
   "example": "This portal shows a registration number for each listed business.",
   "related": [
    "renewal",
    "verified-business"
   ],
   "related_terms": [
    "Renewal",
    "Verified business"
   ],
   "letter": "R"
  },
  "... 10 more"
 ],
 "total": 12,
 "letters": [
  "A",
  "B",
  "... 19 more"
 ],
 "categories": [
  "Hospitality operations",
  "Revenue & metrics",
  "Tourism",
  "Regulation & compliance",
  "Trekking & safety",
  "Local terms"
 ],
 "note": "Plain-language explanations for orientation; not legal definitions. Hindi terms to be reviewed by native speakers."
}
```

#### `GET /api/v1/dictionary/{id}`

Auth: none. One term with resolved related terms.

Example: `GET /api/v1/dictionary/revpar` -> 200

Response (abbreviated):
```json
{
 "id": "revpar",
 "term": "RevPAR",
 "hindi": null,
 "category": "Revenue & metrics",
 "definition": "Revenue per available room: room revenue divided by rooms available (or ADR times occupancy).",
 "example": "ADR Rs 2,000 at 50% occupancy gives RevPAR of Rs 1,000.",
 "related": [
  "average-daily-rate-adr",
  "occupancy-rate"
 ],
 "related_terms": [
  "Average daily rate (ADR)",
  "Occupancy rate"
 ],
 "letter": "R",
 "related_items": [
  {
   "id": "occupancy-rate",
   "term": "Occupancy rate"
  },
  {
   "id": "average-daily-rate-adr",
   "term": "Average daily rate (ADR)"
  }
 ]
}
```

#### `GET /api/v1/rules`

Auth: none. Rules, licences and schemes cards (orientation only).

Query/body fields: `business_type`, `q`

Example: `GET /api/v1/rules?business_type=homestay` -> 200

Response (abbreviated):
```json
{
 "items": [
  {
   "id": "fssai",
   "title": "FSSAI registration / licence",
   "who_needs_it": "Businesses that prepare, serve or sell food, including restaurants and stays that serve meals.",
   "what_it_covers": "Food safety registration or licence; which one applies depends on the business.",
   "typical_documents": [
    "Identity proof of the owner or operator",
    "Address proof of the premises",
    "Ownership or lease papers for the premises",
    "Details of the food served and the kitchen"
   ],
   "where_to_apply": "Food Safety and Standards Authority of India (FSSAI).",
   "business_types": [
    "hotel",
    "homestay",
    "restaurant"
   ],
   "tags": [
    "food",
    "licence"
   ],
   "verify_note": "Summary for orientation, verify with the issuing authority."
  },
  {
   "id": "form-c",
   "title": "Form C reporting of foreign guests",
   "who_needs_it": "Accommodation providers who host foreign guests.",
   "what_it_covers": "Reporting each foreign guest's stay to the FRRO.",
   "typical_documents": [
    "Guest's passport and visa details",
    "Stay dates"
   ],
   "where_to_apply": "Foreigners Regional Registration Office (FRRO).",
   "business_types": [
    "hotel",
    "homestay"
   ],
   "tags": [
    "foreign guests",
    "reporting"
   ],
   "verify_note": "Summary for orientation, verify with the issuing authority."
  },
  "... 4 more"
 ],
 "total": 6,
 "note": "Summary for orientation, verify with the issuing authority. No fees, thresholds or section numbers are given here."
}
```

#### `GET /api/v1/rules/{id}`

Auth: none. One card.

Example: `GET /api/v1/rules/form-c` -> 200

Response (abbreviated):
```json
{
 "id": "form-c",
 "title": "Form C reporting of foreign guests",
 "who_needs_it": "Accommodation providers who host foreign guests.",
 "what_it_covers": "Reporting each foreign guest's stay to the FRRO.",
 "typical_documents": [
  "Guest's passport and visa details",
  "Stay dates"
 ],
 "where_to_apply": "Foreigners Regional Registration Office (FRRO).",
 "business_types": [
  "hotel",
  "homestay"
 ],
 "tags": [
  "foreign guests",
  "reporting"
 ],
 "verify_note": "Summary for orientation, verify with the issuing authority."
}
```

#### `GET /api/v1/helplines`

Auth: none. Helplines. `number: null` = placeholder to be filled by the department.

Example -> 200

Response (abbreviated):
```json
{
 "items": [
  {
   "id": "emergency-112",
   "name": "All-India emergency",
   "number": "112",
   "scope": "national",
   "note": "Police, fire and ambulance."
  },
  {
   "id": "ambulance-108",
   "name": "Ambulance",
   "number": "108",
   "scope": "national",
   "note": null
  },
  {
   "id": "tourist-helpline-1363",
   "name": "Ministry of Tourism tourist helpline",
   "number": "1363 / 1800-11-1363",
   "scope": "national",
   "note": null
  },
  {
   "id": "disaster-1077",
   "name": "District disaster control room",
   "number": "1077",
   "scope": "district",
   "note": "Verify per district."
  },
  {
   "id": "state-tourism-helpline",
   "name": "State tourism helpline",
   "number": null,
   "scope": "state",
   "note": "To be filled by the department."
  },
  {
   "id": "police-tourist-help",
   "name": "Police tourist help",
   "number": null,
   "scope": "state",
   "note": "To be filled by the department."
  }
 ],
 "note": "Verify numbers locally. Blank numbers are placeholders to be filled by the department."
}
```

#### `GET /api/v1/advisories`

Auth: none. Active advisories, closed first. `sample: true` items are illustrative.

Query/body fields: `district`, `destination` (also returns district-wide advisories without a destination), `kind` (road|weather|general)

Example: `GET /api/v1/advisories?district=rudraprayag` -> 200

Response (abbreviated):
```json
{
 "items": [
  {
   "id": "adv_sample01",
   "kind": "road",
   "status": "caution",
   "district": "rudraprayag",
   "district_name": "Rudraprayag",
   "destination_id": "kedarnath",
   "destination_name": "Kedarnath",
   "segment": "Gaurikund approach",
   "title": "SAMPLE: slow traffic near Gaurikund",
   "reason": "Illustrative sample advisory for the prototype; not real road status.",
   "posted_at": "2026-10-12T07:02:59.683000Z",
   "expires_at": "2026-10-19T08:02:59.683000Z",
   "active": true,
   "sample": true,
   "posted_by_role": "district_officer"
  }
 ],
 "total": 1,
 "by_district": {
  "rudraprayag": 1
 },
 "note": "Items marked sample are illustrative, not real road status."
}
```

### Public: grievances

#### `POST /api/v1/grievances`

Auth: none (5/hour/IP). File a grievance. Returns 201 with `ticket_id` and the 6-digit `tracking_code` (shown once; store only on the user's screen).

Query/body fields: `category` (see /meta), `district`, `business_reg_no` (optional, format checked), `description` (10-2000), `contact` (optional, officers only)

Example -> 201

Request body:
```json
{
 "category": "overcharging",
 "district": "rudraprayag",
 "business_reg_no": null,
 "description": "Taxi charged more than the agreed fare.",
 "contact": "optional, kept private"
}
```

Response (abbreviated):
```json
{
 "ticket_id": "UTHP-G-000041",
 "category": "overcharging",
 "category_label": "Overcharging / price not as displayed",
 "district": "rudraprayag",
 "district_name": "Rudraprayag",
 "business_reg_no": null,
 "status": "received",
 "created_at": "2026-10-13T08:02:59.808677Z",
 "updated_at": "2026-10-13T08:02:59.808677Z",
 "sla_due_at": "2026-10-20T08:02:59.808677Z",
 "sla_days": 7,
 "overdue": false,
 "resolved_at": null,
 "timeline": [
  {
   "status": "received",
   "at": "2026-10-13T08:02:59.808677Z",
   "note": "Grievance received."
  }
 ],
 "synthetic": false,
 "tracking_code": "961070",
 "message": "Keep the ticket id and tracking code. You need both to check the status. The code is shown only once."
}
```

#### `POST /api/v1/grievances/track`

Auth: none (20/min/IP). Track. 404 with a generic message when the ticket or code is wrong. Public timeline shows only public notes.

Example -> 200

Request body:
```json
{
 "ticket_id": "UTHP-G-000041",
 "tracking_code": "961070"
}
```

Response (abbreviated):
```json
{
 "ticket_id": "UTHP-G-000041",
 "category": "overcharging",
 "category_label": "Overcharging / price not as displayed",
 "district": "rudraprayag",
 "district_name": "Rudraprayag",
 "business_reg_no": null,
 "status": "received",
 "created_at": "2026-10-13T08:02:59.808000Z",
 "updated_at": "2026-10-13T08:02:59.808000Z",
 "sla_due_at": "2026-10-20T08:02:59.808000Z",
 "sla_days": 7,
 "overdue": false,
 "resolved_at": null,
 "timeline": [
  {
   "status": "received",
   "at": "2026-10-13T08:02:59.808000Z",
   "note": "Grievance received."
  }
 ],
 "synthetic": false
}
```

### Auth

#### `GET /api/v1/auth/demo-accounts`

Auth: none. Demo accounts for one-click login. Empty list when demo login is off.

Example -> 200

Response (abbreviated):
```json
[
 {
  "username": "demo.admin",
  "role": "state_admin",
  "district": null,
  "label": "State admin (demo)",
  "description": "All districts: officers, analytics, approvals"
 },
 {
  "username": "demo.officer.rudraprayag",
  "role": "district_officer",
  "district": "rudraprayag",
  "label": "District tourism officer, Rudraprayag (demo)",
  "description": "Applications, grievances, advisories and analytics for Rudraprayag only"
 },
 {
  "username": "demo.business",
  "role": "business",
  "district": null,
  "label": "Business owner (demo)",
  "description": "Registered homestay and hotel, renewals, occupancy, API key"
 }
]
```

#### `POST /api/v1/auth/demo/{username}`

Auth: none (10/min/IP). One-click demo sign-in. 404 when disabled, in production, or for non-demo usernames.

Example: `POST /api/v1/auth/demo/demo.officer.rudraprayag` -> 200

Response (abbreviated):
```json
{
 "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c3JfZTE5MDM2YjA4ZjUyIiwidXNyIjoiZGVtby5vZmZpY2VyLnJ1ZHJhcHJheWFnIiwicm9sZSI6ImRpc3RyaWN0...",
 "token_type": "bearer",
 "expires_in": 1800,
 "refresh_token": "ffF2qL8srq2wMjR5xFf17hU_AEzXRqgxM2OFFppKsvmwLU7-LampeNIUoNISzBXn",
 "user": {
  "id": "usr_e19036b08f52",
  "username": "demo.officer.rudraprayag",
  "role": "district_officer",
  "district": "rudraprayag",
  "label": "District tourism officer, Rudraprayag (demo)",
  "active": true,
  "created_at": "2026-10-13T08:02:57.880000Z",
  "last_login": null,
  "role_label": "District tourism officer",
  "district_name": "Rudraprayag"
 }
}
```

#### `POST /api/v1/auth/register`

Auth: none (10/min/IP). Business owner self-registration (role `business`). 201 + session. 409 if the username is taken.

Example -> 201

Request body:
```json
{
 "username": "my.homestay",
 "password": "at-least-10-chars"
}
```

Response (abbreviated):
```json
{
 "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c3JfNjRhNjY4MDUxMzEyIiwidXNyIjoibXkuaG9tZXN0YXkiLCJyb2xlIjoiYnVzaW5lc3MiLCJkc3QiOm51bGws...",
 "token_type": "bearer",
 "expires_in": 1800,
 "refresh_token": "wvgoa6WM6ELI28-hYgXOvvX05vDNNxChOFY72EuYpIQwC93g-e2_DI2oAOf5W9UW",
 "user": {
  "id": "usr_64a668051312",
  "username": "my.homestay",
  "role": "business",
  "district": null,
  "label": null,
  "active": true,
  "created_at": "2026-10-13T08:03:00.176033Z",
  "last_login": null,
  "role_label": "Business",
  "district_name": null
 }
}
```

#### `POST /api/v1/auth/login`

Auth: none (10/min per IP and per username). Password sign-in. 401 `Wrong username or password.`; 5 failures lock the account for 5 minutes.

Example -> 200

Request body:
```json
{
 "username": "my.homestay",
 "password": "at-least-10-chars"
}
```

Response (abbreviated):
```json
{
 "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c3JfNjRhNjY4MDUxMzEyIiwidXNyIjoibXkuaG9tZXN0YXkiLCJyb2xlIjoiYnVzaW5lc3MiLCJkc3QiOm51bGws...",
 "token_type": "bearer",
 "expires_in": 1800,
 "refresh_token": "ez0ZqR_lrri0kbfAeuXVEFgtWICmQf0VCIPj9-e3We7EYKyrqKtAbm8i1bKw4LMM",
 "user": {
  "id": "usr_64a668051312",
  "username": "my.homestay",
  "role": "business",
  "district": null,
  "label": null,
  "active": true,
  "created_at": "2026-10-13T08:03:00.176000Z",
  "last_login": "2026-10-13T08:03:00.277000Z",
  "role_label": "Business",
  "district_name": null
 }
}
```

#### `POST /api/v1/auth/refresh`

Auth: none. Rotate: returns a new access token AND a new refresh token; the old refresh token stops working.

Example -> 200

Request body:
```json
{
 "refresh_token": "jSmnHUznVy2Iat-0SCqHWfLE9XWQ4LCijRhjGPt2FngWt7FpuhL9o2cIiDpCjXh1"
}
```

Response (abbreviated):
```json
{
 "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c3JfNjRhNjY4MDUxMzEyIiwidXNyIjoibXkuaG9tZXN0YXkiLCJyb2xlIjoiYnVzaW5lc3MiLCJkc3QiOm51bGws...",
 "token_type": "bearer",
 "expires_in": 1800,
 "refresh_token": "K2_AlRY7-9EHw1btVInqU2KM8_2k2HFowhoYiL8ULKFOt6zh5O7EcuSjgkvphbYO",
 "user": {
  "id": "usr_64a668051312",
  "username": "my.homestay",
  "role": "business",
  "district": null,
  "label": null,
  "active": true,
  "created_at": "2026-10-13T08:03:00.176000Z",
  "last_login": "2026-10-13T08:03:00.373000Z",
  "role_label": "Business",
  "district_name": null
 }
}
```

#### `GET /api/v1/auth/me`

Auth: any signed-in. Current user.

Example -> 200

Response (abbreviated):
```json
{
 "user": {
  "id": "usr_e19036b08f52",
  "username": "demo.officer.rudraprayag",
  "role": "district_officer",
  "district": "rudraprayag",
  "label": "District tourism officer, Rudraprayag (demo)",
  "active": true,
  "created_at": "2026-10-13T08:02:57.880000Z",
  "last_login": null,
  "role_label": "District tourism officer",
  "district_name": "Rudraprayag"
 }
}
```

#### `POST /api/v1/auth/logout`

Auth: none. Revoke a refresh token. 204, empty body.

Example -> 204

Request body:
```json
{
 "refresh_token": "wHcaui67BvM7c3lBgTdKYpkaW7BLBfB_MmcJjwwkBMwBuTW1LWC65gEyqfQJK2JX"
}
```

### Business owner (role `business`)

#### `GET /api/v1/business/dashboard`

Auth: business. Everything for the dashboard: own businesses, own applications, summary counts.

Example -> 200

Response (abbreviated):
```json
{
 "businesses": [
  {
   "id": "biz_0010",
   "reg_no": "UK-HMS-RUD-00001",
   "name": "Lotus Sample Homestay 010, Kedarnath",
   "type": "homestay",
   "district": "rudraprayag",
   "destination_id": "kedarnath",
   "status": "active",
   "verified": true,
   "rating": 4.2,
   "capacity": 6,
   "beds": 12,
   "languages": [
    "Hindi",
    "English",
    "Garhwali"
   ],
   "registered_on": "2024-06-07",
   "valid_until": "2027-05-01",
   "hoi_connected": true,
   "type_label": "Homestay",
   "capacity_unit": "rooms",
   "district_name": "Rudraprayag",
   "destination_name": "Kedarnath",
   "letter": "L",
   "contact": "Contact details are shown to verified visitors in the full product (placeholder in this prototype).",
   "synthetic": true,
   "days_to_expiry": 200,
   "renewal_due": false,
   "open_renewal_id": null,
   "reports_occupancy": true,
   "api_keys_active": 1
  },
  "... 1 more"
 ],
 "applications": [
  {
   "id": "APP-000002",
   "kind": "new",
   "status": "changes_requested",
   "business_id": null,
   "business_name": "Maple Sample Guide A02, Kedarnath",
   "type": "guide",
   "type_label": "Guide",
   "district": "rudraprayag",
   "district_name": "Rudraprayag",
   "destination_id": "kedarnath",
   "destination_name": "Kedarnath",
   "capacity": 5,
   "capacity_unit": "guests per group",
   "beds": null,
   "languages": [
    "Hindi",
    "English"
   ],
   "documents": {
    "identity_proof": true,
    "address_proof": false,
    "property_papers": false,
    "trade_licence": false,
    "fssai": false,
    "fire_noc": false,
    "guide_training": false,
    "adventure_permit": false,
    "vehicle_papers": false
   },
   "required_documents": [
    "identity_proof",
    "guide_training"
   ],
   "missing_documents": [
    "guide_training"
   ],
   "notes": null,
   "reason": "Please tick and keep ready the missing document.",
   "reg_no": null,
   "submitted_at": "2026-10-04T08:02:58.602000Z",
   "updated_at": "2026-10-05T08:02:58.602000Z",
   "decided_at": "2026-10-05T08:02:58.602000Z",
   "history": [
    {
     "at": "2026-10-04T08:02:58.602000Z",
     "action": "submitted",
     "reason": null
    },
    "... 1 more"
   ],
   "synthetic": true
  },
  "... 1 more"
 ],
 "summary": {
  "businesses": 2,
  "active": 2,
  "renewals_due": 1,
  "applications_open": 2,
  "changes_requested": 1
 }
}
```

#### `GET /api/v1/business/businesses`

Auth: business. Own businesses with renewal info.

Example -> 200

Response (abbreviated):
```json
{
 "items": [
  {
   "id": "biz_0010",
   "reg_no": "UK-HMS-RUD-00001",
   "name": "Lotus Sample Homestay 010, Kedarnath",
   "type": "homestay",
   "district": "rudraprayag",
   "destination_id": "kedarnath",
   "status": "active",
   "verified": true,
   "rating": 4.2,
   "capacity": 6,
   "beds": 12,
   "languages": [
    "Hindi",
    "English",
    "Garhwali"
   ],
   "registered_on": "2024-06-07",
   "valid_until": "2027-05-01",
   "hoi_connected": true,
   "type_label": "Homestay",
   "capacity_unit": "rooms",
   "district_name": "Rudraprayag",
   "destination_name": "Kedarnath",
   "letter": "L",
   "contact": "Contact details are shown to verified visitors in the full product (placeholder in this prototype).",
   "synthetic": true,
   "days_to_expiry": 200,
   "renewal_due": false,
   "open_renewal_id": null,
   "reports_occupancy": true,
   "api_keys_active": 1
  },
  "... 1 more"
 ],
 "total": 2
}
```

#### `GET /api/v1/business/businesses/{id}`

Auth: business (owner). One own business; stays include `occupancy_months` (last 12).

Example: `GET /api/v1/business/businesses/biz_0010` -> 200

Response (abbreviated):
```json
{
 "id": "biz_0010",
 "reg_no": "UK-HMS-RUD-00001",
 "name": "Lotus Sample Homestay 010, Kedarnath",
 "type": "homestay",
 "district": "rudraprayag",
 "destination_id": "kedarnath",
 "status": "active",
 "verified": true,
 "rating": 4.2,
 "capacity": 6,
 "beds": 12,
 "languages": [
  "Hindi",
  "English",
  "Garhwali"
 ],
 "registered_on": "2024-06-07",
 "valid_until": "2027-05-01",
 "hoi_connected": true,
 "type_label": "Homestay",
 "capacity_unit": "rooms",
 "district_name": "Rudraprayag",
 "destination_name": "Kedarnath",
 "letter": "L",
 "contact": "Contact details are shown to verified visitors in the full product (placeholder in this prototype).",
 "synthetic": true,
 "days_to_expiry": 200,
 "renewal_due": false,
 "open_renewal_id": null,
 "reports_occupancy": true,
 "api_keys_active": 1,
 "occupancy_months": [
  {
   "month": "2026-10",
   "days_reported": 12,
   "rooms_available_nights": 72,
   "occupied_room_nights": 70,
   "occupancy_pct": 97.2,
   "sources": {
    "s": 12
   }
  },
  {
   "month": "2026-09",
   "days_reported": 30,
   "rooms_available_nights": 180,
   "occupied_room_nights": 141,
   "occupancy_pct": 78.3,
   "sources": {
    "s": 30
   }
  },
  "... 10 more"
 ]
}
```

#### `POST /api/v1/business/businesses/{id}/occupancy`

Auth: business (owner). Monthly occupancy form. Spreads `occupied_room_nights` evenly across the month's days (to today for the current month), skipping days already reported by HOI ingest. 422 for future months, capacity overflow, or nights > rooms x days.

Example: `POST /api/v1/business/businesses/biz_0010/occupancy` -> 200

Request body:
```json
{
 "month": "2026-09",
 "rooms_available": 4,
 "occupied_room_nights": 60
}
```

Response (abbreviated):
```json
{
 "business_id": "biz_0010",
 "month": "2026-09",
 "days_written": 30,
 "days_skipped_ingested": 0,
 "occupancy_pct": 50.0,
 "created": 0,
 "replaced": 30,
 "unchanged": 0
}
```

#### `GET /api/v1/business/businesses/{id}/occupancy`

Auth: business (owner). Monthly occupancy history (24 months). `sources`: s=seed, m=monthly form, i=HOI ingest.

Example: `GET /api/v1/business/businesses/biz_0010/occupancy` -> 200

Response (abbreviated):
```json
{
 "business_id": "biz_0010",
 "months": [
  {
   "month": "2026-10",
   "days_reported": 12,
   "rooms_available_nights": 72,
   "occupied_room_nights": 70,
   "occupancy_pct": 97.2,
   "sources": {
    "s": 12
   }
  },
  {
   "month": "2026-09",
   "days_reported": 30,
   "rooms_available_nights": 120,
   "occupied_room_nights": 60,
   "occupancy_pct": 50.0,
   "sources": {
    "m": 30
   }
  },
  "... 22 more"
 ]
}
```

#### `POST /api/v1/business/businesses/{id}/api-keys`

Auth: business (owner, stays only). Create an ingest API key. `api_key` is returned ONCE; only its SHA-256 is stored. Max 3 active keys per business (409).

Example -> 201

Request body:
```json
{
 "label": "HOI ingest"
}
```

Response (abbreviated):
```json
{
 "id": "key_e856c965ac59",
 "business_id": "biz_0010",
 "label": "HOI ingest",
 "prefix": "uthp_xhgRZ",
 "created_at": "2026-10-13T08:02:59.821978Z",
 "last_used_at": null,
 "revoked": false,
 "api_key": "uthp_xhgRZW-fCbc9HFGVzBa-2OA29ljrrwQ_6FXK-s78AGg",
 "warning": "Copy this key now. It is shown only once and stored only as a hash."
}
```

#### `GET /api/v1/business/businesses/{id}/api-keys`

Auth: business (owner). List keys (prefix only, never the key).

Example: `GET /api/v1/business/businesses/biz_0010/api-keys` -> 200

Response (abbreviated):
```json
{
 "items": [
  {
   "id": "key_e856c965ac59",
   "business_id": "biz_0010",
   "label": "HOI ingest",
   "prefix": "uthp_xhgRZ",
   "created_at": "2026-10-13T08:02:59.821000Z",
   "last_used_at": null,
   "revoked": false
  }
 ],
 "total": 1
}
```

#### `POST /api/v1/business/businesses/{id}/renew`

Auth: business (owner). Start a renewal (opens 60 days before expiry, or after expiry). 409 if too early or one is already open; 403 if suspended. An expired business shows `pending` while under review.

Example: `POST /api/v1/business/businesses/biz_0001/renew` -> 201

Response (abbreviated):
```json
{
 "id": "APP-000021",
 "kind": "renewal",
 "status": "submitted",
 "business_id": "biz_0001",
 "business_name": "Valley Sample Hotel 001, Kedarnath",
 "type": "hotel",
 "type_label": "Hotel",
 "district": "rudraprayag",
 "district_name": "Rudraprayag",
 "destination_id": "kedarnath",
 "destination_name": "Kedarnath",
 "capacity": 58,
 "capacity_unit": "rooms",
 "beds": 116,
 "languages": [
  "Hindi",
  "English",
  "Garhwali"
 ],
 "documents": {
  "identity_proof": true,
  "address_proof": true,
  "property_papers": true,
  "trade_licence": true,
  "fssai": true,
  "fire_noc": false,
  "guide_training": false,
  "adventure_permit": false,
  "vehicle_papers": false
 },
 "required_documents": [
  "identity_proof",
  "address_proof",
  "property_papers",
  "trade_licence",
  "fssai"
 ],
 "missing_documents": [],
 "notes": null,
 "reason": null,
 "reg_no": "UK-HTL-RUD-00001",
 "submitted_at": "2026-10-13T08:03:01.152169Z",
 "updated_at": "2026-10-13T08:03:01.152169Z",
 "decided_at": null,
 "history": [
  {
   "at": "2026-10-13T08:03:01.152169Z",
   "action": "submitted",
   "reason": null
  }
 ],
 "synthetic": false
}
```

#### `POST /api/v1/business/applications`

Auth: business. New registration application (no file upload; documents are checklist ticks). Unknown languages are dropped.

Example -> 201

Request body:
```json
{
 "business_name": "My Sample Homestay, Chopta",
 "type": "homestay",
 "district": "rudraprayag",
 "destination_id": "chopta",
 "capacity": 4,
 "beds": 8,
 "languages": [
  "Hindi",
  "English",
  "Garhwali"
 ],
 "documents": {
  "identity_proof": true,
  "address_proof": true,
  "property_papers": false
 },
 "notes": "Two family rooms"
}
```

Response (abbreviated):
```json
{
 "id": "APP-000022",
 "kind": "new",
 "status": "submitted",
 "business_id": null,
 "business_name": "My Sample Homestay, Chopta",
 "type": "homestay",
 "type_label": "Homestay",
 "district": "rudraprayag",
 "district_name": "Rudraprayag",
 "destination_id": "chopta",
 "destination_name": "Chopta",
 "capacity": 4,
 "capacity_unit": "rooms",
 "beds": 8,
 "languages": [
  "Hindi",
  "English",
  "Garhwali"
 ],
 "documents": {
  "identity_proof": true,
  "address_proof": true,
  "property_papers": false,
  "trade_licence": false,
  "fssai": false,
  "fire_noc": false,
  "guide_training": false,
  "adventure_permit": false,
  "vehicle_papers": false
 },
 "required_documents": [
  "identity_proof",
  "address_proof",
  "property_papers"
 ],
 "missing_documents": [
  "property_papers"
 ],
 "notes": "Two family rooms",
 "reason": null,
 "reg_no": null,
 "submitted_at": "2026-10-13T08:03:01.152169Z",
 "updated_at": "2026-10-13T08:03:01.152169Z",
 "decided_at": null,
 "history": [
  {
   "at": "2026-10-13T08:03:01.152169Z",
   "action": "submitted",
   "reason": null
  }
 ],
 "synthetic": false
}
```

#### `GET /api/v1/business/applications`

Auth: business. Own applications, newest first.

Example -> 200

Response (abbreviated):
```json
{
 "items": [
  {
   "id": "APP-000021",
   "kind": "renewal",
   "status": "submitted",
   "business_id": "biz_0001",
   "business_name": "Valley Sample Hotel 001, Kedarnath",
   "type": "hotel",
   "type_label": "Hotel",
   "district": "rudraprayag",
   "district_name": "Rudraprayag",
   "destination_id": "kedarnath",
   "destination_name": "Kedarnath",
   "capacity": 58,
   "capacity_unit": "rooms",
   "beds": 116,
   "languages": [
    "Hindi",
    "English",
    "Garhwali"
   ],
   "documents": {
    "identity_proof": true,
    "address_proof": true,
    "property_papers": true,
    "trade_licence": true,
    "fssai": true,
    "fire_noc": false,
    "guide_training": false,
    "adventure_permit": false,
    "vehicle_papers": false
   },
   "required_documents": [
    "identity_proof",
    "address_proof",
    "property_papers",
    "trade_licence",
    "fssai"
   ],
   "missing_documents": [],
   "notes": null,
   "reason": null,
   "reg_no": "UK-HTL-RUD-00001",
   "submitted_at": "2026-10-13T08:03:01.152000Z",
   "updated_at": "2026-10-13T08:03:01.152000Z",
   "decided_at": null,
   "history": [
    {
     "at": "2026-10-13T08:03:01.152000Z",
     "action": "submitted",
     "reason": null
    }
   ],
   "synthetic": false
  },
  "... 3 more"
 ],
 "total": 4
}
```

#### `GET /api/v1/business/applications/{id}`

Auth: business (owner). One own application.

Example: `GET /api/v1/business/applications/APP-000002` -> 200

Response (abbreviated):
```json
{
 "id": "APP-000002",
 "kind": "new",
 "status": "changes_requested",
 "business_id": null,
 "business_name": "Maple Sample Guide A02, Kedarnath",
 "type": "guide",
 "type_label": "Guide",
 "district": "rudraprayag",
 "district_name": "Rudraprayag",
 "destination_id": "kedarnath",
 "destination_name": "Kedarnath",
 "capacity": 5,
 "capacity_unit": "guests per group",
 "beds": null,
 "languages": [
  "Hindi",
  "English"
 ],
 "documents": {
  "identity_proof": true,
  "address_proof": false,
  "property_papers": false,
  "trade_licence": false,
  "fssai": false,
  "fire_noc": false,
  "guide_training": false,
  "adventure_permit": false,
  "vehicle_papers": false
 },
 "required_documents": [
  "identity_proof",
  "guide_training"
 ],
 "missing_documents": [
  "guide_training"
 ],
 "notes": null,
 "reason": "Please tick and keep ready the missing document.",
 "reg_no": null,
 "submitted_at": "2026-10-04T08:02:58.602000Z",
 "updated_at": "2026-10-05T08:02:58.602000Z",
 "decided_at": "2026-10-05T08:02:58.602000Z",
 "history": [
  {
   "at": "2026-10-04T08:02:58.602000Z",
   "action": "submitted",
   "reason": null
  },
  {
   "at": "2026-10-05T08:02:58.602000Z",
   "action": "changes_requested",
   "reason": "Please tick and keep ready the missing document."
  }
 ],
 "synthetic": true
}
```

#### `PUT /api/v1/business/applications/{id}`

Auth: business (owner). Edit an application in `changes_requested` and resubmit it (status back to `submitted`). Send only the fields to change. 409 in other states.

Example: `PUT /api/v1/business/applications/APP-000002` -> 200

Request body:
```json
{
 "documents": {
  "identity_proof": true,
  "guide_training": true
 }
}
```

Response (abbreviated):
```json
{
 "id": "APP-000002",
 "kind": "new",
 "status": "submitted",
 "business_id": null,
 "business_name": "Maple Sample Guide A02, Kedarnath",
 "type": "guide",
 "type_label": "Guide",
 "district": "rudraprayag",
 "district_name": "Rudraprayag",
 "destination_id": "kedarnath",
 "destination_name": "Kedarnath",
 "capacity": 5,
 "capacity_unit": "guests per group",
 "beds": null,
 "languages": [
  "Hindi",
  "English"
 ],
 "documents": {
  "identity_proof": true,
  "address_proof": false,
  "property_papers": false,
  "trade_licence": false,
  "fssai": false,
  "fire_noc": false,
  "guide_training": true,
  "adventure_permit": false,
  "vehicle_papers": false
 },
 "required_documents": [
  "identity_proof",
  "guide_training"
 ],
 "missing_documents": [],
 "notes": null,
 "reason": null,
 "reg_no": null,
 "submitted_at": "2026-10-04T08:02:58.602000Z",
 "updated_at": "2026-10-13T08:03:01.184000Z",
 "decided_at": "2026-10-05T08:02:58.602000Z",
 "history": [
  {
   "at": "2026-10-04T08:02:58.602000Z",
   "action": "submitted",
   "reason": null
  },
  {
   "at": "2026-10-05T08:02:58.602000Z",
   "action": "changes_requested",
   "reason": "Please tick and keep ready the missing document."
  },
  "... 1 more"
 ],
 "synthetic": true
}
```

#### `DELETE /api/v1/business/businesses/{id}/api-keys/{key_id}`

Auth: business (owner). Revoke a key (kept, `revoked: true`).

Example: `DELETE /api/v1/business/businesses/biz_0010/api-keys/key_e856c965ac59` -> 200

Response (abbreviated):
```json
{
 "id": "key_e856c965ac59",
 "business_id": "biz_0010",
 "label": "HOI ingest",
 "prefix": "uthp_xhgRZ",
 "created_at": "2026-10-13T08:02:59.821000Z",
 "last_used_at": null,
 "revoked": true
}
```

### HOI ingest (API key)

#### `POST /api/v1/ingest/occupancy`

Auth: `X-API-Key: uthp_...` (120/min/IP). Daily occupancy from HOI-run stays. Idempotent per (business, date): `result` is `created`, `replaced` or `unchanged`. 401 for a missing/wrong/revoked key; 403 if the registration is not active; 422 for future dates, > 400 days old, rooms_available > capacity, occupied > available, staff_flagged > staff_count.

Example -> 200

Request body:
```json
{
 "date": "2026-10-12",
 "rooms_available": 4,
 "rooms_occupied": 3,
 "staff_count": 7,
 "staff_flagged": 1
}
```

Response (abbreviated):
```json
{
 "business_id": "biz_0010",
 "reg_no": "UK-HMS-RUD-00001",
 "date": "2026-10-12",
 "result": "replaced",
 "occupancy_pct": 75.0
}
```

### Officials: applications (district_officer scoped, state_admin all)

#### `GET /api/v1/officer/applications`

Auth: district_officer / state_admin. Queue, oldest first. `counts` per status in scope.

Query/body fields: `district` (admin; officer may only pass own), `status`, `kind` (new|renewal), `page`, `page_size`

Example: `GET /api/v1/officer/applications?status=submitted` -> 200

Response (abbreviated):
```json
{
 "items": [
  {
   "id": "APP-000001",
   "kind": "new",
   "status": "submitted",
   "business_id": null,
   "business_name": "Cedar Sample Homestay A01, Kedarnath",
   "type": "homestay",
   "type_label": "Homestay",
   "district": "rudraprayag",
   "district_name": "Rudraprayag",
   "destination_id": "kedarnath",
   "destination_name": "Kedarnath",
   "capacity": 2,
   "capacity_unit": "rooms",
   "beds": null,
   "languages": [
    "Hindi",
    "English"
   ],
   "documents": {
    "identity_proof": true,
    "address_proof": true,
    "property_papers": true,
    "trade_licence": false,
    "fssai": false,
    "fire_noc": false,
    "guide_training": false,
    "adventure_permit": false,
    "vehicle_papers": false
   },
   "required_documents": [
    "identity_proof",
    "address_proof",
    "property_papers"
   ],
   "missing_documents": [],
   "notes": null,
   "reason": null,
   "reg_no": null,
   "submitted_at": "2026-09-17T08:02:58.602000Z",
   "updated_at": "2026-09-17T08:02:58.602000Z",
   "decided_at": null,
   "history": [
    {
     "at": "2026-09-17T08:02:58.602000Z",
     "action": "submitted",
     "reason": null,
     "by": "usr_0db892e409c2"
    }
   ],
   "synthetic": true,
   "owner_user_id": "usr_0db892e409c2"
  },
  "... 5 more"
 ],
 "total": 6,
 "page": 1,
 "page_size": 50,
 "counts": {
  "submitted": 6,
  "changes_requested": 1,
  "approved": 0,
  "rejected": 0
 }
}
```

#### `GET /api/v1/officer/applications/{id}`

Auth: official. One application (404 outside the officer's district).

Example: `GET /api/v1/officer/applications/APP-000001` -> 200

Response (abbreviated):
```json
{
 "id": "APP-000001",
 "kind": "new",
 "status": "submitted",
 "business_id": null,
 "business_name": "Cedar Sample Homestay A01, Kedarnath",
 "type": "homestay",
 "type_label": "Homestay",
 "district": "rudraprayag",
 "district_name": "Rudraprayag",
 "destination_id": "kedarnath",
 "destination_name": "Kedarnath",
 "capacity": 2,
 "capacity_unit": "rooms",
 "beds": null,
 "languages": [
  "Hindi",
  "English"
 ],
 "documents": {
  "identity_proof": true,
  "address_proof": true,
  "property_papers": true,
  "trade_licence": false,
  "fssai": false,
  "fire_noc": false,
  "guide_training": false,
  "adventure_permit": false,
  "vehicle_papers": false
 },
 "required_documents": [
  "identity_proof",
  "address_proof",
  "property_papers"
 ],
 "missing_documents": [],
 "notes": null,
 "reason": null,
 "reg_no": null,
 "submitted_at": "2026-09-17T08:02:58.602000Z",
 "updated_at": "2026-09-17T08:02:58.602000Z",
 "decided_at": null,
 "history": [
  {
   "at": "2026-09-17T08:02:58.602000Z",
   "action": "submitted",
   "reason": null,
   "by": "usr_0db892e409c2"
  }
 ],
 "synthetic": true,
 "owner_user_id": "usr_0db892e409c2"
}
```

#### `POST /api/v1/officer/applications/{id}/decision`

Auth: official. `action`: approve | request_changes | reject. `reason` required unless approving. Approve needs every required document ticked (422) and issues `reg_no` UK-<TYPE>-<DISTRICT>-<NNNNN> (new) or extends `valid_until` by a year (renewal). 409 if not `submitted`.

Example: `POST /api/v1/officer/applications/APP-000001/decision` -> 200

Request body:
```json
{
 "action": "approve",
 "reason": null
}
```

Response (abbreviated):
```json
{
 "id": "APP-000001",
 "kind": "new",
 "status": "approved",
 "business_id": "biz_00004_000001",
 "business_name": "Cedar Sample Homestay A01, Kedarnath",
 "type": "homestay",
 "type_label": "Homestay",
 "district": "rudraprayag",
 "district_name": "Rudraprayag",
 "destination_id": "kedarnath",
 "destination_name": "Kedarnath",
 "capacity": 2,
 "capacity_unit": "rooms",
 "beds": null,
 "languages": [
  "Hindi",
  "English"
 ],
 "documents": {
  "identity_proof": true,
  "address_proof": true,
  "property_papers": true,
  "trade_licence": false,
  "fssai": false,
  "fire_noc": false,
  "guide_training": false,
  "adventure_permit": false,
  "vehicle_papers": false
 },
 "required_documents": [
  "identity_proof",
  "address_proof",
  "property_papers"
 ],
 "missing_documents": [],
 "notes": null,
 "reason": null,
 "reg_no": "UK-HMS-RUD-00004",
 "submitted_at": "2026-09-17T08:02:58.602000Z",
 "updated_at": "2026-10-13T08:03:01.263000Z",
 "decided_at": "2026-10-13T08:03:01.263000Z",
 "history": [
  {
   "at": "2026-09-17T08:02:58.602000Z",
   "action": "submitted",
   "reason": null,
   "by": "usr_0db892e409c2"
  },
  {
   "at": "2026-10-13T08:03:01.263000Z",
   "action": "approved",
   "reason": null,
   "by": "demo.officer.rudraprayag"
  }
 ],
 "synthetic": true,
 "owner_user_id": "usr_0db892e409c2"
}
```

### Officials: grievances

#### `GET /api/v1/officer/grievances`

Auth: official. Grievances with private details. Also returns `open` and `overdue` counts.

Query/body fields: `district`, `status` (a status or `open`), `overdue` (true|false), `category`, `page`, `page_size`

Example: `GET /api/v1/officer/grievances?status=open` -> 200

Response (abbreviated):
```json
{
 "items": [
  {
   "ticket_id": "UTHP-G-000041",
   "category": "overcharging",
   "category_label": "Overcharging / price not as displayed",
   "district": "rudraprayag",
   "district_name": "Rudraprayag",
   "business_reg_no": null,
   "status": "received",
   "created_at": "2026-10-13T08:02:59.808000Z",
   "updated_at": "2026-10-13T08:02:59.808000Z",
   "sla_due_at": "2026-10-20T08:02:59.808000Z",
   "sla_days": 7,
   "overdue": false,
   "resolved_at": null,
   "timeline": [
    {
     "status": "received",
     "at": "2026-10-13T08:02:59.808000Z",
     "note": "Grievance received.",
     "by": "system",
     "public": true
    }
   ],
   "synthetic": false,
   "description": "Taxi charged more than the agreed fare.",
   "contact": "optional, kept private",
   "assigned_to": null,
   "business_id": null
  },
  "... 3 more"
 ],
 "total": 4,
 "page": 1,
 "page_size": 50,
 "open": 4,
 "overdue": 2
}
```

#### `GET /api/v1/officer/grievances/{ticket_id}`

Auth: official. One grievance incl. description and contact.

Example: `GET /api/v1/officer/grievances/UTHP-G-000023` -> 200

Response (abbreviated):
```json
{
 "ticket_id": "UTHP-G-000023",
 "category": "safety",
 "category_label": "Safety concern",
 "district": "rudraprayag",
 "district_name": "Rudraprayag",
 "business_reg_no": null,
 "status": "received",
 "created_at": "2026-09-18T23:02:59.388000Z",
 "updated_at": "2026-09-18T23:02:59.388000Z",
 "sla_due_at": "2026-09-25T23:02:59.388000Z",
 "sla_days": 7,
 "overdue": true,
 "resolved_at": null,
 "timeline": [
  {
   "status": "received",
   "at": "2026-09-18T23:02:59.388000Z",
   "note": "Grievance received.",
   "by": "system",
   "public": true
  }
 ],
 "synthetic": true,
 "description": "Sample grievance about safety concern (synthetic text for the prototype).",
 "contact": null,
 "assigned_to": null,
 "business_id": null
}
```

#### `POST /api/v1/officer/grievances/{ticket_id}`

Auth: official. Update: any of `status`, `note`, `public` (default true; false = internal note), `assign_to`. Transitions: received->assigned|in_progress|resolved|closed, assigned->in_progress|resolved|closed, in_progress->resolved|closed, resolved->closed|in_progress. Resolving/closing needs a note. 409 for an invalid transition.

Example: `POST /api/v1/officer/grievances/UTHP-G-000041` -> 200

Request body:
```json
{
 "status": "in_progress",
 "note": "Contacted the operator.",
 "public": true
}
```

Response (abbreviated):
```json
{
 "ticket_id": "UTHP-G-000041",
 "category": "overcharging",
 "category_label": "Overcharging / price not as displayed",
 "district": "rudraprayag",
 "district_name": "Rudraprayag",
 "business_reg_no": null,
 "status": "in_progress",
 "created_at": "2026-10-13T08:02:59.808000Z",
 "updated_at": "2026-10-13T08:03:01.280000Z",
 "sla_due_at": "2026-10-20T08:02:59.808000Z",
 "sla_days": 7,
 "overdue": false,
 "resolved_at": null,
 "timeline": [
  {
   "status": "received",
   "at": "2026-10-13T08:02:59.808000Z",
   "note": "Grievance received.",
   "by": "system",
   "public": true
  },
  {
   "status": "in_progress",
   "at": "2026-10-13T08:03:01.280000Z",
   "note": "Contacted the operator.",
   "by": "demo.officer.rudraprayag",
   "public": true
  }
 ],
 "synthetic": false,
 "description": "Taxi charged more than the agreed fare.",
 "contact": "optional, kept private",
 "assigned_to": null,
 "business_id": null
}
```

### Officials: advisories and events

#### `GET /api/v1/officer/advisories`

Auth: official. All advisories in scope incl. expired (max 200).

Example -> 200

Response (abbreviated):
```json
{
 "items": [
  {
   "id": "adv_sample01",
   "kind": "road",
   "status": "caution",
   "district": "rudraprayag",
   "district_name": "Rudraprayag",
   "destination_id": "kedarnath",
   "destination_name": "Kedarnath",
   "segment": "Gaurikund approach",
   "title": "SAMPLE: slow traffic near Gaurikund",
   "reason": "Illustrative sample advisory for the prototype; not real road status.",
   "posted_at": "2026-10-12T07:02:59.683000Z",
   "expires_at": "2026-10-19T08:02:59.683000Z",
   "active": true,
   "sample": true,
   "posted_by_role": "district_officer"
  },
  "... 1 more"
 ],
 "total": 2
}
```

#### `POST /api/v1/officer/advisories`

Auth: official. Post an advisory. Officers post for their own district (403 for another); state admin must pass `district`. Road advisories need `status`. `expires_at` default +3 days, max +60 days.

Example -> 201

Request body:
```json
{
 "kind": "road",
 "status": "caution",
 "title": "Caution near Gaurikund",
 "segment": "Gaurikund approach",
 "reason": "Slow traffic",
 "destination_id": "kedarnath",
 "expires_at": "2026-10-15T08:03:01.280558Z"
}
```

Response (abbreviated):
```json
{
 "id": "adv_4bb87604e9",
 "kind": "road",
 "status": "caution",
 "district": "rudraprayag",
 "district_name": "Rudraprayag",
 "destination_id": "kedarnath",
 "destination_name": "Kedarnath",
 "segment": "Gaurikund approach",
 "title": "Caution near Gaurikund",
 "reason": "Slow traffic",
 "posted_at": "2026-10-13T08:03:01.295217Z",
 "expires_at": "2026-10-15T08:03:01.280558Z",
 "active": true,
 "sample": false,
 "posted_by_role": "district_officer"
}
```

#### `PATCH /api/v1/officer/advisories/{id}`

Auth: official. Update fields.

Example: `PATCH /api/v1/officer/advisories/adv_4bb87604e9` -> 200

Request body:
```json
{
 "status": "closed",
 "reason": "Road closed for clearance"
}
```

Response (abbreviated):
```json
{
 "id": "adv_4bb87604e9",
 "kind": "road",
 "status": "closed",
 "district": "rudraprayag",
 "district_name": "Rudraprayag",
 "destination_id": "kedarnath",
 "destination_name": "Kedarnath",
 "segment": "Gaurikund approach",
 "title": "Caution near Gaurikund",
 "reason": "Road closed for clearance",
 "posted_at": "2026-10-13T08:03:01.295000Z",
 "expires_at": "2026-10-15T08:03:01.280000Z",
 "active": true,
 "sample": false,
 "posted_by_role": "district_officer"
}
```

#### `DELETE /api/v1/officer/advisories/{id}`

Auth: official. Withdraw now (sets `expires_at` to now; record kept).

Example: `DELETE /api/v1/officer/advisories/adv_4bb87604e9` -> 200

Response (abbreviated):
```json
{
 "id": "adv_4bb87604e9",
 "kind": "road",
 "status": "closed",
 "district": "rudraprayag",
 "district_name": "Rudraprayag",
 "destination_id": "kedarnath",
 "destination_name": "Kedarnath",
 "segment": "Gaurikund approach",
 "title": "Caution near Gaurikund",
 "reason": "Road closed for clearance",
 "posted_at": "2026-10-13T08:03:01.295000Z",
 "expires_at": "2026-10-13T08:03:01.300000Z",
 "active": false,
 "sample": false,
 "posted_by_role": "district_officer"
}
```

#### `POST /api/v1/officer/events`

Auth: official. Post a dated event (feeds the calendar and crowd estimate). State admin passes `district`.

Example -> 201

Request body:
```json
{
 "name": "Trail clean-up drive",
 "description": "Volunteers welcome.",
 "start_date": "2026-11-02",
 "end_date": "2026-11-03",
 "destination_ids": [
  "chopta"
 ],
 "crowd_impact": "low"
}
```

Response (abbreviated):
```json
{
 "id": "evt_441b89696e",
 "name": "Trail clean-up drive",
 "kind": "event",
 "months": [
  11
 ],
 "window": "2026-11-02 to 2026-11-03",
 "districts": [
  "rudraprayag"
 ],
 "destination_ids": [
  "chopta"
 ],
 "crowd_impact": "low",
 "description": "Volunteers welcome.",
 "date_note": "Posted by the district tourism office.",
 "start_date": "2026-11-02",
 "end_date": "2026-11-03",
 "curated": false,
 "sample": false,
 "district_names": [
  "Rudraprayag"
 ],
 "destination_names": [
  "Chopta"
 ],
 "statewide": false,
 "updated_at": "2026-10-13T08:03:01.300018Z"
}
```

#### `GET /api/v1/officer/events`

Auth: official. Officer-posted events in scope (curated festivals are not editable).

Example -> 200

Response (abbreviated):
```json
{
 "items": [
  {
   "id": "evt_441b89696e",
   "name": "Trail clean-up drive",
   "kind": "event",
   "months": [
    11
   ],
   "window": "2026-11-02 to 2026-11-03",
   "districts": [
    "rudraprayag"
   ],
   "destination_ids": [
    "chopta"
   ],
   "crowd_impact": "low",
   "description": "Volunteers welcome.",
   "date_note": "Posted by the district tourism office.",
   "start_date": "2026-11-02",
   "end_date": "2026-11-03",
   "curated": false,
   "sample": false,
   "district_names": [
    "Rudraprayag"
   ],
   "destination_names": [
    "Chopta"
   ],
   "statewide": false,
   "updated_at": "2026-10-13T08:03:01.300000Z"
  },
  "... 1 more"
 ],
 "total": 2
}
```

#### `PATCH /api/v1/officer/events/{id}`

Auth: official. Update fields.

Example: `PATCH /api/v1/officer/events/evt_441b89696e` -> 200

Request body:
```json
{
 "crowd_impact": "medium"
}
```

Response (abbreviated):
```json
{
 "id": "evt_441b89696e",
 "name": "Trail clean-up drive",
 "kind": "event",
 "months": [
  11
 ],
 "window": "2026-11-02 to 2026-11-03",
 "districts": [
  "rudraprayag"
 ],
 "destination_ids": [
  "chopta"
 ],
 "crowd_impact": "medium",
 "description": "Volunteers welcome.",
 "date_note": "Posted by the district tourism office.",
 "start_date": "2026-11-02",
 "end_date": "2026-11-03",
 "curated": false,
 "sample": false,
 "district_names": [
  "Rudraprayag"
 ],
 "destination_names": [
  "Chopta"
 ],
 "statewide": false,
 "updated_at": "2026-10-13T08:03:01.309000Z"
}
```

#### `DELETE /api/v1/officer/events/{id}`

Auth: official. Delete. 204.

Example: `DELETE /api/v1/officer/events/evt_441b89696e` -> 204

### Officials: businesses

#### `GET /api/v1/officer/businesses`

Auth: official. Registry view in scope (same shape as /registry).

Query/body fields: `district`, `status`, `type`, `q`, `page`, `page_size`

Example: `GET /api/v1/officer/businesses?status=expired&page_size=1` -> 200

Response (abbreviated):
```json
{
 "items": [],
 "total": 0,
 "page": 1,
 "page_size": 1,
 "letters": [
  "A",
  "B",
  "... 23 more"
 ],
 "synthetic": true
}
```

#### `POST /api/v1/officer/businesses/{id}/status`

Auth: official. Suspend or reinstate (`active` only from `suspended`).

Example: `POST /api/v1/officer/businesses/biz_0004/status` -> 200

Request body:
```json
{
 "status": "suspended",
 "reason": "Safety inspection pending"
}
```

Response (abbreviated):
```json
{
 "id": "biz_0004",
 "reg_no": "UK-HTL-RUD-00003",
 "name": "Elm Sample Hotel 004, Kedarnath",
 "type": "hotel",
 "district": "rudraprayag",
 "destination_id": "kedarnath",
 "status": "suspended",
 "verified": false,
 "rating": 4.1,
 "capacity": 47,
 "beds": 141,
 "languages": [
  "Hindi",
  "English"
 ],
 "registered_on": "2023-09-20",
 "valid_until": "2027-09-20",
 "hoi_connected": false,
 "type_label": "Hotel",
 "capacity_unit": "rooms",
 "district_name": "Rudraprayag",
 "destination_name": "Kedarnath",
 "letter": "E",
 "contact": "Contact details are shown to verified visitors in the full product (placeholder in this prototype).",
 "synthetic": true
}
```

### Analytics (official; officer = own district, admin = state or `?district=`)

#### `GET /api/v1/analytics/kpis`

Auth: official. KPI tiles + businesses by status + crowd alerts (outlook >= 85 within 14 days).

Example -> 200

Response (abbreviated):
```json
{
 "synthetic": true,
 "note": "SYNTHETIC data generated for a hackathon concept prototype. Not official statistics.",
 "scope": {
  "district": null,
  "district_name": "All districts (state)"
 },
 "generated_at": "2026-10-13T08:03:01.412275Z",
 "kpis": [
  {
   "key": "registered_businesses",
   "label": "Registered businesses (active)",
   "value": 264
  },
  {
   "key": "active_rooms",
   "label": "Active rooms",
   "value": 3422
  },
  {
   "key": "active_beds",
   "label": "Active beds",
   "value": 8085
  },
  {
   "key": "applications_pending",
   "label": "Applications pending review",
   "value": 13
  },
  {
   "key": "grievances_open",
   "label": "Grievances open",
   "value": 19
  },
  {
   "key": "grievances_overdue",
   "label": "Grievances past 7-day SLA",
   "value": 14
  },
  {
   "key": "avg_occupancy_30d",
   "label": "Average occupancy, last 30 days",
   "value": 65.2,
   "unit": "%"
  },
  {
   "key": "crowd_alerts",
   "label": "Destinations with very high crowd outlook (14 days)",
   "value": 4
  }
 ],
 "businesses_by_status": {
  "active": 264,
  "expired": 26,
  "suspended": 12,
  "pending": 3
 },
 "crowd_alerts": [
  {
   "destination_id": "yamunotri",
   "name": "Yamunotri",
   "peak_index": 96,
   "peak_date": "2026-10-17"
  },
  {
   "destination_id": "badrinath",
   "name": "Badrinath",
   "peak_index": 94,
   "peak_date": "2026-10-17"
  },
  {
   "destination_id": "gangotri",
   "name": "Gangotri",
   "peak_index": 93,
   "peak_date": "2026-10-24"
  },
  {
   "destination_id": "kedarnath",
   "name": "Kedarnath",
   "peak_index": 90,
   "peak_date": "2026-10-17"
  }
 ]
}
```

#### `GET /api/v1/analytics/rush`

Auth: official. Heatmap destination x week (8 past + current + 7 outlook weeks, weekly mean index), top busiest (next 14 days), daily alerts >= 85.

Query/body fields: `district`, `top` (1-24, default 10)

Example -> 200

Response (abbreviated):
```json
{
 "synthetic": true,
 "note": "SYNTHETIC data generated for a hackathon concept prototype. Not official statistics.",
 "scope": {
  "district": null,
  "district_name": "All districts (state)"
 },
 "generated_at": "2026-10-13T08:03:01.470040Z",
 "label": "estimate",
 "bands": [
  {
   "key": "low",
   "label": "Low",
   "min": 0,
   "max": 39
  },
  {
   "key": "moderate",
   "label": "Moderate",
   "min": 40,
   "max": 64
  },
  "... 2 more"
 ],
 "heatmap": {
  "weeks": [
   "2026-08-17",
   "2026-08-24",
   "... 14 more"
  ],
  "week_kind": [
   "past",
   "past",
   "... 14 more"
  ],
  "rows": [
   {
    "destination_id": "kedarnath",
    "name": "Kedarnath",
    "district": "rudraprayag",
    "values": [
     37,
     37,
     52,
     56,
     56,
     56,
     "... 10 more"
    ]
   },
   {
    "destination_id": "badrinath",
    "name": "Badrinath",
    "district": "chamoli",
    "values": [
     40,
     40,
     55,
     59,
     59,
     59,
     "... 10 more"
    ]
   },
   "... 22 more"
  ]
 },
 "top": [
  {
   "destination_id": "yamunotri",
   "name": "Yamunotri",
   "avg_index_14d": 92,
   "band": "very_high",
   "peak_index": 96,
   "peak_date": "2026-10-17"
  },
  {
   "destination_id": "badrinath",
   "name": "Badrinath",
   "avg_index_14d": 90,
   "band": "very_high",
   "peak_index": 94,
   "peak_date": "2026-10-17"
  },
  "... 8 more"
 ],
 "alerts": [
  {
   "destination_id": "yamunotri",
   "name": "Yamunotri",
   "date": "2026-10-13",
   "index": 91,
   "events": [
    "Char Dham closing"
   ]
  },
  {
   "destination_id": "badrinath",
   "name": "Badrinath",
   "date": "2026-10-13",
   "index": 89,
   "events": [
    "Char Dham closing"
   ]
  },
  "... 52 more"
 ],
 "alert_threshold": 85
}
```

#### `GET /api/v1/analytics/occupancy`

Auth: official. Occupancy % trend: overall, by district, by stay type. `values[i]` belongs to `dates[i]` (bucket start); null = no data.

Query/body fields: `district`, `type` (hotel|homestay), `days` (7-730, default 365), `granularity` (daily|weekly|monthly)

Example: `GET /api/v1/analytics/occupancy?granularity=monthly&days=365` -> 200

Response (abbreviated):
```json
{
 "synthetic": true,
 "note": "SYNTHETIC data generated for a hackathon concept prototype. Not official statistics.",
 "scope": {
  "district": null,
  "district_name": "All districts (state)"
 },
 "generated_at": "2026-10-13T08:03:01.485818Z",
 "unit": "%",
 "granularity": "monthly",
 "type": null,
 "dates": [
  "2025-10-13",
  "2025-11-01",
  "... 11 more"
 ],
 "overall": {
  "key": "state",
  "label": "State",
  "values": [
   72.8,
   61.5,
   64.6,
   53.6,
   49.3,
   54.6,
   "... 7 more"
  ]
 },
 "by_district": [
  {
   "key": "almora",
   "label": "Almora",
   "values": [
    64.8,
    61.4,
    58.0,
    53.1,
    53.1,
    57.5,
    "... 7 more"
   ]
  },
  {
   "key": "bageshwar",
   "label": "Bageshwar",
   "values": [
    65.1,
    59.7,
    66.3,
    54.9,
    46.0,
    50.6,
    "... 7 more"
   ]
  },
  "... 11 more"
 ],
 "by_type": [
  {
   "key": "hotel",
   "label": "Hotel",
   "values": [
    72.8,
    61.5,
    64.2,
    53.4,
    49.0,
    54.4,
    "... 7 more"
   ]
  },
  {
   "key": "homestay",
   "label": "Homestay",
   "values": [
    72.6,
    61.5,
    68.1,
    56.4,
    53.0,
    57.0,
    "... 7 more"
   ]
  }
 ]
}
```

#### `GET /api/v1/analytics/market`

Auth: official. SYNTHETIC tourist arrivals and registrations by year (2019-2026) and district with YoY %. Current year is partial (no YoY).

Example -> 200

Response (abbreviated):
```json
{
 "synthetic": true,
 "note": "SYNTHETIC data generated for a hackathon concept prototype. Not official statistics.",
 "scope": {
  "district": null,
  "district_name": "All districts (state)"
 },
 "generated_at": "2026-10-13T08:03:01.485818Z",
 "label": "SYNTHETIC",
 "years": [
  2019,
  2020,
  2021,
  2022,
  2023,
  2024,
  "... 2 more"
 ],
 "totals": [
  {
   "year": 2019,
   "domestic": 14600000,
   "foreign": 287713,
   "total": 14887713,
   "yoy_pct": null,
   "partial_year": false,
   "registrations": 21,
   "registrations_yoy_pct": null
  },
  {
   "year": 2020,
   "domestic": 15784895,
   "foreign": 265873,
   "total": 16050768,
   "yoy_pct": 7.8,
   "partial_year": false,
   "registrations": 23,
   "registrations_yoy_pct": 9.5
  },
  "... 6 more"
 ],
 "by_district": [
  {
   "key": "almora",
   "label": "Almora",
   "arrivals": [
    606021,
    659200,
    717816,
    752678,
    773363,
    803783,
    "... 2 more"
   ],
   "registrations": [
    2,
    1,
    1,
    0,
    2,
    2,
    "... 2 more"
   ],
   "latest_full_year_yoy_pct": 7.2
  },
  {
   "key": "bageshwar",
   "label": "Bageshwar",
   "arrivals": [
    304247,
    315494,
    340201,
    354470,
    366499,
    411767,
    "... 2 more"
   ],
   "registrations": [
    3,
    1,
    0,
    1,
    1,
    3,
    "... 2 more"
   ],
   "latest_full_year_yoy_pct": 6.3
  },
  "... 11 more"
 ],
 "partial_year_note": "The current year is partial (months to date); YoY is not computed for it."
}
```

#### `GET /api/v1/analytics/registrations`

Auth: official. New registrations and applications submitted per month.

Query/body fields: `district`, `months` (1-60, default 24)

Example: `GET /api/v1/analytics/registrations?months=12` -> 200

Response (abbreviated):
```json
{
 "synthetic": true,
 "note": "SYNTHETIC data generated for a hackathon concept prototype. Not official statistics.",
 "scope": {
  "district": null,
  "district_name": "All districts (state)"
 },
 "generated_at": "2026-10-13T08:03:01.505440Z",
 "months": [
  "2025-11",
  "2025-12",
  "... 10 more"
 ],
 "series": [
  {
   "key": "new_registrations",
   "label": "New registrations",
   "values": [
    3,
    1,
    5,
    3,
    4,
    4,
    "... 6 more"
   ]
  },
  {
   "key": "applications_submitted",
   "label": "Applications submitted",
   "values": [
    0,
    0,
    0,
    0,
    0,
    0,
    "... 6 more"
   ]
  }
 ]
}
```

#### `GET /api/v1/analytics/grievances`

Auth: official. Grievances by category, district and status; SLA breach rate; median resolution days.

Example -> 200

Response (abbreviated):
```json
{
 "synthetic": true,
 "note": "SYNTHETIC data generated for a hackathon concept prototype. Not official statistics.",
 "scope": {
  "district": null,
  "district_name": "All districts (state)"
 },
 "generated_at": "2026-10-13T08:03:01.512296Z",
 "total": 41,
 "by_category": [
  {
   "key": "overcharging",
   "label": "Overcharging / price not as displayed",
   "count": 9
  },
  {
   "key": "cleanliness",
   "label": "Cleanliness / hygiene",
   "count": 3
  },
  {
   "key": "safety",
   "label": "Safety concern",
   "count": 6
  },
  "... 6 more"
 ],
 "by_district": [
  {
   "key": "almora",
   "label": "Almora",
   "count": 0
  },
  {
   "key": "bageshwar",
   "label": "Bageshwar",
   "count": 2
  },
  {
   "key": "chamoli",
   "label": "Chamoli",
   "count": 3
  },
  "... 10 more"
 ],
 "by_status": [
  {
   "key": "received",
   "count": 7
  },
  {
   "key": "assigned",
   "count": 0
  },
  {
   "key": "in_progress",
   "count": 12
  },
  "... 2 more"
 ],
 "sla_days": 7,
 "sla_breach_rate_pct": 65.9,
 "sla_breached": 27,
 "median_resolution_days": 7.5,
 "resolved_count": 22
}
```

#### `GET /api/v1/analytics/workforce`

Auth: official. HOI workforce aggregates for the latest complete month, k-anonymity: a group with fewer than 5 contributing businesses is suppressed with a reason (no numbers).

Query/body fields: `district`, `group_by` (district|type)

Example: `GET /api/v1/analytics/workforce?group_by=district` -> 200

Response (abbreviated):
```json
{
 "synthetic": true,
 "note": "SYNTHETIC data generated for a hackathon concept prototype. Not official statistics.",
 "scope": {
  "district": null,
  "district_name": "All districts (state)"
 },
 "generated_at": "2026-10-13T08:03:01.569119Z",
 "k_min": 5,
 "group_by": "district",
 "month": "2026-09",
 "months_in_turnover": 12,
 "source": "HOI-connected stays (aggregated). Never per person or per business.",
 "overall": {
  "suppressed": false,
  "businesses": 92,
  "staff_total": 1320,
  "roles": {
   "housekeeping": 420,
   "front_office": 156,
   "food_beverage": 292,
   "maintenance": 100,
   "other": 352
  },
  "flagged_share_pct": 7.6,
  "turnover_pct_12m": 35.2
 },
 "groups": [
  {
   "key": "almora",
   "label": "Almora",
   "suppressed": false,
   "businesses": 5,
   "staff_total": 48,
   "roles": {
    "housekeeping": 14,
    "front_office": 5,
    "food_beverage": 10,
    "maintenance": 3,
    "other": 16
   },
   "flagged_share_pct": 12.5,
   "turnover_pct_12m": 43.2
  },
  {
   "key": "bageshwar",
   "label": "Bageshwar",
   "suppressed": true,
   "reason": "Fewer than 5 businesses contribute to this group, so figures are hidden to protect privacy (k-anonymity)."
  },
  {
   "key": "chamoli",
   "label": "Chamoli",
   "suppressed": false,
   "businesses": 6,
   "staff_total": 41,
   "roles": {
    "housekeeping": 11,
    "front_office": 4,
    "food_beverage": 7,
    "maintenance": 2,
    "other": 17
   },
   "flagged_share_pct": 9.8,
   "turnover_pct_12m": 26.2
  },
  {
   "key": "champawat",
   "label": "Champawat",
   "suppressed": true,
   "reason": "Fewer than 5 businesses contribute to this group, so figures are hidden to protect privacy (k-anonymity)."
  },
  {
   "key": "dehradun",
   "label": "Dehradun",
   "suppressed": false,
   "businesses": 22,
   "staff_total": 308,
   "roles": {
    "housekeeping": 97,
    "front_office": 34,
    "food_beverage": 68,
    "maintenance": 22,
    "other": 87
   },
   "flagged_share_pct": 8.1,
   "turnover_pct_12m": 31.2
  },
  {
   "key": "haridwar",
   "label": "Haridwar",
   "suppressed": false,
   "businesses": 10,
   "staff_total": 182,
   "roles": {
    "housekeeping": 60,
    "front_office": 23,
    "food_beverage": 40,
    "maintenance": 15,
    "other": 44
   },
   "flagged_share_pct": 6.6,
   "turnover_pct_12m": 31.4
  },
  {
   "key": "nainital",
   "label": "Nainital",
   "suppressed": false,
   "businesses": 16,
   "staff_total": 264,
   "roles": {
    "housekeeping": 86,
    "front_office": 31,
    "food_beverage": 60,
    "maintenance": 21,
    "other": 66
   },
   "flagged_share_pct": 7.6,
   "turnover_pct_12m": 35.6
  },
  {
   "key": "pauri-garhwal",
   "label": "Pauri Garhwal",
   "suppressed": true,
   "reason": "Fewer than 5 businesses contribute to this group, so figures are hidden to protect privacy (k-anonymity)."
  },
  {
   "key": "pithoragarh",
   "label": "Pithoragarh",
   "suppressed": true,
   "reason": "Fewer than 5 businesses contribute to this group, so figures are hidden to protect privacy (k-anonymity)."
  },
  {
   "key": "rudraprayag",
   "label": "Rudraprayag",
   "suppressed": false,
   "businesses": 6,
   "staff_total": 116,
   "roles": {
    "housekeeping": 38,
    "front_office": 15,
    "food_beverage": 27,
    "maintenance": 10,
    "other": 26
   },
   "flagged_share_pct": 6.0,
   "turnover_pct_12m": 38.7
  },
  {
   "key": "tehri-garhwal",
   "label": "Tehri Garhwal",
   "suppressed": false,
   "businesses": 5,
   "staff_total": 93,
   "roles": {
    "housekeeping": 32,
    "front_office": 12,
    "food_beverage": 21,
    "maintenance": 7,
    "other": 21
   },
   "flagged_share_pct": 7.5,
   "turnover_pct_12m": 28.1
  },
  {
   "key": "udham-singh-nagar",
   "label": "Udham Singh Nagar",
   "suppressed": true,
   "reason": "Fewer than 5 businesses contribute to this group, so figures are hidden to protect privacy (k-anonymity)."
  },
  {
   "key": "uttarkashi",
   "label": "Uttarkashi",
   "suppressed": false,
   "businesses": 7,
   "staff_total": 72,
   "roles": {
    "housekeeping": 21,
    "front_office": 9,
    "food_beverage": 15,
    "maintenance": 6,
    "other": 21
   },
   "flagged_share_pct": 9.7,
   "turnover_pct_12m": 45.4
  }
 ]
}
```

### State admin

#### `GET /api/v1/admin/users`

Auth: state_admin. Accounts.

Query/body fields: `role`

Example: `GET /api/v1/admin/users?role=district_officer` -> 200

Response (abbreviated):
```json
{
 "items": [
  {
   "id": "usr_e19036b08f52",
   "username": "demo.officer.rudraprayag",
   "role": "district_officer",
   "district": "rudraprayag",
   "label": "District tourism officer, Rudraprayag (demo)",
   "active": true,
   "created_at": "2026-10-13T08:02:57.880000Z",
   "last_login": null,
   "role_label": "District tourism officer",
   "district_name": "Rudraprayag"
  }
 ],
 "total": 1
}
```

#### `POST /api/v1/admin/officers`

Auth: state_admin. Create a district officer.

Example -> 201

Request body:
```json
{
 "username": "officer.chamoli",
 "password": "a-strong-password",
 "district": "chamoli",
 "label": "District tourism officer, Chamoli"
}
```

Response (abbreviated):
```json
{
 "id": "usr_d9c2393e14b5",
 "username": "officer.chamoli",
 "role": "district_officer",
 "district": "chamoli",
 "label": "District tourism officer, Chamoli",
 "active": true,
 "created_at": "2026-10-13T08:03:01.675538Z",
 "last_login": null,
 "role_label": "District tourism officer",
 "district_name": "Chamoli"
}
```

#### `PATCH /api/v1/admin/users/{id}`

Auth: state_admin. Enable/disable an account (disabling revokes sessions; tokens stop working at once). 409 for your own account.

Example: `PATCH /api/v1/admin/users/usr_e57c6d85e861` -> 200

Request body:
```json
{
 "active": false
}
```

Response (abbreviated):
```json
{
 "id": "usr_e57c6d85e861",
 "username": "sample.applicant.05",
 "role": "business",
 "district": null,
 "label": "Sample applicant 05 (synthetic)",
 "active": false,
 "created_at": "2026-10-13T08:02:58.594000Z",
 "last_login": null,
 "role_label": "Business",
 "district_name": null
}
```

#### `GET /api/v1/admin/audit`

Auth: state_admin. Audit log, newest first.

Query/body fields: `limit` (1-500), `district`

Example: `GET /api/v1/admin/audit?limit=2` -> 200

Response (abbreviated):
```json
{
 "items": [
  {
   "ts": "2026-10-13T08:03:01.681000Z",
   "actor": "demo.admin",
   "action": "user.disabled",
   "target": "usr_e57c6d85e861",
   "detail": "",
   "district": null
  },
  {
   "ts": "2026-10-13T08:03:01.677000Z",
   "actor": "officer.chamoli",
   "action": "user.created",
   "target": "usr_d9c2393e14b5",
   "detail": "role=district_officer",
   "district": "chamoli"
  }
 ],
 "total": 2
}
```

_79 endpoints documented. Generated by `portal/scripts/gen_api_doc.py` on 2026-10-13 from the app running on mongomock._
