# MongoDB conventions (all services)

All three services store their data in one MongoDB Atlas cluster, **one database per service**:

| Service | Folder | Package | Database (env override) |
|---|---|---|---|
| ML / ops API (team) | `backend/` | `backend` | `hoi_ops` (`HOI_OPS_DB`) |
| HOI platform API | `platform_api/` | `hoi_platform` | `hoi_platform` (`HOI_PLATFORM_DB`) |
| Tourism portal | `portal/` | `hoi_portal` | `hoi_portal` (`HOI_PORTAL_DB`) |

## Connection

- `MONGODB_URI` (secret; root `.env`, gitignored; set in Render/Docker env). Never commit it or print it in logs.
- If `MONGODB_URI` is unset or equals `mongomock://`, the service uses an **in-memory `mongomock` client** (development and tests only; data is lost on restart). Each service logs one warning when that happens.
- Production (`HOI_ENV=production`) refuses to start on `mongomock://` or with no URI.
- One `MongoClient` per process (cached), created with `tz_aware=True, tzinfo=UTC`, `serverSelectionTimeoutMS=8000`, `appname=<service>`.
- Each service has its own small `mongo.py` (no shared package between services, so each deploys on its own).

## Data rules

- **IDs:** keep the existing public API contracts. Where an API exposes integer ids, keep integers via a `counters` collection (`find_one_and_update({"_id": name}, {"$inc": {"seq": 1}}, upsert=True, return_document=AFTER)`). Store the id in a field `id` with a unique index; never leak `_id` (ObjectId) in responses.
- **Timestamps:** timezone-aware UTC `datetime`. Dates (no time) as ISO `YYYY-MM-DD` strings.
- **Tenancy (platform API):** every business document has `tenant_id`; every query filters by it; compound indexes start with `tenant_id`.
- **Atomicity:** no multi-document transactions (mongomock does not support them and the free Atlas tier keeps them slow). Use single-document atomic updates: conditional `find_one_and_update` (e.g. stock `{"qty": {"$gte": n}}` + `$inc`), unique indexes for idempotency, and compensating writes when a second write fails.
- **Indexes:** created idempotently at startup (`ensure_indexes(db)`), including unique ones that enforce business rules.
- **Privacy:** same rules as before. Employees are ids only; no name, gender, age, religion, caste, health or family fields in any collection.
- **Audit:** state changes still write an `audit_log` document.

## Tests

- Tests run offline on `mongomock` with a fresh database per test (or per test module). No network in the default test run.
- `python scripts/check_mongo.py` (root) pings the real cluster and lists the three databases: the only check that needs Atlas.
