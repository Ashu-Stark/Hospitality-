# HOI — Hospitality Operations Intelligence

Retention, forecast-driven rosters, live dispatch with photo proof and demand-aware inventory for hill hotels, plus a
concept **Uttarakhand Tourism & Hospitality Portal** that ties hotels, tourists and officials together.
Built for the AI-Tourism Hackathon 2026 (TBI-GEU). **All data is synthetic** (TRL 4: ready for a pilot, not validated on a real property).

## Folders

| Folder | What it is | Port | MongoDB database |
|---|---|---|---|
| `ml/` | Synthetic data generator, models (forecast, attrition, workload, pulse), evaluation | none | none (files) |
| `backend/` | ML / ops API: forecast, attrition scoring, OR-Tools roster, tasks, closed loop, voice (deployed on Render) | 8000 | `hoi_ops` |
| `platform_api/` | HOI platform API: accounts, hotel groups, dispatch, rooms, photo proof, inventory with GST, audit. Serves the **staff app** (`/worker/`) and **guest QR pages** (`/guest/`) | 8100 | `hoi_platform` |
| `portal/` | Tourism portal (concept, not an official site): directory, destinations with weather/roads/crowd, festivals, dictionary, rules, grievances, business registration, officials' analytics | 8200 | `hoi_portal` |
| `dashboard/` | Streamlit manager dashboard: login, platform console, 15 hotel pages, employee view | 8501 | none |
| `website/` | Static marketing site (`site/index.html`), live at https://hoi-portal.vercel.app/site/ | none | none |
| `docs/` | Tech stack, MongoDB conventions, portal spec and API, scope, competitors, TimesFM, UX review | | |

Flow diagrams: https://claude.ai/artifact/JHsoddyLwTtaLm3ktCohgK (private until shared).

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
cd dashboard; $env:API_BASE_URL="http://127.0.0.1:8000"; $env:PLATFORM_API_URL="http://127.0.0.1:8100"; streamlit run app.py
```

| Open | Link | Sign in |
|---|---|---|
| Manager dashboard | http://localhost:8501 | demo role buttons |
| Staff phone app | http://localhost:8100/worker/ | demo employee `E134` |
| Tourism portal | http://localhost:8200 | tourists need none; demo state admin, district officer, business under "Sign in" |
| API docs | http://localhost:8000/docs · http://localhost:8100/docs · http://localhost:8200/docs | |

Docker: `docker compose up --build` runs all four services against the Atlas URI in `.env` (written, not build-tested here).

## Tests and quality (all offline on mongomock)

```powershell
$env:MONGODB_URI="mongomock://"
cd ml;           python -m pytest -q             # 335 passed, 1 skipped
cd backend;      python -m pytest -q -m "not slow"   # 33 passed
cd platform_api; python -m pytest -q             # 35 passed
cd portal;       python -m pytest -q             # 36 passed
cd dashboard;    python tests\smoke.py           # 22 pages + 3 access checks
ruff check platform_api portal dashboard; ruff format --check platform_api portal dashboard
```

CI (`.github/workflows/ci.yml`) runs all of the above.

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
| Attrition: LightGBM + SHAP | Logistic regression with per-feature contributions (LightGBM kept as the comparison) | Better on our data: ROC-AUC 0.691 vs 0.652 |
| Cut list: inventory, guest checklists, full auth | Built: inventory with GST, guest QR requests, accounts with roles | Requested for the SaaS version; shown as extensions, not core |
| `make demo` | `scripts\hoi.ps1 start` (one command, all services) | Team rule: Windows, no Makefiles |

## Ethics and limitations

- All data is synthetic, from a seeded generator whose attrition drivers were **planted** by us; the models partly rediscover that design. No result is a real-world finding.
- Models are reported beside baselines: forecast MAPE 6.7/7.2/10.3 % vs seasonal-naive ~13.7 %; attrition (resignation) ROC-AUC 0.691 vs rules 0.542. The effect of interventions in the closed loop is a **simulation**, and small (largest −0.0123).
- Risk bands are within-week rankings to offer support ("flagged for review"), never grounds for adverse action. Employees never see risk scores.
- No name, gender, age, religion, caste, health or family data is stored or used; imports containing such columns are rejected.
- Rest hours, workload standards and Hindi wording are ASSUMED until the hospitality-management student confirms them; statutory rules (rest hours, Form C) need a qualified person.
- The tourism portal is a concept: not an official Government of Uttarakhand site; its businesses, statistics and complaints are synthetic, and its reference facts are marked "approximate, verify".

## Before real data (not done yet)

- Rotate the Atlas password if it was ever shared; set `MONGODB_URI` and `HOI_ENV=production` in each host's secret store (production refuses unsafe settings).
- Redis for rate limits if any API runs more than one instance; SSO/OIDC; TLS; monitoring; backups (Atlas).
- DPDP Act review; a real-property pilot; native-speaker review of Hindi; verify every "approximate, verify" fact in the portal with the issuing authority.
