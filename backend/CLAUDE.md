# Hospitality Operations Intelligence (HOI) backend (FastAPI + MongoDB)

Project-wide rules are in the root CLAUDE.md (SYNTHETIC data everywhere, no personal or protected
attributes, never read `ml/data/internal/`). The ML side is documented in ml/CLAUDE.md. MongoDB
conventions (all services): docs/MONGODB.md.

## Rules for this folder

- Use ONLY the ml entry points `forecast.predict`, `attrition.score`, `attrition.rescore`,
  `voice.extract` (plus the result types and `attrition.heroes`), loaded from `ml/artifacts`.
  Never train, never read `ml/data/internal/`. The seed and the roster read ml/data OUTPUT tables
  (employee_v2, weekly_behaviour, weekly_signals, employee_skill, pay_changes, demo/), which are
  synthetic data, not models.
- Seeded randomness only (roster.seed in config.yaml). Every assumption is in config.yaml and
  marked ASSUMED.
- Every document has an integer `id` (from `counters`), `created_at` and `source`. Everything that
  changes state writes `audit_log`. `_id` never leaves db.py / the API.
- MongoDB: database `hoi_ops` (`HOI_OPS_DB`) at `MONGODB_URI` (secret: never print, log or
  commit it). Unset or `mongomock://` = in-memory mongomock (dev / tests; tests force it in
  tests/conftest.py and never touch Atlas). No multi-document transactions: single-document
  writes, unique indexes (task.idempotency_key, task_event (task_id, kind)), created by
  `ensure_indexes` at startup. Dates are ISO strings, times tz-aware UTC (millisecond precision).
- Dependencies (installed for the backend batch; versions in requirements-lock.txt): fastapi
  0.143.0, uvicorn 0.54.0, pymongo 4.18.3 (+ dnspython 2.9.0), apscheduler 3.11.3, ortools
  9.15.6755, httpx 0.28.1; mongomock 4.3.0 (dev / test only).

## Layout and commands

```
backend/            the `backend` package (repo root on PYTHONPATH, like ml/)
  config.yaml/.py   settings, roster / task / metrics / voice config (ASSUMED values)
  mongo.py          cached MongoClient (MONGODB_URI) or mongomock; database_kind for /health
  db.py             collections, counters ids, ensure_indexes, audit, seed from the ml data
  schemas.py        request models; responses ARE the ml result types
  services.py       the bridge to ml/ (ModelService) and MOCK=1 (MockService, ml/data/mocks)
  main.py           app factory create_app() + core routes
  roster/           problem.py, solver.py (CP-SAT + greedy + cache), check.py, service.py, stress.py
  tasks/            engine.py (virtual clock, idempotency, reminders), api.py
  loop.py           POST /loop/run (closed loop)
  demo.py           metrics, demo reset, voice ingest
  smoke.py          python run.py backend-smoke
  tests/            pytest (slow marker: the 100-scenario roster test)
```

```powershell
cd backend
python run.py test            # fast tests;  python run.py test --all  includes the 100 scenarios
python run.py lint
python run.py seed            # drop + rebuild hoi_ops at MONGODB_URI (mongomock if unset)
python run.py roster-cache    # solve the demo week and save roster/cache/roster_2029-12-24.json
python run.py roster-stress   # 100 random scenarios: hard violations + solve times
python run.py backend         # http://127.0.0.1:8000  (MOCK=1 serves ml/data/mocks/*.json)
python run.py backend-smoke   # fresh process, mongomock: health, forecast, score, roster, loop, task
```

## Endpoints

| method | path | what |
|---|---|---|
| GET | /health | status, MOCK flag, database (mongodb / mongomock), model name / version / dataset hash per artifact |
| GET | /forecast?from=&to=&as_of= | forecast.predict (ForecastResult) |
| POST | /attrition/score | attrition.score (list[AttritionScore]) |
| POST | /attrition/rescore | attrition.rescore (RescoreResult, a SIMULATION) |
| POST | /roster/generate | CP-SAT roster for the snapshot week (protected_ids, use_cache); status infeasible + causes when impossible |
| GET | /roster/{id} | a stored roster |
| POST | /tasks | create (idempotency_key: a retry returns the same task; another task -> 409) |
| POST | /tasks/{id}/ack, /tasks/{id}/done | idempotent transitions |
| GET | /tasks | list with events |
| POST/GET | /demo/clock | demo clock multiplier (reminders fire in seconds) |
| POST | /loop/run | closed loop: score, interventions, baseline vs protected roster, rescore |
| GET | /interventions?status=open\|done\|all&employee_id=&week_start= | stored interventions with their linked task status (open / acked / done / overdue = not done past its deadline); open = not done |
| GET | /metrics/overview | overtime, understaffing, task on-time rate, flagged count, ROI (ASSUMPTION) |
| POST | /demo/reset | drop the hoi_ops collections, recreate indexes, reseed, clock x1 |
| POST | /voice/ingest | voice.extract on a clip in ml/voice/clips -> structured task |

