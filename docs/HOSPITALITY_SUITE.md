# Hospitality suite: five apps, one platform API (build contract)

**Audience:** the team and the builders. Status: contract for the 13–14 Oct build. All data synthetic.

| App | Who | Where | Built with |
|---|---|---|---|
| Marketing site | prospects, judges | `website/site/` (Vercel, `/site/`) | static HTML |
| Super-admin portal | HOI team (platform admin) | dashboard with `ADMIN_PORTAL=super`: `console/` pages (Render `hoi-platform-admin`) | Streamlit |
| Hotel admin portal | owner, HR, dept heads, storekeeper (platform admins after choosing a hotel, audited) | dashboard with `ADMIN_PORTAL=hotel`: `pages/` + `employee/` (Render `hoi-dashboard`) | Streamlit |
| Worker app (voice) | frontline staff | `platform_api/.../static/worker/` → `/worker/` (Render) | vanilla JS PWA |
| Guest concierge (QR, voice) | hotel guests | `platform_api/.../static/guest/` → `/guest/?t=<room token>` (Render) | vanilla JS |

## 1. Hotel profile (feeds the guest concierge)

One document per property, collection `hotel_profiles`, `{tenant_id, property_id, ...}`.

```json
{
  "property_id": "...",
  "display_name": "Sample Hill Retreat, Mussoorie",
  "welcome": "Namaste! ...",
  "checkin_time": "12:00", "checkout_time": "11:00",
  "late_checkout": {"allowed": true, "latest": "14:00", "note": "Subject to availability; manager approves"},
  "wifi": {"network": "HOI-Guest", "password_hint": "Ask at front desk"},
  "contacts": [{"label": "Front desk", "extension": "9"}],
  "amenities": [{"name": "Restaurant", "hours": "07:00-22:30", "where": "Ground floor", "note": ""}],
  "dining": [{"item": "Aloo paratha", "price_inr": 180, "veg": true, "hours": "07:00-11:00"}],
  "policies": [{"title": "Quiet hours", "text": "22:00-07:00"}],
  "nearby": [{"name": "Mall Road", "distance_note": "approx. 1 km", "tip": "Best before 10 am"}],
  "faq": [{"q": "Is breakfast included?", "a": "..."}],
  "languages": ["en", "hi"],
  "updated_at": "..."
}
```

- `GET /hotel/profile` (owner, dept_head, hr, storekeeper read; owner/dept_head write via `PUT /hotel/profile`), scoped to the token's tenant + its (first) property. Validated by Pydantic; strings length-capped; no personal data.
- Demo seed: one complete synthetic profile for the demo hotel.

## 2. Guest concierge (public, room token from the QR code; no login)

All under `/public/guest/{token}`; rate-limited per IP and per room (config). Responses never include other rooms' data or staff ids.

| Method | Path | Purpose |
|---|---|---|
| GET | `/public/guest/{token}` | (exists) room info + request menu; ADD `profile` (public subset of the hotel profile, no internal fields) |
| GET | `/public/guest/{token}/requests` | this room's requests with live status (open → accepted → in progress → done) |
| POST | `/public/guest/{token}/requests` | (exists) create a request |
| POST | `/public/guest/{token}/transcribe` | multipart `audio` + `consent=true` + `lang` hint → `{text, provider}`; Groq Whisper (`whisper-large-v3-turbo`); max size/duration from config; audio never stored; 422 without consent; 503 + "type instead" when no key/failure |
| POST | `/public/guest/{token}/chat` | `{message, lang?, history: [{role, text}] (last 6)}` → `{reply, lang, proposed_action|null, source: "llm"|"rules"}` |
| POST | `/public/guest/{token}/actions` | `{action, params}` — executes a proposed action ONLY after the guest taps Confirm |
| POST | `/public/guest/{token}/checkout` | `{time "HH:MM", luggage_help: bool}` → express checkout: notifies front office (dispatch job, dept front_office) and queues the room-cleaning job for that time |
| POST | `/public/guest/{token}/late-checkout` | `{until "HH:MM", reason?}` → pending request for manager approval |
| GET | `/public/guest/{token}/late-checkout` | status: pending / approved / declined (+ note) |
| POST | `/public/guest/{token}/feedback` | `{rating 1-5, comment?, lang}` (one per stay; comment ≤ 1000 chars) |
| GET | `/public/guest/{token}/bill` | placeholder: `{"available": false, "note": "Bills and payment come from the hotel's PMS; not connected in this prototype", "requests_with_charges": [...]}` (only dining items with a profile price, labelled estimate) |

