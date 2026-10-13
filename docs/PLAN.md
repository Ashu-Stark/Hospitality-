# HOI Frontend — Plan & Checklist

`[x]` done and verified · `[~]` done with a stated limitation · `[ ]` not done

## 0. Ground truth
- [~] CLAUDE.md / backend README / ml/data/mocks: not in this workspace. Real schemas were taken from the live backend's `/openapi.json`, and every mock was captured from the live API.
- [x] Hero ID → name mapping inferred from driver patterns (H901 Sunita … H905 Deepak); repo file overrides it automatically.

## 1. Foundation
- [x] Router `app.py` (st.navigation, numbered `pages/`), `home.py`
- [x] `requirements.txt`, `.env.example`, `.streamlit/config.toml` (Inter Tight theme)
- [x] `lib/api_client.py`: one function per endpoint, MOCK/LIVE switch, plain-language `ApiError`
- [x] `lib/mock_backend.py`: offline mutations with backend-identical idempotency keys, reminders at 50/90%, escalation
- [x] `lib/models.py`: dataclasses that match OpenAPI; schema warnings
- [x] `lib/theme.py`: design system following Train.png / Train (1).png; band colors defined once
- [x] `lib/data.py`: 30 s cache plus Refresh
- [x] `mocks/_fixtures.py --refresh` re-captures mocks from the live API

## 2. Pages
- [x] 1 Overview · [x] 2 Risk list · [x] 3 Employee · [x] 4 What-if · [x] 5 Roster · [x] 6 Closed loop
- [x] 7 Tasks · [~] 8 Voice (server-side clip name; no upload endpoint) · [x] 9 Admin

## 3. Extras beyond the brief
- [x] Editable ROI replacement-cost assumption (passed to `/metrics/overview?replacement_cost_inr=`)
- [x] Forecast interval honesty note (80% band covered ~68% in backtests)
- [x] Simulate-infeasible toggle (MOCK) to rehearse the honest-solver story
- [x] Baseline vs protected roster shift-by-shift diff
- [x] Live-refresh task board (fragment, 5 s) and clock speed presets
- [x] Schema check and mock provenance on Admin
- [x] Privacy: names only for 5 heroes; CSV exports IDs only
- [ ] Role switch (owner / manager / HR) — roadmap
- [ ] Multi-week intervention memory — needs backend support

## 3b. Round 2: dispatch, photo proof, SaaS, onboarding, motion, responsive
- [x] Auto-assign dispatch engine (`lib/dispatch.py`): on-shift + department filter, load / fairness / distance / retention-guard score, timed offers, decline/timeout → next, supervisor fallback
- [x] Live dispatch board (page 10) with pinging animation, countdown and explainable ranking; voice note → dispatch
- [x] Worker app (page 11): accept/decline, camera-only before/after photo, server timestamp, SHA-256, tamper check
- [x] Multi-tenant workspaces + onboarding wizard + plan tiers + invites (page 12); privacy-guarded staff import
- [x] Welcome dialog + 9-step guided tour
- [x] Motion: staggered rise-in, hero gradient drift, hover lift, ping pulse, countdown bar; honours prefers-reduced-motion
- [x] Responsive: scrollable pill nav, 2/1-column tiles, auto-collapsed sidebar on phones (checked at 390 px)
- [x] `docs/BACKEND_CONTRACT.md` for moving dispatch/photos/tenants server-side
- [x] TimesFM assessment (`docs/TIMESFM.md`)
- [~] Dispatch and photo data live in a local SQLite sidecar until the backend endpoints exist
- [ ] Auth / RBAC, billing, Telegram push

## 3c. Round 3: platform backend, roles, inventory, website
- [x] `backend/hoi_platform`: FastAPI + SQLite, JWT auth, role guards, tenant isolation, audited impersonation
- [x] Server-side dispatch engine (offer expiry enforced on read), photo proof upload/verify, inventory API, audit log
- [x] Frontend talks to it only over HTTP (`lib/platform.py`); embedded by default, remote via `PLATFORM_API_URL`
- [x] Sign-in / invite sign-up / one-click demo roles; platform console; role-filtered hotel pages; employee app
- [x] Inventory: requests → issue, PO → GRN (partial), counts, wastage, ledger invariant, forecast-aware reorder
- [x] Marketing website (`website/index.html`) in the Train.png design language
- [x] ruff lint + format across backend and frontend; repo restructured (backend/, frontend/, website/, docs/)
- [ ] SSO/OIDC, Postgres, object storage for photos, billing, Telegram push

## 3d. Round 4: production readiness, worker portal, eZee-inspired features
- [x] Separate staff app (`/worker/`, PWA): live pings with vibration, live-camera photos, supplies, shifts, Hindi/English, offline shell
- [x] Guest QR request page (`/guest/`) → auto-dispatched jobs, per-room rate limit, no personal data
- [x] Room status board: checkout → cleaning job → inspection → ready; out of order → maintenance job; supervisor queue
- [x] GST on purchasing: HSN + rate per item, GSTIN check, CGST/SGST vs IGST, printable PO
- [x] Rotating refresh tokens (reuse detection), dashboard stays signed in, silent token refresh
- [x] Rate limiting, security headers/CSP, request IDs, /ready, production config guard
- [x] Dockerfiles, docker-compose, .env.example, GitHub Actions CI
- [~] Docker files not build-tested (no Docker on the build machine)
- [x] UX review with measured contrast fixes (`docs/UX_REVIEW.md`)

## 4. Verification
- [x] `backend: python -m pytest`: 17 API tests pass
- [x] `python tests/smoke.py`: all 21 pages render as their roles through the API
- [x] `python tests/smoke.py --live`: all 10 pages render against Render
- [x] LIVE click-through: loop run (32 s, 12 tasks), ack, what-if (E134), voice demo clip, overview table
- [x] Visual check via headless Chrome screenshots
- [ ] Reset against LIVE (deliberately not run: it would wipe shared demo state)