## B2 roster

- Shifts (ASSUMED): morning 06:00, evening 14:00, night 22:00, 9 h each. 9 h because with 8 h
  shifts and a weekly off nobody can exceed 48 h, so overtime could never appear.
- Demand: ml workload standards (base / 7 + per-room-night hours x 45 rooms x FORECAST occupancy
  per day), split per shift by demand_share.
- HARD: approved leave (weekly leave days from the synthetic leave table, placed as a seeded
  consecutive block: the table has no dates), one shift a day, 10 h minimum rest (ASSUMED, HM
  student to confirm), >= 1 day off, <= 6 consecutive days incl. the run carried in from the
  previous week (ASSUMED), >= 1 person per department-shift, a fo_system holder on every
  front-office shift. SOFT (config weights): understaffed hours, overtime above 48 h, weekend and
  night spread per department, protected-weekend bonus (full Sat + Sun off, matching ml signals).
- Demo heroes join their department as extra staff (labelled) so the closed loop can roster them.
- Never publishes a rule-breaking roster: a week CP-SAT proves impossible returns status
  `infeasible` with every department / day / shift that cannot be staffed (relaxed re-solve) and
  no roster; greedy runs only when CP-SAT times out with no solution, and its roster is published
  only if the independent checker finds zero hard violations (greedy alone breaks rules on the
  demo week, so in practice it never publishes there).
- Real demo week: CP-SAT optimal (objective 2242) in 2.5-7.5 s, 0 hard violations.
- Stress (100 random scenarios): 91 solved with 0 hard violations (52 optimal, 39 feasible), 9
  infeasible with causes (8 security, 1 maintenance); median 7.0 s, p95 10.1 s; ~40% hit the
  10 s limit, so the demo uses the cached demo-week roster (see README).

## B4 closed loop: what it shows (demo week 2029-12-24, B4b final, reproducible)

Flagged = high-band permanent staff from attrition.score (6: E134, E177, E186, E196, E198 and
demo hero H901 Sunita). Each gets the top-2 playbook actions as tasks. Before / after = the
person's rescored risk under the baseline roster vs the protected roster (features each roster
implies; a SIMULATION).

Determinism (B4b): both demo-week rosters are solved with CP-SAT's deterministic interleaved
search (8 workers, fixed seed, work-unit limit; config roster.deterministic) and cached
(`python run.py roster-cache`), so /loop/run gives identical numbers on every run (verified twice;
a fresh deterministic re-solve gives the same rosters). The earlier B4 numbers came from one of
several equally good optimal rosters picked by the non-deterministic parallel search and are
superseded. 1 worker was tried: deterministic too, but stuck at objective 2744 / 2702 after 5-8
min vs the optimum 2242 / 2204 (bonus 40) proven in ~5 s.

Weekend bonus (B4b): protected_weekend_bonus = 120, chosen from 40 / 100 / 120 (above the ~90
understaffing cost of one 9 h shift). Flagged people protected: 2 / 4 / 5 of 6; mean risk change
-0.0004 / -0.0026 / -0.0037; coverage 99.04% / 98.61% / 97.99%.

| person | baseline: overtime, weekend off, risk | protected (bonus 120) | risk change |
|---|---|---|---|
| E134 | 6 h, no, 0.0965 high | 0 h, yes, 0.0891 high | -0.0074 |
| E177 | 0 h, no, 0.0910 high | 0 h, yes, 0.0890 high | -0.0020 |
| E186 | 6 h, no, 0.1734 high | 0 h, yes, 0.1611 high | -0.0123 |
| E196 | 0 h, no, 0.0961 high | 6 h, no, 0.1029 high | +0.0068 |
| E198 | 6 h, no, 0.0727 watch | 0 h, yes, 0.0675 watch | -0.0052 |
| H901 Sunita | 0 h, no, 0.0661 watch | 0 h, yes, 0.0639 watch | -0.0022 |

Every person stays in the same band. 5 of 6 flagged get a full weekend off (E196 does not and
picks up 6 h of overtime). Totals, baseline -> protected: coverage 99.36% -> 97.99%, understaffed
shifts 42 / 122.4 h -> 47 / 155.4 h, overtime 180 h -> 168 h, wage cost INR 301,897 -> 295,092;
0 hard violations in both.

Honest notes:
- Sunita's risk does not meaningfully drop under one protected week (-0.002): her risk is driven
  by a 10-week sustained-overtime average, so one week barely moves it. A visible drop for her
  would need several consecutive protected weeks, not a higher bonus weight.
- Wage cost FALLS only because understaffing is not priced in money: the protected roster trades
  coverage (47 vs 42 understaffed shifts) for protection. A real coverage / cost tradeoff, not a
  free improvement.
