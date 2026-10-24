# HOI — Hospitality Operations Intelligence

**Smarter hotels. Happier teams.** One system with five simple apps that helps small hotels and homestays in Uttarakhand
see the rush coming, run every day smoothly and keep good staff: forecast-driven shift plans, automatic job assignment to
whoever is on shift, photo-proof work logs, a guest QR assistant in Hindi and English, staff-leaving risk with talking
points, and the **Uttarakhand Travel Guide** that ties hotels, tourists, job seekers and officials together.

Built for the AI-Tourism Hackathon 2026 (TBI-GEU, Team Innov8). **All hotel, staff and business data is synthetic demo
data** (ready for a pilot, not yet validated on a real property). Full context of every feature and decision:
[docs/HOI_FULL_CONTEXT.md](docs/HOI_FULL_CONTEXT.md).

## Live apps

Free hosting sleeps after about 15 minutes idle: run `python scripts/wake_demo.py` 2–3 minutes before a demo.
Demo accounts (all passwords `123456`, demo data only) are listed in `credentials.local.md` (gitignored).

| App | Link | Demo sign-in |
|---|---|---|
| Uttarakhand Travel Guide (tourists, businesses, officials) | https://hoi-portal.vercel.app | public; `demo.admin`, `demo.officer.rudraprayag`, `demo.business`, `demo.agency`, `demo.seeker` |
| Hotel portal (owner / managers) | https://hoi-dashboard.onrender.com | `himsagar.owner`, `himsagar.hr`, `himsagar.housekeeping`, `himsagar.store`; homestay: `deodar.owner` |
| Staff app (phone) | https://hoi-platform-api.onrender.com/worker/ | staff ID, e.g. `HS05`, `HS19` |
| Guest page (room QR) | Hotel portal → Rooms & guests → a room's QR link | none |
| HOI console (HOI team) | https://hoi-platform-admin.onrender.com | `hoi.admin` |
| Marketing website | https://hoi-website.vercel.app | public |
| API docs | https://hoi-platform-api.onrender.com/docs · https://hoi-ops.onrender.com/docs | ops data needs the `X-HOI-Key` header |

## Folders

| Folder | What it is | Port | MongoDB database |
|---|---|---|---|
| `ml/` | Synthetic data generator, models (forecast, attrition, workload, pulse), evaluation | none | none (files) |
| `backend/` | ML / ops API: forecast, attrition scoring, OR-Tools roster, tasks, closed loop, voice (deployed on Render) | 8000 | `hoi_ops` |
| `platform_api/` | HOI platform API: accounts, hotel groups, dispatch, rooms, photo proof, inventory with GST, audit. Serves the **staff app** (`/worker/`) and **guest QR pages** (`/guest/`) | 8100 | `hoi_platform` |
| `portal/` | Uttarakhand Travel Guide (not an official government site): destinations with weather/roads/crowd, verified stays, local experiences, trips, festivals, jobs and staffing agencies, complaints, business registration, officials' analytics and the state data layer | 8200 | `hoi_portal` |
| `dashboard/` | Streamlit admin portals from one codebase (`ADMIN_PORTAL`): **hotel admin portal** (hotel pages by role, employee view; default) and **super-admin portal** (`ADMIN_PORTAL=super`: hotels, insights, audit) | 8501 hotel · 8502 super | none |
| `website/` | Static marketing site (`site/index.html`), live at https://hoi-website.vercel.app | none | none |
| `docs/` | Full project context, pitch script and deck, real-data results, market and competitors, portal API, MongoDB conventions, usability test kit | | |
| `scripts/` | One-command runner, demo wake-up, scenario simulator, demo model run, Mongo tools | | |

