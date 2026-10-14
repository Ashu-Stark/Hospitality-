# HOI — Hospitality Operations Intelligence · Frontend

Streamlit dashboard for staff attrition risk, occupancy forecast, roster, closed-loop interventions and tasks.
**All data is synthetic.** Risk bands are rankings that flag people for a supportive check-in. They are not predictions that someone will resign, and they are never grounds for adverse action.

## Run locally

```bash
cd dashboard
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # Windows: copy .env.example .env
streamlit run app.py            # hotel admin portal, http://localhost:8501
```

## Two portals, one codebase

The same code (and the same Docker image) serves two separate admin portals. `ADMIN_PORTAL` picks one per process:

| `ADMIN_PORTAL` | Portal | Who signs in | Pages |
|---|---|---|---|
| `hotel` (default) | **Hotel admin portal** · title "&lt;hotel&gt; · Hotel admin", hotel logo/brand | owner, HR, department head, storekeeper, employee; platform admins after choosing a hotel | Home, Overview … Hotel profile, Guest services, Hotel setup (voice), Setup, Admin; employee app for employees. No console pages. |
| `super` | **HOI Platform Admin** · navy header, "Platform admin" badge | platform admins only; hotel accounts are refused with a link to the hotel portal | Home (summary), Hotels, Insights, Audit log |

```bash
# macOS/Linux
ADMIN_PORTAL=hotel SUPER_PORTAL_URL=http://localhost:8502 streamlit run app.py --server.port 8501
ADMIN_PORTAL=super HOTEL_PORTAL_URL=http://localhost:8501 streamlit run app.py --server.port 8502
```

```powershell
# Windows PowerShell (one terminal each)
$env:ADMIN_PORTAL="hotel"; $env:SUPER_PORTAL_URL="http://localhost:8502"; streamlit run app.py --server.port 8501
$env:ADMIN_PORTAL="super"; $env:HOTEL_PORTAL_URL="http://localhost:8501"; streamlit run app.py --server.port 8502
```

* `HOTEL_PORTAL_URL` (super portal): where "Open in hotel portal" and the sign-in hint point (default `http://localhost:8501`).
* `SUPER_PORTAL_URL` (hotel portal): shown to platform admins (default `http://localhost:8502`).
* **Platform admin in the hotel portal:** signs in with the platform account, must choose a hotel (audited impersonation,
  `platform.open_workspace` in the audit log), then sees that hotel's pages with a "Viewing as platform admin — audited"
  banner and an **Exit** back to hotel selection. The console's "Open in hotel portal" link passes `?hotel=<id>` so the
  hotel is highlighted on the picker. Hotels are never opened inside the super-admin portal.
* Each portal keeps its own "stay signed in" cookie (`hoi_rt` / `hoi_rt_admin`), because cookies on one host are shared across ports.
* The portal split is a usability boundary. Security still comes from the platform API, which checks the role on every call
  (console endpoints are platform-admin only).

## MOCK vs LIVE

There is one switch, `USE_MOCKS` in `dashboard/.env`:

| Setting | Behaviour |
|---|---|
| `USE_MOCKS=true` | Serves `dashboard/mocks/*.json`. Works offline; mutations (tasks, ack/done, clock, reset, loop) run in an in-memory mock. |
| `USE_MOCKS=false` | Calls `API_BASE_URL` (default `https://hospitality-management-9jdk.onrender.com`). |

`HOI_OPS_API_KEY`: when the ops API has a shared secret, set the same value here; `lib/api_client.py` sends it as
`X-HOI-Key`, but only to `API_BASE_URL`, `OPS_API_URL`, `https://hoi-ops.onrender.com` or a local server (never to another
"Server address" a workspace enters). A wrong or missing key shows "access key ... missing or wrong".

You can also switch at runtime on **Admin → Data source** (per browser session); no code changes are needed.
The top-bar badge always shows `MOCK DATA` or `LIVE`.

