# HOI — Hospitality Operations Intelligence

**Audience:** the team, mentors and judges. **As of:** 2026-10-13. All versions below are the ones installed and tested on the build machine
unless marked *planned* or *team ML repo* (code not in this workspace).

---

## 1. What we are making (one minute)

**HOI is an operations and retention layer for small hill hotels and homestays** (first target: Uttarakhand). It sits next to a hotel's
PMS (e.g. eZee) and runs the day-to-day of the staff:

- **Forecast** occupancy for the next 1 / 7 / 30 days, with an honest uncertainty band.
- **Roster** staff fairly to that forecast with a constraint solver that refuses to publish a rule-breaking roster.
- **Spot** who may need support (attrition-risk ranking with plain-language reasons), never to punish.
- **Close the loop:** turn a risk into tasks and a protected-weekend roster, then re-score and show what changed, even when the change is small.
- **Dispatch** live requests (guest QR codes, voice notes, managers) to the best on-shift worker, with before/after photo proof.
- **Run rooms and stores:** room turnaround board, inventory with forecast-aware reordering and GST purchase orders.
- **Sell it as SaaS:** many hotel groups, each isolated, onboarded by an HOI platform admin, with separate apps for managers, staff and guests.

**Status:** working prototype on synthetic data (TRL 4). Every accuracy number is from a seeded synthetic hotel, not a real property.

## 2. Summary pointers

- **4 surfaces:** manager dashboard (Streamlit) · staff phone app (PWA, Hindi/English) · guest QR page · marketing website.
- **2 back ends:** the team's **ML / ops API** (forecast, attrition, roster solver, tasks, closed loop, voice) and our **HOI platform API** (accounts, hotels, dispatch, rooms, photos, inventory, audit).
- **4 models:** occupancy forecast, attrition risk (+ contract-date rule for seasonal staff), workload, pulse. Every one is reported beside a simple baseline.
- **1 solver:** Google OR-Tools CP-SAT for weekly rosters, with a greedy fallback.
- **6 roles:** platform admin, owner/GM, HR, department head, storekeeper, employee; each sees only its pages, and the API re-checks every call.
- **Security:** PBKDF2 passwords, 30-min JWT + rotating refresh tokens with reuse detection, rate limits, CSP, tenant isolation from the token, audit log, production config guard.
- **Privacy by design:** staff by ID only; imports with name, gender, religion, caste, health or family columns are rejected; guests give nothing personal; workers never see risk scores.
- **Quality:** 28 API tests, 22-page smoke test as real roles, browser end-to-end runs (Playwright + Chrome, fake camera), ruff lint + format, CI workflow.
- **Python everywhere** except the three small browser apps (plain HTML/CSS/JS, no build step).

## 3. What makes HOI different

| # | Differentiator | Why it matters | Evidence in the build |
|---|---|---|---|
| 1 | **Closed loop:** risk → interventions → re-solved roster → re-score | Competitors either schedule (Legion, NymbleUp) or score attrition (inFeedo, Darwinbox); none publicly connect both and measure the effect | `/loop/run`, Closed-loop page; reports small effects honestly (largest change 0.0123 in the demo) |
| 2 | **Retention-aware dispatch** | Auto-assign avoids piling extra jobs on staff already flagged for overload (−15 / −6 score) | Dispatch engine; "Why this worker?" breakdown on every offer |
| 3 | **Forecast-aware purchasing** | Reorder quantities follow the same occupancy forecast as the roster, not static par | 4 demo items look fine on par but would run short in the busy week |
| 4 | **Honest, explained outputs** | Each driver is labelled supported / weakly supported / unsupported; models shown beside baselines; "flagged for review", never "will quit" | Risk list, employee page, model cards |
| 5 | **A solver that will not lie** | An infeasible week returns the exact short shifts, not a partial roster | Roster page infeasible banner |
| 6 | **India hill-hotel native** | Char Dham season, festivals, seasonal contracts (separate contract-date band), GST purchase orders, Hindi staff app | Synthetic generator, rooms/inventory, staff app |
| 7 | **Frontline-first staff app** | Live-camera-only proof with server time + SHA-256, job pings with vibration, works on cheap Android phones | `/worker/` PWA, verified end-to-end in Chrome |
| 8 | **Privacy guard enforced in code** | Sensitive columns rejected server-side; workers never see colleagues' risk bands | API tests |

