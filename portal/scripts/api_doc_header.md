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
| `business` | `POST /auth/register` or demo `demo.business` | own businesses and applications; hiring (job posts, candidate search, interest requests) only with an ACTIVE registration |
| `job_seeker` | `POST /auth/register` with `role: job_seeker` or demo `demo.seeker` | own hiring profile, applications, interest requests, message threads |
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
| `POST /me/seeker/profile` (create) | 5/hour per user, 20/hour per IP |
| `POST /jobs/threads/{id}` (message) | 30/hour per user |
| `POST /jobs/{id}/apply` | 20/day per user |
| `POST /candidates/{code}/interest` | 40/day per user |
| `POST /jobs` (job post) | 20/day per user |

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
- **Hiring board privacy**: profiles have no gender, age/date of birth, religion, caste, marital/family status, photo
  or address fields (sending them is a 422). `phone`/`email` appear only in the seeker's own profile and, for a
  business, in `contact` after the candidate accepted that business's interest request; never in `/jobs` or
  `/candidates` search. `match.why` items are `{ok, partial?, text}`; show them as chips (not colour only).
  Workforce-market rows with `suppressed: true` have `candidates: null` and `gap: null`.
- **Rules/helplines**: `number: null` means "to be filled by the department"; never fill in a number.

## 8. Environment (server)

`MONGODB_URI` (unset or `mongomock://` = in-memory dev DB), `HOI_PORTAL_DB` (default `hoi_portal`), `HOI_ENV`
(`production` turns on the guard), `PORTAL_JWT_SECRET`, `PORTAL_ADMIN_PASSWORD`, `PORTAL_DEMO_LOGIN`,
`PORTAL_SEED_DEMO`, `PORTAL_CORS_ORIGINS`, `PORTAL_WEATHER_ENABLED`, `PORTAL_ACCESS_TTL_MINUTES` (30),
`PORTAL_REFRESH_TTL_DAYS` (14), rate-limit variables. See `portal/README.md`.
