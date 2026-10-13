# HOI platform API (`hoi_platform`)

FastAPI service for everything the ML/ops backend does not cover: hotel groups (tenants), accounts and roles,
live dispatch with server-enforced offer expiry, photo proof, inventory, and an audit log.

```
hoi_platform/
  main.py        create_app(): routers, error mapping, demo seed
  config.py      settings from env (MONGODB_URI, HOI_PLATFORM_DB, HOI_JWT_SECRET, HOI_DEMO_LOGIN, HOI_ADMIN_PASSWORD, HOI_SEED_DEMO)
  mongo.py       MongoDB client (cached), indexes, integer counters, serialisation (every business document has tenant_id)
  security.py    PBKDF2-SHA256 password hashing, JWT (HS256) tokens
  deps.py        bearer auth, role guards, tenant scoping (tenant only from the token)
  schemas.py     request bodies (Pydantic)
  services/      business logic, no HTTP: tenants, users, sessions, dispatch, rooms, photos, inventory, errors
  routers/       HTTP layer: auth, platform, workspace, dispatch, rooms, public (guest), me, inventory
  ratelimit.py   per-IP / per-user sliding-window limiter for auth and guest endpoints
  seed.py        platform admin from HOI_ADMIN_PASSWORD; demo workspace (45 rooms, inventory history) when HOI_SEED_DEMO
  static/worker  staff app (PWA): shifts, live job pings, live-camera before/after photos, supplies, Hindi/English
  static/guest   guest request page per room (QR), no personal data
tests/           pytest (TestClient), offline on mongomock with a fresh database per run
```

## Run

```powershell
pip install -r requirements.txt
$env:MONGODB_URI = "mongodb+srv://..."                  # optional; without it an in-memory mongomock is used (data lost on restart)
uvicorn hoi_platform.main:app --reload --port 8100      # docs at http://localhost:8100/docs
python -m pytest -q                                     # offline: tests force MONGODB_URI=mongomock://
```

## Environment

| Variable | Default | Notes |
|---|---|---|
| `MONGODB_URI` | unset (mongomock) | Secret. Unset or `mongomock://` = in-memory mongomock with one warning; refused when `HOI_ENV=production`. Never logged; `/health` only says `"database": "mongodb"` or `"mongomock"`. |
| `HOI_PLATFORM_DB` | `hoi_platform` | Database name in the cluster. |
| `HOI_ENV` | `development` | `production` turns on the startup checks below. |
| `HOI_JWT_SECRET` | random per process | 32+ characters in production. |
| `HOI_ADMIN_PASSWORD` | unset | Creates the platform admin `platform` on first start (12+ characters in production). |
| `HOI_DEMO_LOGIN` / `HOI_SEED_DEMO` | true outside production | One-click demo accounts / synthetic demo workspace (`org_demo`). |
| `HOI_CORS_ORIGINS`, `HOI_PUBLIC_BASE_URL` | `*`, request URL | Explicit origins in production; base URL printed in room QR codes. |
| `HOI_ACCESS_TTL_MINUTES`, `HOI_REFRESH_TTL_DAYS`, `HOI_LOGIN_RATE_PER_MINUTE` | 30, 14, 10 | Sessions and rate limit. |

## Data model (MongoDB, database `hoi_platform`)

No multi-document transactions (see `docs/MONGODB.md`). Every business document has `tenant_id` and every query filters by it
(exceptions: sign-in by globally unique username, refresh tokens by hash, and the guest page by its random room token).
Public ids are the `id` field (unique index); `_id` never leaves `mongo.py`. Audit entries and ledger moves keep integer ids from
the `counters` collection. Times are stored as UTC datetimes and returned in the same ISO format as before.

