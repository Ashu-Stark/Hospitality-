# Hospitality Operations Intelligence (HOI) backend (FastAPI + MongoDB)

ALL data is SYNTHETIC (from `ml/`). See `backend/CLAUDE.md`, the root CLAUDE.md and
`docs/MONGODB.md`.

Data lives in MongoDB, database `hoi_ops` (override with `HOI_OPS_DB`), at `MONGODB_URI` (a secret:
root `.env` locally, the Render dashboard in production; never commit or print it). With no
`MONGODB_URI` (or `mongomock://`) the app uses an in-memory mongomock database: fine for local runs
and the tests, data lost on restart. The tests and `backend-smoke` always use mongomock (offline).

```powershell
cd backend
python run.py test        # backend tests (offline, mongomock)
python run.py seed        # rebuild hoi_ops at MONGODB_URI from the synthetic ml data
python run.py backend     # http://127.0.0.1:8000  (set MOCK=1 to serve ml/data/mocks/*.json)
```

## Interventions

`GET /interventions` lists the open and completed interventions written by `POST /loop/run`
(query: `status=open|done|all`, default `all`; optional `employee_id`, `week_start`). Each row
carries its linked task's status: `open`, `acked`, `done`, or `overdue` (not done and past its
deadline on the demo clock). "Open vs completed" is derived from the task, so acking or closing
the task via `/tasks/{id}/ack|done` is what moves an intervention. Employees are ids only.

## Roster solver: operating characteristics (B2)

- The solver never publishes a roster that breaks a hard rule. A week CP-SAT proves impossible
  comes back as status `infeasible` with every department / day / shift that cannot be staffed
  (and no roster). The greedy fallback runs only when CP-SAT times out without any solution, and
  its roster is published only if the independent hard-rule checker finds zero violations.
- 100-scenario stress test (random leave, occupancy and carried-in days on the real staff):
  91 solved with 0 hard violations (52 optimal, 39 feasible), 9 correctly reported infeasible
  with causes (8 x security, 1 x maintenance: a 3-shift or 2-shift day with too few staff left
  after leave and the 6-day rule). Median solve 7.0 s, p95 10.1 s.
- About 40 of 100 scenarios run to the 10 s time limit (42 in the first run, 38 in the rerun),
  returning the best roster found (status `feasible`). This is a known operating characteristic,
  not a bug:
  for the demo week use the cached rosters (`use_cache: true`; `python run.py roster-cache`
  rebuilds the baseline and the protected roster deterministically), as `POST /loop/run` does
  for both of its rosters, so its before / after numbers are identical on every run. The real demo week
  (2029-12-24) solves to `optimal` in 2.5-7.5 s depending on the machine.

## Deploying on Render

`render.yaml` (repo root) defines a Docker web service built from `backend/Dockerfile` with the
REPO ROOT as build context (the image needs `backend/` and `ml/`: `ml/data` and `ml/artifacts`).
The container runs `python -m backend.serve`, which binds `0.0.0.0:$PORT` (Render injects `PORT`;
default 8000). Health check: `GET /health`.

Environment variables the app reads:

| variable | default | purpose |
|---|---|---|
| `PORT` | 8000 | listening port (set by Render) |
| `HOST` | 0.0.0.0 | listening address (`backend.serve` only) |
| `MONGODB_URI` | unset (= mongomock) | MongoDB connection string; secret, `sync: false` in `render.yaml` |
| `HOI_OPS_DB` | `hoi_ops` | MongoDB database name |
| `MOCK` | 0 | `1` serves `ml/data/mocks/*.json` instead of the models |
| `CORS_ORIGINS` | `*` | comma-separated allowed origins; `*` (all) is relaxed for the hackathon demo |
| `GROQ_API_KEY` | unset | optional voice provider (Groq Whisper) |
| `SARVAM_API_KEY` | unset | optional voice provider (Sarvam) |

**Data persists across redeploys** in MongoDB Atlas (set `MONGODB_URI` in the Render dashboard).
On startup the app creates the indexes and seeds the employee snapshot from the synthetic ml data
only when it is empty, so a fresh database works without any manual step. `POST /demo/reset`
drops every `hoi_ops` collection (ids restart at 1) and reseeds. If `MONGODB_URI` is not set the
service falls back to in-memory mongomock and loses its data on every restart. MongoDB writes are
single-document (no transactions); task idempotency is backed by a unique index on
`task.idempotency_key`.

The free plan has 0.1 CPU and 512 MB RAM: a fresh `POST /roster/generate` without `use_cache` can
take the full 10 s solver limit or longer there; `/loop/run` uses the cached demo-week rosters.