**Where we are weaker (say it before a judge does):** no real-hotel validation yet; not a PMS, payroll or attendance system of record; one property scale tested; pulse score is simulated; no SSO, billing or certifications yet. Full comparison: `docs/COMPETITORS.md`.

## 4. Architecture

```
 Browsers / phones
 ┌────────────────────┐  ┌──────────────────────┐  ┌──────────────────┐  ┌───────────────────┐
 │ Manager dashboard  │  │ Staff app (PWA)      │  │ Guest QR page    │  │ Marketing website │
 │ Streamlit (Python) │  │ HTML/CSS/JS, /worker │  │ HTML/JS, /guest  │  │ static HTML       │
 └──────┬─────────┬───┘  └──────────┬───────────┘  └────────┬─────────┘  └───────────────────┘
        │         │ HTTPS + JWT     │ HTTPS + JWT            │ HTTPS (room token, no login)
        │         └────────────┬────┴────────────────────────┘
        │ HTTPS                ▼
        │          ┌─────────────────────────────────────────────┐
        │          │ HOI platform API (FastAPI)  backend/         │
        │          │ auth · tenants · dispatch · rooms · photos   │
        │          │ inventory+GST · audit · serves /worker /guest│
        │          │ SQLite (WAL) + photo files                   │
        │          └─────────────────────────────────────────────┘
        ▼
 ┌─────────────────────────────────────────────┐
 │ ML / ops API (team's FastAPI, Render)       │   or frontend/mocks/*.json when USE_MOCKS=true
 │ forecast · attrition score/rescore · roster │
 │ (OR-Tools) · tasks + reminders · closed loop│
 │ · metrics · voice · demo clock · SQLite     │
 └──────────────────────┬──────────────────────┘
                        ▼
 ┌─────────────────────────────────────────────┐
 │ ML layer (team ML repo): synthetic generator│
 │ LightGBM, scikit-learn, joblib artifacts    │
 └─────────────────────────────────────────────┘
```

Data rules: the manager dashboard is the only client of the ML API; the platform API never trusts a client-supplied tenant (it comes from the signed token); the dashboard publishes the roster's on-shift snapshot to the platform API so dispatch can rank workers.

## 5. Tech stack in detail

### 5.1 Language and runtime

| Item | Choice | Why |
|---|---|---|
| Main language | **Python 3.12.4** (plan: 3.13 in the ML repo) | One language for data, models, APIs and dashboard |
| Browser apps | Plain **HTML5, CSS3, ES2020 JavaScript** | No build step; tiny; strict CSP possible |
| Environments | `venv` per app; `pip` requirements files | Simple, reproducible |

### 5.2 ML layer *(team ML repo; versions per the project docs)*

| Component | Technology | Notes / results on synthetic data |
|---|---|---|
| Synthetic data generator | numpy (seeded `Generator`, `rng.spawn`), pandas, PyYAML config | 45-room hill property, ~55 staff, Char Dham peak, festivals, weather, 5 scripted demo employees kept out of training; byte-identical regeneration |
| Occupancy forecast | **LightGBM** + seasonal-naive ensemble; split-conformal interval | MAPE 6.7 / 7.2 / 10.3 % (1/7/30 d) vs seasonal-naive ~13.7 %; the 80 % band covered ~70 / 68 / 56 % |
| Attrition (permanent staff) | **scikit-learn logistic regression**, Platt calibration; LightGBM compared | ROC-AUC 0.691 / PR-AUC 0.119 vs rules 0.542; LightGBM 0.652 |
| Attrition (seasonal staff) | Contract-date rule | ROC-AUC 0.736 / PR-AUC 0.316 |
| Drivers / explanations | Logistic contributions (log-odds) grouped into 7 driver categories, each tagged with its support level | Same model for score and explanation |
| Workload, pulse | LightGBM / HistGradientBoosting regressors | Workload MAE 0.053 vs naive 0.073; pulse 0.250 vs 0.257 (marginal) |
| Packaging | joblib artifacts + metrics.json, model_card.md, feature_list.json, dataset hash | Shown on the Admin page (`/health`) |
| Evaluation | Time-based splits with a 90-day gap, oracle ceiling, multi-seed checks, 58 validation checks, 330+ pytest tests | |
| Challenger (assessed) | **Google TimesFM 2.5** (Apache-2.0) | CPU test: 5.8 % vs 11.0 % MAPE on our own synthetic series; ~1.1 GB RAM, so a batch job, not in the API. TimesFM 3.0 is non-commercial. See `docs/TIMESFM.md` |