| Collection | Key indexes | Atomicity |
|---|---|---|
| `users` | `id`, `_username_lc` (unique) | unique index makes sign-up race-free; failed logins use `$inc` |
| `refresh_tokens` | `token_hash` (unique), `user_id` | rotation claims the token with one conditional update (`revoked: 0` and not expired); reuse of a rotated token revokes all of the user's tokens |
| `invites` | `code` (unique) | claimed with `find_one_and_delete`; re-inserted if the account cannot be created |
| `jobs` | `id`, `(tenant_id, status)`, `(tenant_id, created_at)` | every write bumps `_v`; accept/decline/offer/retry are conditional on status and `_v`, so only one racing request wins |
| `photos` + `photo_blobs` | `id` | stamped JPEG stored as BSON binary (no disk); metadata keeps the SHA-256, re-checked on every read; blob removed if the metadata insert fails |
| `inv_stock` | `(tenant_id, item_id, location_id)` unique | decrement is `find_one_and_update({qty: {$gte: n}}, {$inc: -n})`: stock can never go negative |
| `inv_moves` | `id`, `(tenant_id, item_id, location_id)`, `(tenant_id, kind, at)` | written right after the stock update; the stock change is reversed if the insert fails, so stock = sum of moves |
| `inv_reqs`, `inv_pos`, `inv_counts` | `id`, `(tenant_id, created_at)` | lines are embedded; issued/received quantities are reserved with a conditional `$inc` on the line before stock moves; multi-line operations undo earlier steps if a later one fails; a count is claimed (`open` to `posting`) so it posts once |
| `tenants`, `properties`, `staff`, `rooms`, `dispatch_context`, `roster_snapshots`, `inv_items`, `inv_locations`, `inv_suppliers`, `audit_log`, `counters` | `id` / natural keys unique (`(tenant_id, employee_id)`, `(tenant_id, number)`, `guest_token`, `(tenant_id, sku)`) | single-document upserts |

Indexes are created idempotently at startup. `GET /ready` pings the database.

## Security model

- **Tenant isolation:** the tenant comes only from the signed token (`tid`). Item, location and supplier ids from another tenant are rejected.
- **Roles:** `platform_admin`, `owner`, `hr`, `dept_head`, `storekeeper`, `worker`. Every route declares its roles. Workers act only as themselves, never see colleagues' risk bands, and see only their own jobs and requests.
- **Platform admins** reach hotel data only through `POST /auth/impersonate/{tid}`, which is audited.
- **Passwords:** PBKDF2-SHA256 with 200k iterations and a per-user salt, constant-time compare, the same timing for unknown users, and lockout after 5 failures for 5 minutes. Sign-up needs a single-use invite code.
- **Privacy guard:** staff imports with personal columns (name, gender, religion, caste, health, family, phone, email, …) are rejected server-side.
- **Photo proof:** the server timestamps (never client EXIF), stamps job and worker onto the image, stores a SHA-256, and re-verifies on read. It cannot detect a photo of a screen.

