# Uttarakhand Tourism & Hospitality Portal (concept), `portal/`

Concept prototype for the AI-Tourism Hackathon 2026, **not an official Government of Uttarakhand website**.
Data is sample/synthetic unless marked otherwise. Spec: `docs/PORTAL_SPEC.md`. API contract: `docs/PORTAL_API.md`.

## Run

```powershell
cd portal
..\.venv\Scripts\python.exe -m uvicorn hoi_portal.main:app --port 8200
```

Without `MONGODB_URI` it uses in-memory mongomock and seeds synthetic demo data at startup (about 3 s).
Open http://127.0.0.1:8200/ (web app) and http://127.0.0.1:8200/docs (Swagger, dev only).

External data (all keys server-side; tests use fakes and never call the network):

- **BestTime** foot traffic: `..\.venv\Scripts\python.exe -m hoi_portal.scripts.besttime_refresh [--dry-run]` fetches the
  venues in `seed/besttime_venues.py` once (skips venues fetched < 7 days ago and venues BestTime could not forecast;
  both are stored in `crowd_forecasts`). Destination crowd responses add `foot_traffic` (or null) beside our estimate.
- **LocationIQ**: `GET /api/v1/map/static` (PNG proxied and cached in `map_tiles`) and
  `GET /api/v1/destinations/{id}/places` (cached in `places_cache`). Calls are sequential, >= 0.5 s apart.
- **Traffic prediction** (`services/traffic.py`, weights in `hoi_portal/traffic.yaml`, all ASSUMED): `GET /api/v1/traffic/{id}?hours=72`.
  Predicted, not measured. Live providers (`services/traffic_live.py`) only adjust the next 1-3 hours; each live answer is
  stored in `traffic_observations`; `python -m hoi_portal.scripts.traffic_calibrate` fits per-destination corrections
  once 30 observations exist (pure Python; no numpy on the deployed portal).

Tests (offline, mongomock, fake weather):

```powershell
cd portal; ..\.venv\Scripts\python.exe -m pytest -q
```

Regenerate the API contract with real example responses: `.venv\Scripts\python.exe portal\scripts\gen_api_doc.py`.

## Environment

| Variable | Default | Notes |
|---|---|---|
| `MONGODB_URI` | unset = mongomock | Secret. Never logged. |
| `HOI_PORTAL_DB` | `hoi_portal` | |
| `HOI_ENV` | `development` | `production` enables the start-up guard |
| `PORTAL_JWT_SECRET` | random per process | 32+ chars required in production |
| `PORTAL_ADMIN_PASSWORD` | unset | Creates state admin `admin` (12+ chars required in production) |
| `PORTAL_DEMO_LOGIN` | true outside production | Must be false in production; demo login is refused in production anyway |
| `PORTAL_SEED_DEMO` | true outside production | Seeds synthetic data when the database has no businesses |
| `PORTAL_CORS_ORIGINS` | `*` in dev, none in prod | Explicit list required in production |
| `PORTAL_WEATHER_ENABLED` | true | Calls Open-Meteo server-side |
| `BESTTIME_API_KEY_PRIVATE` | unset | Secret. Only the refresh command uses it (BestTime foot-traffic forecasts) |
| `LOCATIONIQ_API_KEY` | unset | Secret. Street map image + nearby places (server-side only); `PORTAL_LOCATIONIQ_ENABLED=false` switches it off |
| `TOMTOM_API_KEYS` / `TOMTOM_API_KEY` | unset | Secret. Live traffic nowcast; comma list = failover keys (401/403/5xx/timeout only, never on 429) |
| `HERE_API_KEY` | unset | Secret. Optional second live-traffic provider |
| `TRAFFIC_PROVIDERS` | `tomtom,here,mapbox` | Provider order (Mapbox is a documented stub) |
| `PORTAL_EXTERNAL_CACHE_DAYS` | 7 | Cache for BestTime / LocationIQ results in MongoDB |
| `PORTAL_ACCESS_TTL_MINUTES` / `PORTAL_REFRESH_TTL_DAYS` | 30 / 14 | |
| `PORTAL_PROFILE_RATE_PER_HOUR`, `PORTAL_MESSAGE_RATE_PER_HOUR`, `PORTAL_APPLY_RATE_PER_DAY`, `PORTAL_INTEREST_RATE_PER_DAY`, `PORTAL_JOB_POST_RATE_PER_DAY` | 5, 30, 20, 40, 20 | Hiring board, per user |
| `PORTAL_LOGIN_RATE_PER_MINUTE`, `PORTAL_GRIEVANCE_RATE_PER_HOUR`, `PORTAL_TRACK_RATE_PER_MINUTE`, `PORTAL_VERIFY_RATE_PER_MINUTE`, `PORTAL_INGEST_RATE_PER_MINUTE` | 10, 5, 20, 60, 120 | |

Production guard (`config.validate`): refuses to start with an empty or `mongomock://` URI, a weak/unset JWT secret,
demo login on, missing/`*` CORS origins, or a missing/short admin password.

## Layout