## Setup (Windows PowerShell, once)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r ml\requirements.txt -r backend\requirements.txt -c backend\requirements-lock.txt
pip install -r platform_api\requirements.txt -r portal\requirements.txt -r dashboard\requirements.txt
copy .env.example .env      # set MONGODB_URI (Atlas) and the secrets; .env is gitignored
python scripts\check_mongo.py   # pings Atlas, lists the three databases
```

Without `MONGODB_URI` every service falls back to an in-memory database (fine for trying things, data is lost on restart).

## Run everything (one command)

```powershell
.\scripts\hoi.ps1 start            # all four services on MongoDB Atlas (.env)
.\scripts\hoi.ps1 start -Offline   # no internet: in-memory database, demo data re-seeded
.\scripts\hoi.ps1 status
.\scripts\hoi.ps1 stop
```

Logs: `.logs\<service>.log`. If PowerShell blocks the script, run it once with `powershell -ExecutionPolicy Bypass -File scripts\hoi.ps1 start`.

## Run by hand (one terminal each, from the repo root; load .env first)

```powershell
Get-Content .env | Where-Object { $_ -match '^[A-Z_]+=' } | ForEach-Object { $k,$v = $_ -split '=',2; Set-Item "env:$k" $v }

$env:PORT=8000; python -m backend.serve                                              # ML / ops API
cd platform_api; python -m uvicorn hoi_platform.main:app --port 8100                  # platform API + staff app + guest pages
cd portal;       python -m uvicorn hoi_portal.main:app --port 8200                    # tourism portal
cd dashboard; $env:API_BASE_URL="http://127.0.0.1:8000"; $env:PLATFORM_API_URL="http://127.0.0.1:8100"; $env:ADMIN_PORTAL="hotel"; streamlit run app.py --server.port 8501   # hotel admin portal
cd dashboard; $env:API_BASE_URL="http://127.0.0.1:8000"; $env:PLATFORM_API_URL="http://127.0.0.1:8100"; $env:ADMIN_PORTAL="super"; streamlit run app.py --server.port 8502   # super-admin portal
```

| Open | Link | Sign in |
|---|---|---|
| Hotel admin portal | http://localhost:8501 | demo role buttons (owner, HR, department head, storekeeper, employee); platform admin chooses a hotel |
| Super-admin portal (HOI Platform Admin) | http://localhost:8502 | "Platform admin" demo button (hotel accounts are refused) |
| Staff phone app | http://localhost:8100/worker/ | demo employee `HS05` |
| Tourism portal | http://localhost:8200 | tourists need none; demo state admin, district officer, business under "Sign in" |
| API docs | http://localhost:8000/docs · http://localhost:8100/docs · http://localhost:8200/docs | |

The ops API is open when `HOI_OPS_API_KEY` is unset (local runs). When it is set (production), the dashboards need the
same `HOI_OPS_API_KEY` (sent as the `X-HOI-Key` header); `/health` stays open.

Docker: `docker compose up --build` runs all four services against the Atlas URI in `.env` (written, not build-tested here).

## Tests and quality (all offline on mongomock)

```powershell
$env:MONGODB_URI="mongomock://"
cd ml;           python -m pytest -q             # 335 passed, 1 skipped
cd backend;      python -m pytest -q             # 175 passed (about 10 min; -m "not slow" for a quick run)
cd platform_api; python -m pytest -q             # 318 passed
cd portal;       python -m pytest -q             # 108 passed
python -m pytest -q scripts\tests               # 9 passed: 24-room hotel day simulation and roster stress
cd dashboard;    python tests\smoke.py           # 84 checks: every hotel/employee page + access and portal checks
cd dashboard;    $env:ADMIN_PORTAL="super"; python tests\smoke.py   # 20 checks: console pages, hotel roles refused
cd dashboard;    python -m pytest -q tests\test_today_logic.py tests\test_timefmt.py   # 6 passed
ruff check platform_api portal dashboard; ruff format --check platform_api portal dashboard
```

CI (`.github/workflows/ci.yml`) runs all of the above. Live QA on the deployed apps (14 Oct 2026): hotel side 242 checks
and Travel Guide 330 checks; every failure found was fixed and redeployed.

## Results on real data

The forecast was also tested on the public Hotel Booking Demand dataset (two Portuguese hotels, held-out Mar–Aug 2017):
one day ahead it was off by **1.9 rooms vs 10.9** for "same day last week" (−83%); 7 days ahead 5.3 vs 10.9 (−51%).
Staff-leaving ranking on real records: ROC-AUC 0.66 vs 0.55 for a checklist (1,129 people). Details:
[docs/REAL_DATA_RESULTS.md](docs/REAL_DATA_RESULTS.md).

## Pitch and demo material

| File | What |
|---|---|
| [docs/HOI_FULL_CONTEXT.md](docs/HOI_FULL_CONTEXT.md) | Everything built, every feature and the thinking behind it |
| [docs/PITCH_SCRIPT.md](docs/PITCH_SCRIPT.md) | 3-minute pitch, 60 s version, framework, hard-question answers |
| [docs/HOI_Final_Pitch.pptx](docs/HOI_Final_Pitch.pptx) | 11-slide minimal deck |
| [docs/USABILITY_TEST.md](docs/USABILITY_TEST.md) | 5-person usability test kit |
| `videos/`, `HOI_Screenshots.zip` | Product film and screenshots of every screen (local only, not in git) |

## Pre-work declaration (team to confirm before submission)

Following the technical plan (Section 0), we declare what existed before the build window (13 Oct 2026, 11:00):

- **Built before the event (team, Oct 5–11 per the plan):** the synthetic data generator and data, the four trained models and their
  model cards, the ML/ops API (forecast, attrition, CP-SAT roster, tasks, closed loop, voice) and its tests. *Team: confirm dates.*
- **Built in the early hours of 13 Oct (before 11:00), per file dates:** the first version of the Streamlit dashboard, the platform API
  (SQLite at that time), the staff app, guest QR page and marketing website.
- **Built during the event:** the unified repository, the move of all three services to MongoDB Atlas, the tourism portal (API and web app),
  the UX restructure, and these docs.
- **AI assistance:** large parts of the code and documents were written with an AI coding assistant (Claude Code) under the team's direction
  and review. *Team: state this the way the organisers' rules ask.*
- Organisers' written answer on pre-built work: *paste here.*

## Changes from the technical plan (v2.0)

| Plan | Now | Why |
|---|---|---|
| Telegram bot for staff (Tier 1) | **Dropped.** Staff phone app (installable web app at `/worker/`): shifts, live job pings, accept/done, live-camera photo proof, supplies, Hindi/English | No bot token or public webhook needed, works on any phone browser, and adds photo proof the bot could not |
| SQLite, zero network | MongoDB Atlas, one database per service; in-memory fallback (`MONGODB_URI=mongomock://`) for an offline demo | Multi-hotel SaaS and the portal need a shared hosted database |
| Attrition: LightGBM + SHAP | Logistic regression with per-feature contributions (XGBoost kept as the comparison; all training on the GPU) | Better on our data: ROC-AUC 0.691 vs 0.666 |
| Cut list: inventory, guest checklists, full auth | Built: inventory with GST, guest QR requests, accounts with roles | Requested for the SaaS version; shown as extensions, not core |
| `make demo` | `scripts\hoi.ps1 start` (one command, all services) | Team rule: Windows, no Makefiles |

