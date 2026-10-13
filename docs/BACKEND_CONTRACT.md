# Backend contract for dispatch, photo proof and multi-tenancy

**Audience:** the backend owner. **Status:** implemented in `backend/hoi_platform` (see `backend/README.md` for the live endpoint list). Kept as the design record; differences: photos are uploaded to `/dispatch/jobs/{id}/photos`, and on-shift workers come from a roster snapshot published to `PUT /dispatch/context`.

The frontend implements these features today in a local SQLite sidecar (`frontend/lib/store.py`, `.data/hoi.db`).
They should move server-side so that every client (the dashboard, a Telegram bot, a worker PWA) shares one source of truth.
The shapes below are the ones the frontend already uses, so swapping the store for HTTP calls is mechanical.

## 1. Tenancy

Every table gets `tenant_id`, and every request carries it via the `X-Tenant-Id` header (from auth once that exists).

| Method | Path | Body / result |
|---|---|---|
| POST | `/tenants` | `{name, plan, brand_color}` → `{id, ...}` |
| GET | `/tenants/{id}` | tenant + properties |
| POST | `/tenants/{id}/properties` | `{name, region, rooms, floors}` |
| POST | `/tenants/{id}/staff:import` | CSV `employee_id, department, skills, contract_type`. **Reject** any column matching name/gender/religion/caste/health/family/phone/email/address/dob (the frontend already enforces this; enforce it again server-side) |
| POST | `/tenants/{id}/invites` | `{role}` → `{code}` (one-time; no email stored) |

## 2. Dispatch (auto-assign)

Job states: `new → offered → accepted → in_progress → done`, with side exits `unassigned` (no candidate left) and `cancelled`.

| Method | Path | Notes |
|---|---|---|
| POST | `/jobs` | `{title, department?, room?, urgency: high/medium/low, source: manual/voice/simulated}`. If `department` is missing, infer it from keywords. When the tenant's assign mode is `auto`, offer immediately. Returns the job with `offer_to`, `offer_expires_at`, `ranking[]` |
| GET | `/jobs?status=` | list |
| POST | `/jobs/{id}/accept` | `{employee_id}`. Must equal the current `offer_to`. Creates and acks the linked task (`idempotency_key = dispatch:{tenant}:{job}`) |
| POST | `/jobs/{id}/decline` | `{employee_id}` → re-offer to the next candidate |
| POST | `/jobs/{id}/start` | requires a `before` photo |
| POST | `/jobs/{id}/complete` | requires an `after` photo; marks the linked task done |
| POST | `/jobs/{id}/offer` | supervisor: offer to a specific `employee_id` |

**Offer expiry** must be enforced by the server (an APScheduler job every second, or lazily on read), not by the client. The demo clock multiplier should apply.

**Ranking** (keep it explainable; return `parts` per candidate):
`100 − 25·open_jobs − 8·done_this_shift − 6·floor_distance − (15 if band = high, 6 if watch)`.
Hard filters: on shift now (from the published roster), same department, has not declined or timed out on this job.
The retention guard ties dispatch to the attrition model: flagged staff are not handed extra load.
Weights are a starting point. Tune them with ops data before calling them good.

**Push:** send the offer to the worker's Telegram chat with inline Accept/Decline buttons (the bot already exists in the plan).

## 3. Photo proof

| Method | Path | Notes |
|---|---|---|
| POST | `/jobs/{id}/photos` | multipart `file`, `kind: before/after`, `employee_id`. The server stamps `server_ts` (never trust client EXIF), computes SHA-256, stores the object, and returns `{photo_id, sha256, server_ts}` |
| GET | `/jobs/{id}/photos` | metadata + signed URLs |

Capture should use a live-camera-only surface (Telegram Mini App / PWA `getUserMedia`, no gallery picker), plus a server-issued one-time token per job.
Known limit: none of this stops someone photographing a screen. A random code shown on the worker's screen at capture time raises the bar.

## 4. What the frontend will change when these exist

`lib/store.py` jobs/photos/tenants functions → `lib/api_client.py` calls. Pages stay as they are.