```
hoi_portal/
  main.py        app factory, request-id + security headers (strict CSP), error mapping, static web app at /
  config.py      settings + production validate()
  mongo.py       cached MongoClient (tz_aware UTC), mongomock fallback, counters, audit, ensure_indexes
  security.py    PBKDF2-SHA256 200k, JWT HS256, refresh tokens / API keys / tracking codes as SHA-256
  deps.py        bearer auth, role guards, district_scope() (single place officer scoping is enforced)
  ratelimit.py   in-process sliding window
  catalog.py     vocabularies (types, codes, checklist, statuses, SLA)
  schemas.py     request bodies (extra fields forbidden)
  errors.py      typed service errors -> HTTP
  services/      search, registry, destinations, weather, crowd, events, dictionary, rules, advisories,
                 grievances, applications, businesses, ingest, analytics, users
  routers/       public, auth, business (+ ingest), officer (+ analytics), admin
  seed/          curated reference data (districts, destinations, festivals, dictionary, rules + helplines)
                 and generator.py (deterministic synthetic data)
  static/        web app (built separately)
scripts/         gen_api_doc.py + api_doc_header.md -> docs/PORTAL_API.md
tests/           pytest, offline
```

## Storage design (MongoDB, see docs/MONGODB.md)

- Collections: `users`, `refresh_tokens`, `districts`, `destinations`, `dictionary`, `rules`, `helplines`, `events`,
  `businesses`, `applications`, `grievances`, `advisories`, `api_keys`, `occupancy`, `occupancy_agg`, `workforce`,
  `arrivals`, `weather_cache`, `crowd_forecasts`, `map_tiles`, `places_cache`, `traffic_cache`, `traffic_observations`,
  `traffic_calibration`, `counters`, `meta`, `audit_log`; hiring board: `seeker_profiles`, `job_posts`, `job_applications`,
  `interest_requests`, `job_shortlist`, `job_messages`. Indexes are created at startup.
- **Occupancy** is stored compactly: `occupancy` holds one document per (business, month) with day-indexed arrays
  `avail[]`, `occ[]`, `src[]` (`s` seed, `m` monthly form, `i` HOI ingest; null = no report). `occupancy_agg` holds
  one document per (destination, stay type, month) with day-indexed sums; the crowd index and occupancy analytics
  read only the aggregate (about 1,150 small documents for two years), cached in-process for 5 minutes and
  invalidated on every write. Writes update both by delta (idempotent per business+date, compensating write if the
  second update fails; no transactions).
- **Search**: mongomock has no `$text`, so searchable documents carry a normalised lowercase `search_text` and
  queries use escaped, case-insensitive regexes (every token must match; 80 chars / 6 tokens max).
- Reference data is reloaded when its content hash changes (`meta.reference`). Demo data is seeded once, guarded by
  a `meta.demo_seed` lock document; bulk inserts run before index creation (mongomock's unique checks are O(n^2)).
- Ids: strings (`biz_0001`, `APP-000001`, `UTHP-G-000001`); sequences from `counters`. Registration numbers
  `UK-<TYPE>-<DISTRICT>-<NNNNN>` use one counter per (type, district). Type and district codes are prototype codes.

## Synthetic seed (fixed RNG seed 20260413)

304 businesses across all 13 districts and 24 destinations with names like "Cedar Sample Homestay 014, Munsiyari";
daily occupancy for the 730 days before the seed date for every hotel/homestay; HOI workforce aggregates (12 months)
for about 40 % of stays; arrivals by district 2019-2026 (current year partial); 40 grievances; 20 applications
(submitted, changes requested, approved, rejected, renewals); 9 sample advisories (one expired); 2 sample events;
demo accounts `demo.admin`, `demo.officer.rudraprayag`, `demo.business` and five synthetic applicants. Occupancy
curves are ASSUMED shapes that follow the curated seasonality hints; they are not data.

## Hiring board (jobs)

Job seekers (role `job_seeker`) keep a profile (skills from `seed/skills.py` with years, self-declared certificates,
languages, preferred districts, availability, expected pay, short bio). No gender, age, religion, caste, family,
photo or address fields exist; sending them is rejected. Phone/email are private and reach a business only after the
seeker accepts that business's interest request. Businesses with an ACTIVE registration post jobs, search candidates
and send requests. Match score: `services/matching.py` with ASSUMED weights in `hoi_portal/hiring.yaml` (skills 50,
district 20, availability 20, language 10; unset criteria are left out and the rest rescaled). Officials see only
aggregates (`/analytics/workforce-market`, candidate counts < 5 suppressed). Delete = hard delete (profile,
applications, requests, messages). Seed (`seed/hiring.py`, once, when the hiring collections are empty, lock
`meta.hiring_seed`): 120 synthetic candidates "Candidate C-0001..", placeholder phones `+91-90000-0NNNN`, 44 job posts
from synthetic businesses, applications, requests, demo account `demo.seeker`.

## Crowd index (estimate)

`index = clamp(0.8 x occupancy% + event + weekend + season, 0, 100)` with event +12/+6/+2 (high/medium/low impact),
weekend +5, season +5 in the pattern's peak months and -10 in closed months (all weights ASSUMED). Occupancy is the
reported value for the day, else the same weekday one and two years earlier (+-3 days), else the month's usual level,
else the seasonal pattern. Bands: low < 40, moderate 40-64, high 65-84, very high >= 85.

## Weather

Open-Meteo forecast (current temperature, weather code, wind; 7-day max/min, precipitation probability and sum,
snowfall; timezone Asia/Kolkata), 6 s timeout, cached 30 minutes per destination in `weather_cache`; failures are
cached for 3 minutes and return `{"available": false, "reason": ...}` (or the last good forecast marked `stale`).
Warning thresholds are ASSUMED: heavy rain >= 50 mm/day (or >= 80 % probability with >= 20 mm), snow >= 5 cm/day.

## Scaling

One process: the rate limiter and crowd cache are in memory. For several instances, move both to a shared store.

## Known gaps

- Altitudes are not in the curated reference set, so `altitude_m` is null.
- Arrival and occupancy figures are synthetic; there is no real data source yet.
- Hindi dictionary terms need review by native speakers.