## Main endpoints

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/login`, `/auth/register` (invite), `GET /auth/demo-accounts`, `POST /auth/demo/{user}` (only if `HOI_DEMO_LOGIN`), `GET /auth/me`, `PATCH /auth/me/prefs`, `POST /auth/impersonate/{tid}` |
| Platform | `GET/POST /platform/tenants`, `PATCH/DELETE /platform/tenants/{id}`, `POST /platform/tenants/{id}/invites`, `GET /platform/audit` |
| Workspace | `GET/PATCH /workspace`, `GET/POST /workspace/properties`, `GET /workspace/staff`, `POST /workspace/staff/import`, `GET /workspace/users`, `PATCH /workspace/users/{id}`, `GET/POST /workspace/invites`, `GET /workspace/audit` |
| Dispatch | `PUT/GET /dispatch/context` (on-shift snapshot from the roster), `POST/GET /dispatch/jobs`, `POST /dispatch/jobs/{id}/accept\|decline\|start\|complete\|offer\|retry\|link-task`, `POST/GET /dispatch/jobs/{id}/photos`, `GET /dispatch/photos/{id}`, `POST /dispatch/reset` |
| Sessions | `POST /auth/refresh` (rotates), `POST /auth/logout` (revokes) |
| Rooms | `GET/POST /rooms`, `POST /rooms/bulk`, `POST /rooms/{id}/checkout\|check-in\|inspect\|out-of-order\|back-in-service`, `GET /rooms/{id}/qr.svg` |
| Guest (public) | `GET /public/guest/{token}`, `POST /public/guest/{token}/requests` (rate-limited per IP and per room) |
| Staff | `GET /me/shifts`, `PUT /dispatch/roster` (managers publish the roster employees see), `GET /me/performance?days=14` (worker: own score and reasons only) |
| Performance | `GET /dispatch/performance?days=14` (owner, hr, dept_head: own department only; 1-90 days) |
| Inventory | `GET/POST /inventory/items\|locations\|suppliers`, `GET /inventory/stock\|moves`, `POST /inventory/receive\|issue\|waste\|transfer`, `GET/POST /inventory/requests`, `POST /inventory/requests/{id}/fulfil\|reject`, `GET/POST /inventory/pos`, `POST /inventory/pos/{id}/status\|receive`, `GET/POST /inventory/counts`, `POST /inventory/counts/{id}/post`, `GET /inventory/suggestions?rooms=&occ=`, `GET /inventory/analytics` |

Dispatch ranking (returned per candidate): `100 − 25·open_jobs − 8·done_this_shift − 6·floor_distance − retention_guard (15 high / 6 watch)`.
The weights are a starting point to tune with real operations data.

## Performance score (plan 4.1)

`services/performance.py`. A **coaching aid compared with each person's own baseline; not for disciplinary use.** Computed from
dispatch jobs only; it never uses or returns attrition risk bands, and workers are employee ids only (SYNTHETIC demo data).
Period = the last `days` days (default 14); baseline = the `days` days before that, scored the same way; `delta` = score − baseline.

| Part | Weight | Definition (thresholds are ASSUMED starting points) |
|---|---|---|
| On time | 35% | Share of completed jobs finished (accepted → done) within the job's target: `target_minutes` on the job if present, else by urgency high 30 / medium 60 / low 120 min. Measured from acceptance, so dispatch delays do not count against the worker. |
| Speed | 20% | Department median work time (started → done, same period) ÷ the worker's median, capped at 1: at or faster than the median = full marks (rushing is not rewarded beyond it). |
| Quality | 25% | Inspection pass rate on the worker's inspected cleaning jobs (room inspection pass vs re-clean; the outcome is stamped on the job by `POST /rooms/{id}/inspect`). Left out when there is no inspected job; the other weights are re-normalised (`weights_used`). |
| Responsiveness | 10% | Median seconds from offer to accept: ≤ 10 s = full marks, linear to 0 at the offer window (`offer_seconds`, default 30). |
| Reliability | 10% | 1 − (declines + timeouts) ÷ offers answered (accepted + declined + timed out). |

Score = 100 × Σ weight × part ÷ Σ weights of the parts available. Fewer than **5 completed jobs** in the period →
`status: "insufficient_data"`, no score, and a reason (parts still shown for context); no baseline when the previous period
has fewer than 5. Up to three plain-language `reasons`: changes vs the person's own baseline first, then the weakest parts.
Department heads are scoped by the `department` on their user document (the demo account `demo.housekeeping` = housekeeping),
falling back to the staff record of their employee id; without one the endpoint answers 403.

## Production configuration

`HOI_ENV=production` + `MONGODB_URI` (a real cluster, not mongomock) + `HOI_JWT_SECRET` (32+ chars) + `HOI_ADMIN_PASSWORD` (12+) +
`HOI_CORS_ORIGINS` (explicit) + `HOI_DEMO_LOGIN=false`.
Startup fails with a list of problems otherwise. See `.env.example` at the repo root.

## Known limits

- The rate limiter is in-process: run one worker per deployment (the Dockerfile does), or move it to a shared store before scaling out.
  The data layer itself is stateless and safe for several instances.
- Without transactions, a crash between the stock update and the ledger insert of one move could leave them apart;
  `GET /inventory/analytics` reports any drift in `ledger_errors`.
- The demo seed creates accounts with random passwords (one-click demo only).