**Chat rules (the "almost human" assistant):**
- Grounded ONLY in the public hotel profile + this room's own requests + today's date/time. If the answer is not there: say so and offer to ask the front desk (proposes a `request` action).
- Warm, short (≤ 3 sentences), replies in the guest's language (Hindi Devanagari, Hinglish or English, mirroring the guest), uses the guest's words back, never invents prices, timings, phone numbers or policies.
- `proposed_action` ∈ `request{type, note}` (types = the existing guest request menu ids), `checkout{time, luggage_help}`, `late_checkout{until}`, `feedback{rating, comment}`. The UI shows a confirm card; nothing happens until Confirm → `/actions`.
- LLM: Groq chat completions, model from config (default `openai/gpt-oss-20b`), temperature 0.3, JSON output validated by Pydantic; on invalid JSON, no key, 429 or timeout → rule-based fallback (keyword/intent matcher over the profile, Hindi + English) with `source: "rules"`.
- Privacy: the page tells guests "Messages and voice are processed by a third-party AI service; please don't share personal details (names, phone, payment)". Messages are not stored beyond the request/feedback they create; chat transcripts are not logged. A config flag `guest_ai_enabled` (default true in development) turns cloud AI off (rules + typing only).

## 3. Worker voice (logged-in worker; existing auth)