> Render's free tier sleeps. The first call can take 20–60 s, and a restart wipes the backend's SQLite (tasks and rosters).
> If the Overview looks empty in LIVE mode, run the **Closed loop** once.

Mocks are **captured from the live API**, so their shapes match it exactly. To re-sync after a backend change, run:

```bash
python mocks/_fixtures.py --refresh   # re-captures; side effect: POST /loop/run (idempotent). Never calls /demo/reset.
```

When the frontend sits inside the monorepo, `dashboard/mocks/` takes precedence; `ml/data/mocks/*.json` is the fallback, and `ml/data/demo/hero_display_names.json` is the preferred hero-name file.

## Structure

```
app.py                 router (st.navigation): portal (ADMIN_PORTAL) → login → console / hotel pages / employee app, by role and plan modules
login.py               sign in, join with invite code, one-click demo accounts (rendered by lib/login_ui.py)
home.py                hotel landing page + first-run welcome dialog
pick_hotel.py          hotel portal: platform admin chooses the hotel to open (audited)
pages/                 hotel dashboard: 1 Overview … 13 Inventory (numbered files)
console/               super-admin portal: 0 Home (summary), 1 Hotels (onboard/suspend/plans/modules), 3 Insights, 2 Audit log
employee/              employee app: 1 My day, 2 Jobs, 3 Supplies, 4 My tasks
lib/platform.py        client for the HOI platform API (platform_api/), embedded or remote (PLATFORM_API_URL)
lib/api_client.py      client for the ML/ops API (Render) or mock fixtures (USE_MOCKS)
lib/auth.py            session tokens + page access per role (the API re-checks every call)
lib/access.py          page sets per portal and surface; modules per plan
lib/portal.py          portal chrome: navy platform-admin header vs hotel brand/logo, impersonation banner, open-in-hotel-portal links
lib/config.py          settings, incl. portal() / HOTEL_PORTAL_URL / SUPER_PORTAL_URL
lib/tenancy.py         current hotel group (from the API), data-source switch per tenant
lib/dispatch.py        on-shift set from the roster (the dispatch engine runs in the API)
lib/worker_ui.py       shared phone UI: ping, accept/decline, before/after photos
lib/models.py, data.py, theme.py, charts.py, ui.py, tour.py, nav.py, mock_backend.py
mocks/                 captured ML API fixtures + _fixtures.py
tests/smoke.py         renders every page of the portal as the right role through the API, plus portal rules
                       (python tests/smoke.py [--live]; ADMIN_PORTAL=super python tests/smoke.py)
```

## Pages