### 5.3 ML / ops API *(team backend, live at hospitality-management-9jdk.onrender.com)*

| Component | Technology |
|---|---|
| Framework | FastAPI + Pydantic, uvicorn |
| Roster solver | **Google OR-Tools CP-SAT** (hard: leave, rest, weekly off, max consecutive days, headcount, skills; soft: understaffing, overtime, fairness, protected-weekend bonus), 10 s limit, greedy fallback |
| Jobs | APScheduler: reminders at 50 % / 90 % of deadline, escalation, demo clock |
| Storage | SQLite via SQLAlchemy |
| Voice | Swappable providers: Groq Whisper / Sarvam / faster-whisper, plus LLM extraction with a glossary. **The live demo currently uses a cached reference transcript** (`fallback_used: true`) |
| Hosting | Render (free tier: sleeps; a restart resets its SQLite) |
| Mock mode | `MOCK=1` serves fixtures; our frontend also ships fixtures captured from the live API |

### 5.4 HOI platform API *(ours, `backend/`)*

| Concern | Technology / design | Version |
|---|---|---|
| Web framework | **FastAPI** on Starlette, **Pydantic v2** validation | fastapi 0.143.0, starlette 1.7.0, pydantic 2.14.1 |
| Server | **uvicorn** (ASGI), one worker | 0.54.0 |
| Storage | **SQLite** (WAL mode, transactions, additive migrations); photos on disk | stdlib `sqlite3` |
| Layers | `db` → `services` (pure business logic, typed errors) → `routers` (HTTP) → `main` | |
| Auth | Passwords **PBKDF2-HMAC-SHA256** (200 k iterations, per-user salt, constant-time compare, equal timing for unknown users); lockout after 5 failures | stdlib `hashlib`, `hmac` |
| Tokens | **JWT HS256** access tokens (30 min) + opaque **refresh tokens** (14 days, stored as SHA-256, rotated on use, reuse revokes the family) | PyJWT 2.15.1 |
| Authorization | 6 roles; per-route role guards; tenant only from the token; audited impersonation for platform admins | |
| Rate limiting | In-process sliding window per IP and per user (login, register, refresh, demo, guest) | |
| Security headers | CSP (`default-src 'self'`, no inline scripts) on the web apps, nosniff, no-referrer, frame-deny, HSTS in production, request IDs | |
| Images | **Pillow**: EXIF orientation fix, resize, server-time stamp, JPEG; SHA-256 verification | Pillow 12.3.0 |
| QR codes | **segno** (pure Python) SVG per room | 1.6.6 |
| Uploads | python-multipart | 0.0.32 |
| Domain features | Dispatch engine (ranking, timed offers, server-side expiry), rooms state machine, guest requests, inventory ledger (invariant: stock = sum of moves), requisitions, POs with partial GRN, stock counts, forecast-aware reorder, GST split (CGST/SGST vs IGST), GSTIN check, printable PO | |
| Config guard | `HOI_ENV=production` refuses unsafe settings (weak secret, demo login, wildcard CORS, no admin password) | |
| Ops endpoints | `/health`, `/ready`, OpenAPI docs (hidden in production) | |

### 5.5 Manager dashboard *(ours, `frontend/`)*

| Concern | Technology | Version |
|---|---|---|
| UI framework | **Streamlit**: `st.navigation` router, fragments for live refresh, dialogs, forms, data editor | 1.65.0 |
| Charts | **Plotly** (forecast bands, driver bars, trajectories, histograms) | 7.1.0 |
| Data | **pandas** | 3.0.6 |
| HTTP | **requests** (ML API, remote platform API); FastAPI TestClient (httpx) for the embedded platform API | 2.34.2 / httpx 0.28.1 |
| Config | python-dotenv; `USE_MOCKS`, `API_BASE_URL`, `PLATFORM_API_URL` (`embedded` or a URL) | 1.2.4 |
| Structure | `app.py` router · `login.py` · `console/` (platform) · `pages/` (15 hotel pages) · `employee/` (4) · `lib/` (api clients, models, auth, access, theme, charts, tour) | |
| Session | Tokens in session state; refresh token in a SameSite=Strict cookie so a browser refresh keeps you signed in; silent refresh on 401 | |
| Design system | Custom CSS on Streamlit: Inter Tight, off-white surfaces, pill nav, outline status cards, motion with `prefers-reduced-motion`, WCAG-checked colours | |

