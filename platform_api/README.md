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
  seed.py        platform admin from HOI_ADMIN_PASSWORD; demo workspace (fictional Himsagar Ridge Resort: 24 rooms, 20 staff, inventory history) when HOI_SEED_DEMO
  static/worker  staff app (PWA): shifts, live job pings, live-camera before/after photos, supplies, Hindi/English
  static/guest   guest concierge per room (QR): chat + voice, hotel info, requests, checkout, feedback; no personal data
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
- **Photos only where needed:** a per-hotel setting (`services/photo_proof.py`, ASSUMED defaults) says which job kinds need a
  before / after photo: room cleaning before + after; repairs, pest control, staff damage reports and lost-and-found after;
  deliveries, other guest requests, alerts, express checkout and other manager jobs none. Each job carries
  `photos_required: {kind, before, after}`; Start / Done (buttons and voice) check it server-side.

## Main endpoints

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/login`, `/auth/register` (invite), `GET /auth/demo-accounts`, `POST /auth/demo/{user}` (only if `HOI_DEMO_LOGIN`), `GET /auth/me`, `PATCH /auth/me/prefs`, `POST /auth/impersonate/{tid}` |
| Platform | `GET/POST /platform/tenants`, `PATCH/DELETE /platform/tenants/{id}`, `POST /platform/tenants/{id}/invites`, `GET /platform/audit` |
| Workspace | `GET/PATCH /workspace`, `GET/POST /workspace/properties`, `GET /workspace/staff`, `POST /workspace/staff/import`, `GET /workspace/users`, `PATCH /workspace/users/{id}`, `GET/POST /workspace/invites`, `GET /workspace/audit` |
| Dispatch | `PUT/GET /dispatch/context` (on-shift snapshot from the roster), `POST/GET /dispatch/jobs`, `POST /dispatch/jobs/{id}/accept\|decline\|start\|complete\|offer\|retry\|link-task`, `POST/GET /dispatch/jobs/{id}/photos`, `GET /dispatch/photos/{id}`, `POST /dispatch/reset` |
| Sessions | `POST /auth/refresh` (rotates), `POST /auth/logout` (revokes) |
| Rooms | `GET/POST /rooms`, `POST /rooms/bulk`, `POST /rooms/{id}/checkout\|check-in\|inspect\|out-of-order\|back-in-service`, `GET /rooms/{id}/qr.svg` |
| Guest (public) | `GET /public/guest/{token}`, `GET/POST /public/guest/{token}/requests`, `POST .../transcribe\|chat\|actions\|checkout\|feedback`, `GET/POST .../late-checkout`, `GET .../bill` (rate-limited per IP and per room) |
| Hotel profile | `GET/PUT /hotel/profile`; photo proof per job kind: `GET /hotel/settings/photo-proof` (owner, dept_head), `PUT` (owner) |
| Guest services | `GET /guest-services/summary\|late-checkouts\|feedback?days=\|checkouts?date=`, `POST /guest-services/late-checkouts/{id}/decide` |
| Worker voice | `POST /me/voice/transcribe\|command\|act` |
| Insights | `GET /platform/insights?days=30` (platform admin) |
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

## Guest concierge, worker voice, guest services, insights

Contract: [docs/HOSPITALITY_SUITE.md](../docs/HOSPITALITY_SUITE.md). Code: `services/profiles.py` (hotel profile), `services/concierge.py`
(chat: LLM + rule-based fallback), `services/guest.py` (express/late checkout, feedback, bill placeholder, guest-services views),
`services/voice.py` (worker voice intents), `services/insights.py` (platform insights), `services/ai.py` (OpenAI-compatible adapters).

- **Chat never acts.** `/public/guest/{token}/chat` only *proposes* an action; the guest's Confirm calls `/actions`. Every LLM
  reply is validated (Pydantic schema, action type in the request menu, HH:MM inside the profile's rules, rating 1-5), every number
  in the reply must appear in the profile / this room's data / the guest's words, the reply must be in the guest's script, and it
  may not claim something already happened. Anything failing, or no key / 429 / timeout, falls back to the rule-based concierge
  (English, Hindi, Hinglish) with `source: "rules"`. After an HTTP 429 the cloud call is skipped for the `Retry-After` time.
- **Privacy:** chat text and audio are not stored or logged (only a fallback reason). Audio is read into memory, never written by
  us; the upload's spooled temp file is closed (deleted) in `finally`. Voice needs `consent=true`. Free-text comments/reasons are
  length-capped and phone numbers / e-mails masked. The guest page shows the third-party-AI notice.
- **Express checkout:** creates a front-office dispatch job at once; the room is *not* vacated until the chosen time. The first read
  after that time (dispatch sweep) runs the normal room checkout (room → dirty, cleaning job, new stay). Times after the profile's
  checkout time need an approved late checkout. One express checkout and one feedback per stay (`rooms.stay` counter; unique indexes).
- **Insights:** `GET /platform/insights?days=30` (platform admin). Average worker performance is suppressed below 5 scored workers.

### AI provider (any OpenAI-compatible API)

| Variable | Default | Notes |
|---|---|---|
| `LLM_BASE_URL` | `https://api.groq.com/openai/v1` | chat completions at `{base}/chat/completions` |
| `LLM_API_KEY` | falls back to `GROQ_API_KEY` | secret; read at call time, never logged |
| `LLM_MODEL` | `openai/gpt-oss-20b` | |
| `LLM_API_KEYS_BACKUP` / `STT_API_KEYS_BACKUP` | fall back to `GROQ_API_KEYS_BACKUP` | secret; comma-separated backup keys (see key failover below) |
| `HOI_AI_KEY_COOLDOWN_MINUTES` | 10 | ASSUMED; a key that failed is skipped this long |
| `LLM_JSON_MODE` | `true` | sends `response_format: {"type": "json_object"}`; set `false` for servers without JSON mode (replies are validated either way) |
| `STT_BASE_URL` / `STT_API_KEY` / `STT_MODEL` | Groq / `GROQ_API_KEY` / `whisper-large-v3-turbo` | Whisper at `{base}/audio/transcriptions` |
| `HOI_GUEST_AI_ENABLED` | `true` | `false` = rules + typing only (no cloud calls) |
| `HOI_AI_TIMEOUT_SECONDS`, `HOI_CHAT_HISTORY_TURNS`, `HOI_CHAT_MAX_REPLY_CHARS`, `HOI_CHAT_TEMPERATURE` | 20, 6, 600, 0.3 | |
| `HOI_STT_MAX_MB`, `HOI_STT_MAX_SECONDS` | 8, 60 | the browser stops at 60 s; the size cap is the server's hard limit |
| `HOI_GUEST_CHAT_RATE_PER_MINUTE`, `HOI_GUEST_STT_RATE_PER_MINUTE`, `HOI_GUEST_ACTION_RATE_PER_MINUTE` | 10, 6, 10 | per room; per IP = 3x |
| `HOI_FEEDBACK_MAX_CHARS`, `HOI_HOTEL_UTC_OFFSET_MINUTES` | 1000, 330 | hotel local time for HH:MM (IST) |