| # | Page | Endpoints | What it shows |
|---|---|---|---|
| – | Home | `GET /health` | Hero banner, quick actions, 3-minute demo story, model versions and honest metrics |
| 1 | Overview | `/metrics/overview`, `/forecast`, `/attrition/score`, `/roster/{id}` | Cost / understaffing / on-time / flagged / ROI tiles (editable **ASSUMPTION** replacement cost), 7-day forecast with band + alerts, top-5 "needs attention", department load table |
| 2 | Risk list | `/attrition/score`, `/roster/{id}` | Band strip split permanent/seasonal, filters, sortable table with basis tags, row click → driver chart by support level, CSV export (IDs only) |
| 3 | Employee | `/attrition/score`, `heroes.json`, playbook, `POST /tasks` | Header, 12-week risk and rank trajectory (heroes), drivers in plain language, playbook actions → Create task, season-end callout |
| 4 | What-if | `/attrition/rescore` | Inputs from the API (`protected_weekends_off` + reported features), before/after cards with delta badge, session history |
| 5 | Roster | `/roster/generate`, `/roster/{id}` | Day strip, generate (protect flagged), honest infeasible banner, dept × day grid, cell drill-down, fairness histogram, soft-goal trade-offs, baseline vs protected diff |
| 6 | Closed loop | `/loop/run` | 4-step story: flagged → interventions → roster deltas → re-score; totals; honest small-effect note |
| 7 | Tasks | `/tasks`, `/tasks/{id}/ack|done`, `/demo/clock` | Kanban, overdue / 50% / 90% highlights, optimistic Ack/Done with rollback, demo-clock speed, live refresh |
| 8 | Voice | `/voice/ingest` | Demo clip (`clip_01.wav`) → transcript + extraction, confirm → task; friendly 503/422 |
| 10 | Dispatch | platform `/dispatch/*` + ML `POST /tasks` | Live requests auto-offered to the best on-shift worker; timed ping with countdown; decline/timeout → next; "Why this worker?" score breakdown; supervisor fallback; voice-note → dispatch |
| 11 | Worker preview | platform `/dispatch/*` | Phone-style preview: ping with countdown ring, Accept/Decline, camera-only **before** photo to start and **after** photo to finish, server-time stamp + SHA-256 + tamper check, time on job |
| 12 | Setup | platform `/workspace/*` | Owner onboarding (organization → properties → staff by ID, privacy-guarded → data source test → team), Team & access (users, enable/disable, invite codes), plan |
| 13 | Inventory | platform `/inventory/*` + ML `/forecast` | Stock value, low stock, forecast-aware vs static reorder, requests → issue, PO → GRN (partial), stock counts, wastage, ledger, catalog, CPOR, linen par |
| 9 | Admin | all | MOCK/LIVE toggle, `/health` versions + dataset hashes, reset with confirmation, raw JSON explorer, schema check, mock provenance |

## Accounts, hotel groups, dispatch, inventory

* **Surfaces:** signed-out visitors see the sign-in page of their portal; **platform admins** use the super-admin portal (onboard hotel groups, plans, modules, suspend, insights, audit) and can open any hotel in the hotel portal (audited); **hotel staff** use the hotel admin portal with pages for their role (owner, HR, department head, storekeeper); **employees** get a separate mobile-first app there.
* **Data:** all of this lives in the HOI platform API (`platform_api/`). By default it runs *inside* the Streamlit process (`PLATFORM_API_URL=embedded`), with real routing, validation and tokens; point `PLATFORM_API_URL` at a deployed instance to split them.
* **First-time users:** demo role cards on the sign-in page, a welcome dialog, and a 9-step guided tour on the demo hotel.
* Accepted dispatch jobs are mirrored into the ML backend's task board (idempotent key `dispatch:{tenant}:{job}`).
* **Not built:** SSO, billing, Telegram push for pings. A browser refresh signs the user out (Streamlit sessions).

## What is backend-integrated vs mock-only

* **Integrated (LIVE verified 2026-10-13):** health, forecast, score, rescore, roster generate/get, tasks list/create/ack/done, demo clock, loop run, metrics, voice ingest, reset (UI only, not exercised against live).
* **Mock-only / derived:**
  * `heroes.json`: 12-week trajectories are **illustrative**, anchored to each hero's live current score. No endpoint serves history.
  * `hero_display_names.json`: H901 Sunita, H902 Rajesh, H903 Meena, H904 Arun, H905 Deepak. This mapping is inferred from each hero's driver pattern; replace it with the repo file.
  * `playbook.json`: built from the live `actions` field plus written explanations.
  * `roster_infeasible.json`: example for rehearsing the infeasible banner (MOCK toggle on the Roster page).

## Known API gaps the UI works around

* `/attrition/score` has no department, role or tenure. Department is joined from `roster.people`; role and tenure are not shown.
* No contract end date, so the season-end callout cannot show days remaining.
* Roster understaffing is reported in **hours short** per department/day/shift, not headcount. The grid shows staff assigned plus hours short.
* `/voice/ingest` takes a server-side clip name, not an uploaded file. Only `clip_01.wav` exists on the server.
* `/demo/clock` only accepts `multiplier` (no "advance by N minutes").