## Ethics and limitations

- All data is synthetic, from a seeded generator whose attrition drivers were **planted** by us; the models partly rediscover that design. No result is a real-world finding.
- Models are reported beside baselines: forecast MAPE 6.7/7.2/10.3 % vs seasonal-naive ~13.7 %; attrition (resignation) ROC-AUC 0.691 vs rules 0.542. The effect of interventions in the closed loop is a **simulation**, and small (largest −0.0123).
- Risk bands are within-week rankings to offer support ("flagged for review"), never grounds for adverse action. Employees never see risk scores.
- No name, gender, age, religion, caste, health or family data is stored or used; imports containing such columns are rejected.
- Rest hours, workload standards and Hindi wording are ASSUMED until the hospitality-management student confirms them; statutory rules (rest hours, Form C) need a qualified person.
- The Travel Guide is not an official Government of Uttarakhand site; its businesses, statistics and complaints are synthetic, and its reference facts are marked "approximate, verify". Joining the official state portal is a proposal to discuss with the department.
- Staff-leaving risk is shown only as a prompt to talk; pay-related reasons are visible to the owner and HR only, and department heads see only their own team.

## Before real data (not done yet)

- Change the demo passwords (`123456`) and rotate every API key shared in chat; rotate the Atlas password if it was ever shared; set `MONGODB_URI` and `HOI_ENV=production` in each host's secret store (production refuses unsafe settings).
- Redis for rate limits if any API runs more than one instance; SSO/OIDC; TLS; monitoring; backups (Atlas).
- DPDP Act review; a real-property pilot; native-speaker review of Hindi; verify every "approximate, verify" fact in the portal with the issuing authority.