| Method | Path | Purpose |
|---|---|---|
| POST | `/me/voice/transcribe` | multipart audio → `{text}` (same STT path, worker's own voice; consent remembered per device) |
| POST | `/me/voice/command` | `{text, lang}` → `{intent, reply, proposed_action|null}` with intents: `whats_next` (reads current offer/job), `accept`, `decline`, `start`, `done` (reminds that the after-photo is still needed), `report_issue{room, issue, department, urgency}` (creates a job after Confirm), `my_shift`, `help` |
| POST | `/me/voice/act` | executes a confirmed `proposed_action` (reuses existing dispatch endpoints' logic) |

The worker app gets a large mic button on Jobs and Today; replies are spoken with the browser's speech synthesis (`hi-IN`/`en-IN` voices when available) and shown as text; everything stays usable by tapping.

## 4. Hotel admin (dashboard pages, hotel roles)

- **Hotel profile** page: edit every profile section (tables + text areas), preview "what guests see".
- **Guest services** page: live guest requests by room, express checkouts today (time, luggage help), late-checkout queue with Approve / Decline (+ note), feedback list with average rating and trend.
- Endpoints: `GET /guest-services/summary`, `GET /guest-services/late-checkouts`, `POST /guest-services/late-checkouts/{id}/decide {approve: bool, note}`, `GET /guest-services/feedback?days=30`, `GET /guest-services/checkouts?date=`.

## 5. Super-admin insights (platform admin)

`GET /platform/insights?days=30` → per hotel group (tenant) and property: plan, status, rooms, occupied now, staff, active users, jobs (count, on-time %, median completion min), guest requests (count, median response min), express/late checkouts, feedback (count, average, last 5 comments trimmed), inventory (stock value, items below reorder), average worker performance score (from the performance service; k ≥ 5 workers else suppressed), last activity. Plus portfolio totals. Dashboard console page **Insights**: KPI tiles, per-hotel table with status pills, drill-down per hotel, charts (requests per day, feedback trend).

## 6. Config (ASSUMED, platform_api)

`guest_ai_enabled`, `groq_chat_model`, `groq_stt_model`, `chat_temperature`, `chat_history_turns` (6), `chat_max_reply_chars`, `stt_max_mb` (8), `stt_max_seconds` (60), `guest_chat_rate_per_minute` (10/room), `guest_stt_rate_per_minute` (6/room), `feedback_max_chars` (1000). Env: `GROQ_API_KEY` (never in the repo).

## 7. As built in platform_api (13 Oct): response shapes and additions

All paths and request bodies above are implemented unchanged. Additions (no renames):

- **Config names (section 6):** the chat/STT provider is any OpenAI-compatible API: `LLM_BASE_URL`, `LLM_API_KEY` (falls back to
  `GROQ_API_KEY`), `LLM_MODEL` (= `groq_chat_model`, default `openai/gpt-oss-20b`), `LLM_JSON_MODE`, `STT_BASE_URL`, `STT_API_KEY`,
  `STT_MODEL` (= `groq_stt_model`). Other settings use the `HOI_` prefix (see platform_api/README.md).
- **Request menu:** new id `food` ("Food order (room service)", fnb_service), so food orders can be confirmed and estimated on the bill.
- **`GET /public/guest/{token}`** also returns `profile` (public subset: display_name, logo_url, welcome, checkin_time, checkout_time,
  late_checkout, wifi, contacts, amenities, dining, policies, nearby, faq, languages, synthetic), `stay`
  `{checkout: null|{id,time,date,luggage_help,status,due_local}, late_checkout: {status: none|pending|approved|declined, until, note, ...}, feedback_given, feedback_rating}`,
  `local_time`, `today`, `synthetic`. `requests` are the current stay only (since the last checkout), each `{id, title, status, stage, department, at}` (department added 13 Oct for the department avatar)
  with `stage` ∈ open / accepted / in_progress / done (`status` keeps the old friendly words).
- **`GET /public/guest/{token}/requests`** → `{room, requests: [...]}`. **`POST .../actions`** → `{action, ok, ...}` (request: `requests`;
  checkout: the `stay` fields; late_checkout: `late_checkout`; feedback: `rating`). **`proposed_action`** = `{action, params, label, label_hi}`.
- **`GET /hotel/profile`** returns the profile plus `exists` (false = default skeleton not yet saved), `updated_at`, `updated_by`.
  `PUT` takes the same fields (unknown fields rejected; `property_id`/`updated_at` ignored); no e-mail addresses or mobile numbers in text.
- **Guest services (roles: read owner, dept_head, hr; decide owner + dept_head of front_office/housekeeping, else 403):**
  - `GET /guest-services/summary` → `{date, open_requests: [{id, room, title, department, status, stage, kind, created_at, minutes_open}], requests_today, median_response_min, checkouts_today: {count, luggage_help, items}, late_checkouts_pending, feedback_30d: {count, average}, synthetic}`
  - `GET /guest-services/late-checkouts?status=pending,approved` → `[{id, room, until, reason, status, note, decided_by, decided_at, created_at, date}]`
  - `POST /guest-services/late-checkouts/{id}/decide {approve, note}` → the same item (409 if already decided)
  - `GET /guest-services/feedback?days=30` → `{days, count, average, by_day: [{date, count, average}], items: [{id, room, rating, comment, lang, date, created_at}]}`
  - `GET /guest-services/checkouts?date=YYYY-MM-DD` → `{date, items: [{id, room, time, luggage_help, status: scheduled|processing|done|failed, outcome, front_job_id, cleaning_job_id, created_at}]}`
- **`GET /platform/insights?days=30`** → `{days, generated_at, k_min_workers: 5, totals: {hotels, active_hotels, properties, rooms, occupied_now, staff, active_users, jobs, guest_requests, express_checkouts, late_checkouts, feedback, feedback_average, stock_value}, hotels: [{tenant_id, name, plan, status, is_demo, properties: [{id, name, region, rooms, occupied_now}], rooms, occupied_now, occupancy_pct, staff, active_users, jobs: {count, done, on_time_pct, median_completion_min}, guest_requests: {count, median_response_min}, requests_per_day: [{date, count}], checkouts: {express, late_requested, late_approved, late_pending}, feedback: {count, average, last_comments: [{rating, comment, date}], by_day}, inventory: {stock_value, items_below_reorder}, performance: {workers_scored, average_score|null, suppressed, reason?}, last_activity}], note}`.
  Jobs carry no property id, so job/request figures are per tenant; rooms without a property count toward the first property.
- **Worker voice:** `/me/voice/command` → `{intent, reply, lang, proposed_action: null|{action, params, label}}`. `action` = accept / decline /
  start / report_issue (run via `/me/voice/act`) or `photo` `{job_id, kind: before|after}` (UI only: opens the live camera; "start"
  without a before photo and "done" always route there).
- **Express checkout timing:** stored as `scheduled` with `due_at`; released lazily on the next read after that time (same pattern as
  offer expiry), not by a background worker.
- **Speech (added 13 Oct, lead requests):** `STT_PROVIDER` = `groq` (any OpenAI-compatible Whisper, `STT_*`) | `local`
  (faster-whisper on the PC, `LOCAL_STT_MODEL` default `small`, `LOCAL_STT_DEVICE` auto; optional `requirements-local.txt`).
  Spoken replies: browser `speechSynthesis` via `static/shared/voice.js` (soft female Indian voice ranking, picker, mute,
  sentence-by-sentence, Hindi number/time normalisation) or, with `TTS_PROVIDER=sarvam` + `SARVAM_API_KEY`, Sarvam Bulbul via
  `POST /public/guest/{token}/tts` and `POST /me/voice/tts` `{text <= 500, lang}` → `audio/wav` or 204 (= browser speaks);
  24 h audio cache. `GET /public/guest/{token}` adds `voice: {server_tts}`.

## 8. Added 13 Oct (late): homestay mode, recognition points, staffing requests, guest issue taxonomy

- **Property mode** `mode: hotel | homestay` on each property (`GET /workspace/properties`; owner `PATCH /workspace/properties/{id}`
  `{mode, incentive_monthly_budget_cap, recognition_leaderboard_opt_in, recognition{weights,max_points_per_worker,min_jobs,max_share}, portal_api_key}`).
  New properties with ≤ 10 rooms start as homestays (ASSUMED threshold). `portal_api_key` is write-only (`portal_key_set: bool`).
  Demo tenant gains the FICTIONAL "Deodar Nest Homestay, Dhanaulti" (6 rooms DN1-DN6, staff DN01 host / DN02 cook / DN03 helper,
  demo accounts `demo.homestay`, `DN03`). Homestay jobs go to the homestay's own team (no roster needed); `/rooms` and
  `/hotel/profile` take `?property_id=`.
- **Recognition points** (positive only, never for discipline): `GET /me/recognition` (worker: own points + team totals),
  `GET /recognition/summary?month=&property_id=` (owner, HR, department heads: per-person rows by id, not ranked; a leaderboard only
  when the owner opts in). Rules and ASSUMED weights: `platform_api/hoi_platform/services/recognition.py`.
- **Staffing requests**: `POST/GET /staffing/requests`, `POST /staffing/requests/{id}/send` (retry). Forwarded to
  `POST {PORTAL_API_URL}/api/v1/ingest/staffing-request` (default `https://hoi-portal.vercel.app`) with header `X-API-Key: <property key>`
  and body `{external_id, department, skill, date_from, date_to, openings, note}`; on failure the request stays `pending_send`.
- **Guest issue taxonomy** `platform_api/hoi_platform/guest_issues.yaml` (ASSUMED, for HM review): pest_control, water_leak,
  lock_or_door, cleanliness, noise_complaint, lost_item, wifi_problem, safety_alert and medical_help (urgency `urgent`: jobs for
  front office + security, 15 s offer window, emergency numbers 112/108 on the guest page). Rule-based understanding v2 in
  `services/issues.py` (EN / Devanagari / Hinglish, whole words, negation, priority); the LLM's answer is re-checked against it.
  `GET /guest-services/summary` adds `urgent_alerts`.