### 5.6 Staff app and guest page *(ours, served by the platform API)*

| Concern | Technology |
|---|---|
| Staff app | Vanilla JS **PWA**: web app manifest, service worker (offline shell), installable; bottom tab bar; polling every 2 s for pings; `navigator.vibrate` |
| Camera | **getUserMedia** rear camera → canvas → JPEG upload; no file picker (live camera only) |
| Language | Hindi / English string tables, remembered per phone |
| Session | Access token in memory; refresh token in localStorage ("keep me signed in") or sessionStorage; strict CSP limits XSS risk |
| Guest page | Vanilla JS; room token from the QR URL; bilingual request menu; status refresh every 15 s |
| Shared look | `shared/base.css` design tokens, system font stack (no third-party fonts, so CSP stays `self`) |

### 5.7 Marketing website *(ours, `website/`)*

Single static `index.html`: HTML/CSS/vanilla JS, Inter Tight from Google Fonts, IntersectionObserver reveal animations, responsive down to 390 px, same design language as the app (from the Train.png references). Two constants to set before publishing: app URL and contact email.

### 5.8 Quality, testing and DevOps

| Area | Tool | Version |
|---|---|---|
| Unit / API tests | **pytest** + FastAPI TestClient (28 tests) | 9.1.1 |
| Dashboard tests | **Streamlit AppTest** smoke test: 22 pages rendered as real signed-in roles + role-filter checks | |
| End-to-end | **Playwright** driving installed Chrome (phone viewport, fake camera) for the staff app, guest page, dashboard session restore | 1.63.0 |
| Lint / format | **ruff** (pycodestyle, pyflakes, isort, bugbear, pyupgrade) + `ruff format` | 0.17.0 |
| CI | GitHub Actions: install → lint → format check → API tests → dashboard smoke test | |
| Containers | Dockerfiles (python:3.12-slim, non-root, health checks) + docker-compose (platform + dashboard, data volume). **Not build-tested on this machine (no Docker).** | |
| Config | `.env.example` with production settings | |

### 5.9 Design and research tooling

Design references `Train.png` / `Train (1).png` (pill nav, outline status cards, gradient banners); colour contrast checked with the WCAG formula; competitor research from public vendor pages (`docs/COMPETITORS.md`), including eZee Absolute.

## 6. Why these choices, and the trade-offs

| Choice | Benefit | Cost / when to change |
|---|---|---|
| Streamlit for managers | Python-only, fast to build, charts built in | Weak on phones and fine-grained UI; a React front end is the upgrade path |
| Plain JS for staff/guests | Fast on cheap phones, no build, strict CSP | More hand-written code; fine at this size |
| SQLite | Zero setup, one file, instant reset for demos | One server only; move to Postgres (schema is plain SQL) |
| In-process rate limiter | No extra service | Needs Redis with more than one API instance |
| Embedded platform API | `streamlit run` alone works for demos | Staff app and QR pages need the API running as a service |
| Logistic regression over LightGBM for attrition | Better on our data, calibrated, explainable | Our synthetic hazard is logistic; re-check on real data |
| Custom JWT auth | Full control, no vendor | Production should add SSO/OIDC |

## 7. Verified vs not verified

**Verified on this machine:** all API tests; all dashboard pages as their roles; live ML backend click-through (loop, tasks, what-if, voice); staff app end-to-end in Chrome (ping → accept → before/after photo → done, Hindi, stays signed in after reload); guest QR request; dashboard session restore after refresh; production config guard (safe boots, unsafe refused).

**Not verified:** Docker images (no Docker here); behaviour on real phones and networks; any real-hotel data; multi-instance deployment; Hindi copy with native speakers.
