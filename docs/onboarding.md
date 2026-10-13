# Hotel onboarding by voice

An owner sets up one hotel by answering a few guided questions in Hindi, English or Hinglish, by
voice or by typing. Hospitality Operations Intelligence extracts the hotel details from the answers,
fills everything else from a size-based template, shows a draft, and saves **only after the owner
presses Confirm**. Voice is optional: with no audio and no API keys, typed answers plus the
rule-based extractor do the whole job.

Code: `backend/onboarding/` (FastAPI routes on the existing ML / ops API, MongoDB `hoi_ops`).
Screen: dashboard page **Hotel setup (voice)** (`dashboard/pages/15_Hotel_Setup.py`). This is not
the dashboard **Setup** page, which creates the platform workspace (organisation, staff import,
team invites).

## Honesty notes (read first)

- **Hindi and Hinglish accuracy on real audio is untested.** No onboarding recordings exist yet;
  every score below comes from sentences we wrote ourselves.
- **Numbers are the most error-prone part** (spoken Hindi numbers have many spellings, speech-to-text
  mishears them). That is why every number an LLM returns is cross-checked against a deterministic
  number reader, and mismatches are shown as "please confirm".
- **Legal values need verification.** Minimum rest hours, overtime rate multiplier and weekly
  off days depend on labour rules. They always carry `needs_verification=true`, are never confirmed
  from voice, and Confirm is refused until each one is explicitly acknowledged ("verified with a
  qualified person").
- **Synthetic data only.** Demo hotels, the cached Hindi demo, tests and the eval set are SYNTHETIC.
- **Free AI tiers give no privacy guarantee.** Owner text goes to the LLM, and owner audio goes to
  cloud speech-to-text, only when a config flag allows it (default off) AND the owner ticks the
  consent box. Never send real staff names, salaries or staff data.

## Flow

```
owner                       backend/onboarding                                  MongoDB (hoi_ops)
-----                       ------------------                                  -----------------
Start (type?, language) --> template for the type (or default) -> draft  -----> onboarding_session
                            reserve property_id, open question 1                (draft only)
   <-- question (en / hi, with an example)
answer: text, or audio -->  [audio] type/size check -> flag + consent? -> STT  (temp file, deleted)
                                    no -> "type instead" + same question
                            number normaliser (Hindi/English words -> digits)
                            rule-based extractor (always)  + LLM (only flag + consent + key)
                            LLM numbers cross-checked -> mismatch = conf 0.3 "please confirm"
                            merge: answers beat template; owner edits always win
                            rooms / type answered -> re-template departments by size band
                            next question = first unanswered field (max 8 questions)
   <-- draft + confidence + warnings + next question | "ready_for_summary"
edit a field (PATCH) -----> owner edit, confidence 1.0, always wins
summary --------------->    every field: value, source, confidence, needs_verification, note
Confirm + legal acks --->   blocked unless: required filled, no errors, nothing "please
                            confirm", every legal field acknowledged
                            insert property (unique property_id)  ----------->  property
                            insert settings (unique property_id)  ----------->  property_settings
                            audit rows  --------------------------------------->  audit_log
                            a double submit hits the unique index -> same property, created=false
```

Questions are asked in this fixed order: rooms, location, departments with headcounts, peak
months, shifts, overtime rate multiplier, minimum rest hours. A field already filled by an answer is
never asked again ("12 rooms in Mussoorie" answers rooms and location). A field with no usable
answer is asked at most twice; the total is capped at 8 questions, so the flow always ends.
"skip" (or "aage", "पता नहीं", ...) keeps the template value. Every other field (standard weekly
hours, weekly off, max consecutive days, department heads, ...) comes from the template and is
shown at Confirm instead of being asked.

## Endpoints (ML / ops API)

| method | path | what |
|---|---|---|
| POST | /onboarding/start | `{hotel_type?, language: en\|hi, hotel_name?}` -> session id, property id, first question, draft |
| POST | /onboarding/answer | JSON `{session_id, text, consent}` or multipart form `session_id`, `text` or `file` (audio), `consent` -> draft, per-field confidence, warnings, next question or `ready_for_summary`; `stt_error` + `input_fallback: "text"` when audio cannot be used |
| PATCH | /onboarding/field | `{session_id, field, value}`: owner edit (always wins) |
| GET | /onboarding/summary?session= | full draft with source / confidence / needs_verification, errors, warnings, missing, needs_confirmation |
| POST | /onboarding/confirm | `{session, acknowledged_legal_fields: [...]}` -> `{property_id, created}`; 422 with what is missing; idempotent |
| GET | /onboarding/demo-transcript | the cached SYNTHETIC Hindi / Hinglish demo answers |
| GET | /properties/{property_id} | one property (query filtered by property_id) |
| GET | /properties/{property_id}/settings | that property's confirmed profile |

Storage: collections `onboarding_session`, `property`, `property_settings` in `hoi_ops` (indexes
in `backend/db.py ensure_indexes`, dropped by `/demo/reset`). Every document has an integer `id`,
`created_at`, `source` and `property_id` (a string, `prop_0001`, reserved when the session
starts). No login exists (out of scope): isolation means every property / settings query filters
by property_id; anyone who knows a property id can read it.

## Commands (from `backend/`)

```powershell
python run.py onboarding-demo            # cached Hindi demo, question by question (mongomock, no keys)
python run.py onboarding-demo --llm      # same, letting the LLM read the answers (GROQ_API_KEY)
python run.py eval-onboarding            # rules + LLM (if GROQ_API_KEY) on the SYNTHETIC eval set
python run.py eval-onboarding --no-llm   # rules only, offline
python run.py test                       # includes tests/test_onboarding_*.py (no network)
```

`eval-onboarding` and `onboarding-demo --llm` read only `GROQ_API_KEY` from the environment or the
root `.env` (no other line of `.env` is read; MongoDB stays mongomock).

## Evaluation (28 synthetic utterances, 34 expected fields)

OPTIMISTIC: the utterances were written by us together with the word lists; no recorded speech,
no speech-to-text errors. Results in `backend/onboarding/eval/results.json`.

| extractor | field accuracy | notes |
|---|---|---|
| rule-based | 33/34 = 97.1% | miss: "two dozen rooms" read as 12 |
| LLM (`openai/gpt-oss-20b`, Groq, temperature 0) | 28/34 = 82.3% | misses: location kept "near" / mixed script, a headcount (2 -> 1), a month dropped, shift names capitalised, "two dozen" |

Cross-check: 1 LLM number flagged "please confirm", and it was a real LLM error (0 false alarms).
Audio: not run (no recorded onboarding clips in `ml/voice/clips`), so no word error rate.

## Config files (every value ASSUMED; HM student to review)

| file | what |
|---|---|
| `backend/onboarding/onboarding.yaml` | size bands (homestay 5-15, small hotel 16-50, resort 51+), allowed ranges, staff-to-room ratio 0.3-2.5 (warning only), 8 questions max, 2 asks per field, confidences (template 0.5, rules 0.8 / 0.7 / 0.6, LLM 0.9 / 0.75, mismatch 0.3, accept 0.6), extractor settings, LLM (Groq URL, model, timeout, retries, `allow_cloud_llm_for_owner_text: false`), audio (`allow_cloud_stt_for_owner_audio: false`, `store_audio: false`, 10 MB, types), the 3 demo hotels, geocoding (LocationIQ Search for the location answer: `LOCATIONIQ_API_KEY` from the environment, countrycodes=in, limit 1, 5 s timeout, 7-day in-process cache; stored as `location.geo` and shown as "Found: ..."; no key or a failure is skipped silently and never blocks Confirm) |
| `backend/onboarding/templates.yaml` | per hotel type: departments, base-hours scale, minimum headcount, shifts, roles combined (homestay); work standards are references (`ml:workload`, `ml:staff.standard_weekly_hours`, `backend:roster.min_rest_hours`, `backend:roster.overtime_premium`, ...), never copies; peak months = ml monthly occupancy >= 0.65 |
| `backend/onboarding/questions.yaml` | the 7 questions + messages in English and Hindi (Devanagari) with examples; DRAFT wording |
| `backend/onboarding/numbers.yaml` | number words 0-100 (English, romanised Hindi with spelling variants, Devanagari), scale words, fractions (dedh, dhai), multipliers (double, dugna) |
| `backend/onboarding/lexicon.yaml` | department synonyms (keys = `ml/voice/glossary.yaml` department ids), months, hotel type words, places, shift words, unit words |
| `backend/onboarding/fixtures/demo_transcript.yaml` | the cached Hindi / Hinglish demo conversation + expected profile |
| `backend/onboarding/eval/utterances.yaml` | the eval set |

## How to add a hotel type

1. Add it to `HOTEL_TYPES` / `HotelType` in `backend/onboarding/schema.py`.
2. Add its size band in `onboarding.yaml size_bands` (the bands must cover every type).
3. Add its template in `templates.yaml hotel_types` (departments must be glossary department ids,
   shifts must be names in `backend/config.yaml roster.shifts`).
4. Add its words in `lexicon.yaml hotel_types`.
5. Run `python run.py test` (the config loaders refuse a type that is missing anywhere).

## Fallbacks

| situation | what happens |
|---|---|
| no API key / LLM not allowed / no consent | rule-based extractor (`fallback_reason` says why) |
| LLM call fails or rate-limited after retries | rule-based extractor |
| LLM reply not JSON or not valid for the schema | rejected; rule-based extractor |
| LLM number not heard by the number reader | value kept at confidence 0.3, "please confirm", Confirm blocked until the owner edits it |
| audio flag off, no consent, no STT provider, STT error | clear message, same question, type the answer instead |
| audio too large / wrong type | HTTP 422 |
| no microphone, no keys at the demo | "Cached Hindi demo" tab on the page, or `python run.py onboarding-demo` |
| dashboard in MOCK mode | the backend onboarding engine runs in-process on mongomock (needs the repo checkout; otherwise 501) |