**Key failover:** the primary key is tried first; the next backup key is used ONLY when a key is invalid or revoked
(HTTP 401/403) or the provider fails (5xx, connection error, timeout). That key is then skipped for the cool-down. Logs show
only indices ("llm key #2 failed: 401"), never keys. HTTP 429 never rotates keys: switching keys to get around a provider's
per-account rate limit would break its terms (Groq's included). A 429 with `Retry-After` <= 2 s is retried once on the same
key; otherwise cloud calls pause for the `Retry-After` time (max 120 s) and the rule-based concierge answers. Sarvam stays single-key.

Three setups (PowerShell):

```powershell
# 1. Groq (default): only the key
$env:GROQ_API_KEY = "<groq key>"

# 2. OpenAI for both chat and speech-to-text
$env:LLM_BASE_URL = "https://api.openai.com/v1"; $env:LLM_MODEL = "gpt-4o-mini"; $env:LLM_API_KEY = "<openai key>"
$env:STT_BASE_URL = "https://api.openai.com/v1"; $env:STT_MODEL = "whisper-1";   $env:STT_API_KEY = "<openai key>"

# 3. Local Ollama for chat (any non-empty key string); Ollama has no Whisper endpoint, so speech-to-text stays on
#    Groq/OpenAI (STT_* or GROQ_API_KEY) or, with no STT key, voice answers 503 and the apps fall back to typing.
$env:LLM_BASE_URL = "http://localhost:11434/v1"; $env:LLM_MODEL = "qwen2.5:7b"; $env:LLM_API_KEY = "ollama"
$env:LLM_JSON_MODE = "true"   # Ollama supports JSON mode; set false for a server that rejects response_format
```

### Local voice (speech-to-text on this PC)

`STT_PROVIDER=local` runs [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on the machine running the API instead of a
cloud Whisper. It is optional and imported lazily, so Render/Docker (which do not install it) still start.

```powershell
pip install -r requirements-local.txt          # faster-whisper (not in requirements.txt)
$env:STT_PROVIDER = "local"
$env:LOCAL_STT_MODEL = "small"                 # default; multilingual incl. Hindi. First run downloads it (about 460 MB)
$env:LOCAL_STT_DEVICE = "auto"                 # auto = CUDA if ctranslate2 sees a GPU (float16), else CPU int8; CUDA failure -> CPU
```

The model is loaded once per process; each recording is written to a temporary file that is deleted right after decoding.
Without the package, `/transcribe` answers 503 "type instead".

### Spoken replies (text-to-speech)

- **Browser (default, free):** `static/shared/voice.js` speaks replies with the phone's `speechSynthesis`, ranking voices for a
  soft female Indian voice (hi-IN natural voices such as Microsoft Swara / Kalpana / "Google हिन्दी"; en-IN such as Neerja / Heera;
  male voices last), rate 0.92, pitch 1.05, volume 0.9, sentence by sentence; users can pick another voice (remembered on the
  device) or mute. Times, rupees and numbers are rewritten for speech first ("11:00" -> "ग्यारह बजे", "₹180" -> "एक सौ अस्सी रुपये").
- **Sarvam Bulbul (optional, realistic Indian voices):** `TTS_PROVIDER=sarvam` + `SARVAM_API_KEY` (secret, environment only).
  `POST /public/guest/{token}/tts` and `POST /me/voice/tts` `{text <= 500, lang}` return `audio/wav`, or 204 when the browser
  should speak (provider browser, no key, error). Identical audio is cached in MongoDB for 24 h (`tts_cache`, TTL index) to save
  credits. Defaults (ASSUMED, user preference: a woman's voice, soft, Indian accent, same speaker for Hindi and English):
  `SARVAM_MODEL=bulbul:v3`, `SARVAM_SPEAKER=priya`, `SARVAM_PACE=0.9`. Sarvam's docs do not label speaker gender: listen in the
  Sarvam dashboard and adjust; the v4-flash catalog has e.g. `ritu_hi_customer_warm`. Loudness/pitch exist only for bulbul:v2.
  Note: cached audio is the assistant's reply text (which can echo the guest's words) and is kept for up to 24 h.

Free tiers give no privacy guarantee and are rate-limited (Groq's free tier answered HTTP 429 after ~4 concierge chats in a
minute in our test; the rules then answer). Use a paid tier or a local model for real guests.

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

## Demo hotel (SYNTHETIC, FICTIONAL)

The demo tenant `org_demo` is "Himsagar Ridge Resort, Mussoorie (fictional)": 24 rooms (101-108, 201-208, 301-308; 18
occupied), 20 staff HS01-HS20 imported with `role_title` and `avatar` (role slug) only, a full hotel profile with
`logo_url: /shared/brand/himsagar-logo.svg`, inventory scaled to 24 rooms. Demo accounts: demo.owner (HS01), demo.hr,
demo.housekeeping (HS02), demo.frontoffice (HS08), demo.store, workers HS05, HS09, HS12, HS18. A demo tenant seeded by an
older version (the former "Riverside Retreat") is rebuilt at startup (`demo_version`); only that tenant is touched.
`python -m hoi_platform.seed --reset-demo` rebuilds it; `scripts/reseed_atlas.py --yes --platform` does it on the real
cluster. The tenant object (login, `/auth/me`) carries `logo_url` (same-origin paths only); guest requests carry
`department` (for the department avatar; never staff ids).
