# Hospitality Operations Intelligence (HOI)

Hackathon project: an AI platform for small hill hotels in Uttarakhand that
**predicts employee attrition**, **forecasts occupancy** and **generates duty rosters**.

## Data is synthetic

ALL data in this project is SYNTHETIC, produced by `ml/generator`. Every dataset,
chart, table, model card, demo screen and doc must be labelled as synthetic.
Config values in `ml/generator/config.yaml` are ASSUMED plausible values, not measured facts.

## Rules

- Python 3.13 on Windows (PowerShell). No Makefile, no Linux-only commands; use `run.py`.
- Every random draw uses a seeded `numpy.random.Generator` passed in as an argument.
  No global random state (`np.random.seed`, `random.*`, unseeded `default_rng()`).
- Split train/test BY TIME, never randomly.
- Never use religion, caste, health or family status as features (or generate them as model inputs).
- Every module gets pytest tests in `/tests`.
- Small, typed functions.
- Do not add dependencies without telling the user first (update `requirements.txt`).

## Repo layout

The repo root holds three projects: `ml/` (this one), `frontend/` and `backend/` (not started).
`ml/` is both the project folder and the Python package `ml`: imports are `from ml.generator ...`
with the REPO ROOT on the import path. In this file, paths starting `ml/` are from the repo
root; bare `data/`, `docs/`, `tests/`, `artifacts/` paths are inside `ml/`.

```
ml/                    (repo root/ml)
  tests/               pytest tests
  docs/
    plots/             validation + model plots
    metrics/           model metrics JSON
  data/                generated SYNTHETIC data (data/*.db, data/internal/, data/features.csv
                       are gitignored)
    mocks/             frontend mock JSON from real model outputs (python run.py mocks)
  generator/           synthetic data generator
                         config.yaml / config.py   ASSUMED parameters + Pydantic validation
                         festivals.yaml            festival / holiday dates (VERIFY before claims)
                         calendar.py               daily event calendar
                         weather.py                temp, rain, heavy rain, road closures
                         occupancy.py              occupancy, ADR, revenue, booking pace
                         run_occupancy.py          writes the daily CSVs
                         validate_occupancy.py     PASS/FAIL checks + plots
                         rng.py                    named seeded streams
                         staff.py                  initial staff + generate_employee
                         skills.py                 employee skills with coverage guarantee
                         workload.py               weekly required vs available hours
                         run_staff.py              writes staff / skill / workload CSVs
                         validate_staff.py         PASS/FAIL checks + load_ratio plot
                         behaviour.py              per employee-week overtime, pulse, leave, hazard
                         attrition.py              weekly simulation: exits, renewals, hires
                         run_attrition.py          writes behaviour / exits / employee_v2 CSVs
                         validate_attrition.py     PASS/FAIL checks + pulse / attrition plots
  features/            build_features.py (feature matrix + label), split.py (time split)
  models/              pulse + workload models (common.py, *_pulse*, *_workload*)
  forecast/            occupancy forecast (core.py, train.py)
  attrition/           attrition model (features.py, models.py, train.py)
  voice/               voice notes: glossary, clip manifest, providers, extraction, eval
  eval/                package.py (artifact packaging), check_artifacts.py (load check)
  artifacts/           trained models (attrition/v1, occupancy_forecast/v1, pulse, workload)
  run.py               task runner
  pyproject.toml       pytest + ruff settings (pythonpath / src point at the repo root)
  requirements.txt, requirements-lock.txt
```

## Setup and commands

Run everything from inside `ml/`:

```powershell
cd ml
py -3.13 -m venv ..\.venv            # or .venv here; run.py finds either
..\.venv\Scripts\Activate.ps1
pip install -r requirements-lock.txt   # exact versions; requirements.txt is unpinned

python run.py test      # fast tests (skips tests marked slow)
python run.py test --all  # every test
python run.py lint      # ruff check .
python run.py generate  # write SYNTHETIC CSVs to data/ (occupancy, staff, then attrition)
python run.py validate  # occupancy + staff + attrition PASS/FAIL checks, plots (exit 1 on FAIL)
python run.py validate-seeds [seed ...]  # pooled multi-seed difficulty checks (default 42 43 44)
python run.py train     # attrition: backtest, calibration, drivers (artifacts/attrition/v1)
python run.py train-forecast  # occupancy forecast (artifacts/occupancy_forecast/v1)
python run.py train-pulse  # pulse features -> split -> naive + XGBoost (GPU) -> compare (exit 1 if not better)
python run.py train-workload  # dept load features -> split -> naive + XGBoost (GPU) -> compare (exit 1 if not better)
python run.py eval      # retrain every model, rewrite metrics + plots, package, check
python run.py check-artifacts  # load every artifact + run the interfaces, no retraining
python run.py eval-voice  # voice: WER + extraction accuracy per provider, demo cache
```

`run.py` uses `ml\.venv` or the repo-root `.venv` when present, so activation is optional,
and it runs every command with `ml/` as working directory and the repo root on PYTHONPATH.
To run a single module by hand, do it from the REPO ROOT: `python -m ml.generator.<module>`.
Never `python generator/<file>.py`: `generator/calendar.py` would shadow the stdlib `calendar`.

## Data files (all SYNTHETIC, seed from config.yaml, one row per day property.start..end)

Horizon: 2023-01-01..2029-12-31 since Task 5b (was 2025-12-31). festivals.yaml dates for
2026-2029 are UNVERIFIED approximations added for the extension.

All files join on `date` (YYYY-MM-DD). `day_of_week` uses Mon=0.

- `data/event_calendar.csv`: date, day_of_week, month, is_weekend (Fri/Sat), is_public_holiday,
  festival_name ("" if none, "; "-joined if several), is_festival, is_festival_window
  (3 days before to 1 day after a festival day), is_char_dham, is_school_holiday
- `data/weather_daily.csv`: date, temp_c, rain_day, heavy_rain (subset of rain days),
  road_closure_flag
- `data/occupancy_daily.csv`: date, occupancy_pct (fraction 0..1 = rooms_sold / rooms),
  rooms_sold, adr (INR), room_revenue (INR), booking_pace_7d (rooms on the books 7 days before
  the stay date)

- `data/employee.csv`: employee_id (E001..), department, role, is_department_head, manager_id
  (dept head's id, empty for heads), hire_date, contract_type (permanent|seasonal),
  contract_end_date (empty if permanent), monthly_pay (INR), last_raise_date.
  Ids only: never add names, gender, age, religion, caste, health or family status.
- `data/employee_skill.csv`: employee_id, skill, level (1-3)
- `data/dept_week_load.csv`: week_start (Monday, complete weeks only: 2023-01-02..2025-12-22),
  department, occupied_room_nights, required_hours, headcount (static until Task 4),
  available_hours (= headcount * staff.standard_weekly_hours), load_ratio
- `data/internal/employee_latent.csv`: employee_id, overtime_propensity, baseline_pulse,
  baseline_task_score, latent_frustration. GENERATOR-ONLY hidden traits: never join into
  model features or show in the product.

Task 4 (attrition) outputs:

- `data/employee_v2.csv`: SAME columns as employee.csv. First 55 rows are byte-identical to
  employee.csv; then every replacement hire (ids continue E056.., never reused). hire_date can
  fall after the last simulated week (replacement scheduled, not yet started). manager_id is the
  department head at hire time. contract_end_date is the end AT HIRE; renewals are separate.
  **Downstream tasks and every ML model must read employee_v2.csv, not employee.csv.**
- `data/weekly_behaviour.csv`: employee_id, week_start, department, role, load_ratio (dynamic),
  overtime_hours, pulse_score (1-5), leave_days, is_active. One row per employee per week they are
  employed at least one day; is_active is False only in the week containing exit_date (the last
  row). No rows after exit.
- `data/pay_changes.csv` (T4): employee_id, effective_date, monthly_pay (new pay from that
  week). Pay in force at a date = hire pay + the latest change on or before it.
- `data/attrition_calibration.json` (T4): calibrated hazard intercept, achieved and target
  annual attrition, simulations run, search mode, config fingerprint.
- `data/weekly_signals.csv` (T5): employee_id, week_start, task_score, weekly_off_skipped,
  weekend_off, weeks_since_weekend_off, consecutive_days_worked, leave_before_festival. One row per
  weekly_behaviour row, from its own random stream (earlier outputs unchanged). Not fed into the
  exit hazard. The T4 leave process does not cluster leave before festivals (known limitation).
- `data/leave_records.csv`, `data/pulse_responses.csv` (T5): leave weeks and weekly pulse,
  derived from weekly_behaviour rows (so no rows after an exit).
- `data/demo/` (T5): five scripted fictional DEMO heroes (H901-H905: hero_employees.csv,
  hero_weekly.csv) from generator/heroes.yaml; display names only in hero_display_names.json.
  Never in training or test data.
- `data/exits.csv`: employee_id, exit_date, exit_reason (resignation | seasonal_end),
  tenure_days_at_exit, replacement_employee_id (every exit schedules one).
  Task 4c fix: a replacement keeps the leaver's contract type (seasonal -> seasonal with a fresh
  contract_end_date from seasonal_contract_end_options, permanent -> permanent; heads unchanged).
  Before, generate_employee re-drew the type from seasonal_share_by_role, so a seasonal leaver was
  replaced by a seasonal hire only 25-30% of the time and seasonal staff drained away (8.9% of
  staff-weeks in 2023 -> 0.1% in 2028). Now flat at ~12.7% (~7 people) every year.
- `data/contract_renewals.csv`: employee_id, renewal_date (old contract end),
  new_contract_end_date. Use it for point-in-time contract features.
- `data/dept_week_load_dynamic.csv`: same columns as dept_week_load.csv, but headcount and
  available_hours follow exits and hires (available = days employed / 7 * weekly hours). Changes
  take effect from the following week. Task 3's static dept_week_load.csv is unchanged.
- `data/internal/employee_latent.csv`: Task 3 rows unchanged, plus one FRESH row per
  replacement hire (rewritten idempotently each run).

Leakage notes for attrition models: exits.csv and is_active are LABELS. pulse_score and
load_ratio drive the hazard, so they are legitimate features only when taken from weeks before
the prediction date. Never use latent traits.

`data/internal/` is gitignored (recreated by `python run.py generate`) and must NEVER be read by
model training, evaluation, app, bot or dashboard code. Only `ml/generator` may use it.

Random streams: every stage takes its Generator from `ml/generator/rng.py` `stream_rngs` by
name. Append new stream names at the END of `STREAMS` so existing outputs do not change.

PLACEHOLDERS: the `roles`, `skills`, `staff` and `workload` config blocks are ASSUMED and must
be replaced with values from the HM (hotel management) student before any claim is made.
The `attrition` block is ASSUMED, pending HM student confirmation. base_weekly_exit_hazard =
0.009 was chosen to land near 30% annualised attrition (validated: 30.4%). The 4 exit-hazard
unit tests in tests/test_behaviour.py use a fixed local AttritionConfig (base 0.004), not
config.yaml, so future calibration will not break them.
The `workload` values are CALIBRATED PLACEHOLDERS, not real standards: fitted so median
load_ratio is ~0.90, May-Jun > 1.10 and Feb < 0.75. Per-room hours are inflated because they
absorb all occupancy-driven demand. Replace with HM student values and re-validate.

Leakage notes: booking_pace_7d is derived from the realised rooms_sold, so it is a valid
feature only for forecast horizons of 7 days or less. No lag features are generated; build them
downstream, using past data only.

## T4: attrition signal (hazard, raises, 90-day label, calibration)

The resignation hazard is now logistic: sigmoid(intercept + observable driver terms + hidden
latent_frustration + weekly noise), capped at attrition.hazard.max_weekly_hazard. Observable
drivers (behaviour.py DRIVERS): sustained overtime, weeks without leave, low pulse, falling
pulse, pay gap, months since raise, load, peer exits, first year. All coefficients are ASSUMED
values in config.yaml (attrition.hazard). Seasonal contract ends stay a separate exit route.
A raise process (attrition.raises) writes data/pay_changes.csv so pay ratio and months since
raise evolve.

target_annual_attrition IS read: calibrate.py finds the intercept by fixed-seed bisection (plus
a local grid scan) and saves it in data/attrition_calibration.json with a config fingerprint.
Same fingerprint -> the saved intercept is reused in one simulation (fast and reproducible).
label_horizon_days IS read: the attrition label is "exit within 90 days"; rows whose window
passes the data end are marked is_censored and excluded from every split.

Sustained overtime (T4b): the overtime driver uses the average over attrition.hazard.
overtime_window_weeks (10) weeks, matched by the overtime_window_mean feature; a 4-week driver
made exits happen inside the overtime spell, so the overtime signal could not precede them.

T4 checks. python run.py validate (seed 42) adds 6: attrition within 5 points of the target;
three PERMANENT-staff difficulty probes on an expanding window (train on all rows whose 90-day
label window ends before 1 January of each test year 2025-2029): overtime-only rule ROC-AUC
0.60-0.72, best of (regularised LightGBM, standardised logistic) >= 0.68, best model beats the
rule by >= 0.04 (pass/fail = ROC-AUC of within-year percentile ranks pooled; the mean of
per-year AUCs is shown beside it); high-driver employees who did not leave >= 15%; the 90-day
label with censoring. The single-seed no-visible-driver share is shown as INFO.
python run.py validate-seeds pools seeds 42-44 and gates the same difficulty probes plus the
no-visible-driver share (5%-20%). Final config A5: overtime 0.5 per hour over a 10-week window,
pay gap 9.0, stalled 0.15 per month, no-leave 0.25 per week, low pulse 1.2, pulse drop 1.2,
noise 0.6, latent frustration 1.0, visibility threshold 0.6, intercept calibrated to 0.40.

How to read the T4 difficulty numbers (applies to every probe and band below):
- (a) The difficulty bands (overtime-only rule 0.60-0.72, best model >= 0.68, gap >= +0.04) and
  the 5%-20% no-visible-driver band are GENERATOR-DIFFICULTY TARGETS chosen by this project,
  not real-world benchmarks.
- (b) Single-seed shares and single-year probes are noisy: one test year holds only ~7-15
  permanent leavers and one seed ~50, so single-year AUCs swing by about +/-0.07 and the
  single-seed no-driver share ranged 2.7%-11.8% across seeds 42-53. That is why the gates use
  pooled numbers (validate-seeds pools 3 seeds; the no-driver share is INFO in validate).
- (c) Logistic regression beat LightGBM in the probes because the planted hazard is itself a
  logistic function of the drivers. This is a property of the synthetic data, NOT evidence
  that logistic regression is a better model in general.
- (d) The old probes had a label leak: training rows near the end of the training period had
  90-day label windows reaching into the test year. A 90-day training gap fixed it. An earlier
  pooled-score evaluation also penalised the models (each year's model scores on its own
  scale); it was replaced by pooling within-year percentile ranks.
- (e) The A5 coefficients were chosen on seeds 42-44 from 6 candidate configs and then
  confirmed, without further tuning, on fresh seeds 48-50 and 51-53.
- (f) The drivers are PLANTED, so every probe result demonstrates the mechanism working; none
  of it is evidence of real-world predictive accuracy.


**MODEL ARTIFACTS (T7):** the old Task 5 attrition artifacts were deleted; attrition now lives
in artifacts/attrition/v1/. Pulse and workload were retrained on the current data in T7 (test
MAE pulse 0.2498 vs naive 0.2567; workload 0.0530 vs naive 0.0729). The occupancy forecast (T6)
is unaffected.

Known limitation: tenure in role equals tenure because no promotions exist; known limitation
for the stalled-progression driver.

## T7: attrition model (ml/attrition, SYNTHETIC data)

Replaces the retired Task 5 pipeline (train_baseline / train_tree / evaluate and their
artifacts were deleted in T7). Files: `ml/attrition/features.py` (T4 feature matrix + T5 signal
features + segment labels), `ml/attrition/models.py` (rules, logistic, LightGBM, Platt
calibration, F1 threshold, metrics), `ml/attrition/train.py`. `python run.py train`.
Outputs: `artifacts/attrition/v1/{model.joblib,metrics.json,feature_list.json}`,
`docs/plots/attrition_calibration.png`. Reads only output tables, never data/internal/ or
data/demo/ (heroes stay out of training).

- Two evaluations: resignation (permanent staff, label = resignation within 90 days) and
  contract_end (seasonal staff, label = seasonal contract-end exit within 90 days). Seasonal
  resignations (12, all before 2028) are in neither evaluation.
- Expanding-window backtest, test years attrition_model.test_years (2027-2029): train on rows
  whose label window ends <= 1 Jan of Y-1, Platt-calibrate + F1 threshold + winner choice on
  Y-1, test on Y; test predictions pooled. Platt, not isotonic: a validation year holds only
  ~5-15 leavers. The deployed model repeats this with 2029 as validation.
- Scorers: rules baseline (count of sustained overtime >= 6 h, >= 3 weeks without a weekend off,
  pulse drop >= 0.3; ASSUMED thresholds), logistic, LightGBM (always kept for SHAP); for
  contract_end also the contract-date rule (days to contract end). Winner = best pooled
  validation PR-AUC.
- Results (pooled test 2027-2029; rows are correlated employee-weeks):
  resignation (31 leavers, base 5.4%): rules ROC 0.542 / PR 0.071; logistic 0.691 / 0.119
  (winner); LightGBM 0.652 / 0.091. Logistic at its validation threshold: precision 0.147,
  recall 0.340.
  contract_end (16 leavers, base 18.7%): rules 0.423 / 0.160; logistic 0.715 / 0.276;
  LightGBM 0.729 / 0.293; contract-date rule 0.736 / 0.316 (winner). Its top calibration bin
  over-predicts (0.81 vs 0.37 observed): renewal rates differ by year and one validation year
  sets the Platt fit.
- Logistic can win because the planted hazard IS logistic in these drivers: a property of the
  synthetic data, not evidence for logistic on real data.

## T8: attrition drivers (SHAP, playbook, bands)

SUPERSEDED IN T12: bands are now rank-based and drivers come from the scoring model (see T12).
The notes below describe the T8 state.

Files: `ml/attrition/drivers.py`, `ml/attrition/explain.py`, `ml/attrition/playbook.json`;
`python run.py train` runs train then explain. Output `artifacts/attrition/v1/drivers.json`.
- SHAP from the explanation model (LightGBM) via LightGBM's built-in TreeSHAP
  (pred_contrib=True); verified identical to the shap package (max difference 0.0), so the shap
  package is not imported. Risk comes from the segment's calibrated winner (logistic /
  contract-date rule), drivers from LightGBM: they can disagree.
- 7 categories: overtime overload, stalled progression, low engagement, clustered-leave burnout,
  season-end exit, pay gap, manager relationship (UNSUPPORTED: manager_id exists but no signal
  about the relationship). department, role, is_department_head, tenure_days and peer_exits are
  context, not drivers. A category is reported if its SHAP sum >= driver_min_logodds (0.1,
  ASSUMED); top 3. Bands from config: watch >= 0.15, high >= 0.35 (ASSUMED).
- playbook.json: 2 interventions per driver (action, owner role, check_after_weeks,
  expected_effect marked ASSUMPTION).
- Demo checks (week 2029-12-24): PASS Sunita's drivers = overtime overload, clustered-leave
  burnout, pay gap; PASS Deepak low (0.023). Reported, not tuned: Sunita's risk is only 0.090
  (band LOW; base rate ~5%), so the demo story shows in her drivers, not her band; Deepak's
  one driver is "low engagement" despite pulse 4.2 (a LightGBM interaction, small effect).
  Arun (seasonal, contract ends in 21 days) is high (0.775). Staff that week: 47 low, 8 watch.

## T9: model interfaces (load from artifacts, never train)

```python
from ml import forecast, attrition, voice
forecast.predict("2029-12-01", "2029-12-05", as_of=None)  # -> ForecastResult(days=[ForecastDay])
attrition.score("2029-12-24", employee_ids=None)          # -> list[AttritionScore]
attrition.rescore("H901", attrition.protected_weekends_off("H901", 2))  # -> RescoreResult
voice.extract("ml/voice/clips/clip_01.wav")                # -> VoiceResult (T11)
```
- Pydantic results (ml/forecast/api.py, ml/attrition/api.py); every result has synthetic=True.
- forecast.predict: as_of defaults to the day before start_date; day d uses the smallest trained
  horizon >= d - as_of with features at d - H (never after as_of; tested by corrupting later
  occupancy). > 30 days ahead or outside the synthetic data -> ValueError.
- attrition.score: risk (calibrated winner), band, top-3 drivers with plain reasons, the top
  driver's 2 playbook actions. Heroes are scored (appended to the tables at scoring time only).
- attrition.rescore: overrides model feature values on one employee-week and re-scores: a
  SIMULATION, not causal proof (stated in every result). Sunita (H901) with two protected
  weekends off (weeks_since_weekend_off 5 -> 0, offs skipped in 4 weeks 4 -> 2, consecutive days
  38 -> 3; overtime unchanged): risk 0.0905 -> 0.0750 (-0.016), drivers unchanged (overtime
  hours dominate).

## T10: packaging

Every model lives in `artifacts/<name>/v1/` (occupancy_forecast, attrition, pulse, workload)
with model.joblib, metrics.json (model AND baseline), feature_list.json, dataset_hash.json
(SHA-256 of each SYNTHETIC input file with line endings normalised, plus a combined hash) and
model_card.md (generated by `ml/eval/package.py` from metrics.json). `python run.py eval`
retrains everything, rewrites metrics + plots, packages and runs `ml/eval/check_artifacts.py`
(every artifact loads, its dataset hash matches the data on disk, the interfaces run).
Full column reference: `docs/data_dictionary.md`. Dependencies: joblib listed explicitly; shap
dropped (LightGBM pred_contrib gives identical SHAP values) with its numba / llvmlite / slicer /
tqdm stack; scipy not listed (no direct import; scikit-learn and LightGBM pull it in).

## T11: voice notes (ml/voice)

Files: `config.yaml` / `config.py` (providers, privacy, Pydantic), `glossary.yaml` (25 hotel
terms in English, Devanagari Hindi and romanised Hinglish, mapped to issue + department; every
term unverified with `local_variants: TODO_HM_STUDENT`), `clips/manifest.yaml` (12 scripted
lines: file, source, language, reference transcript, expected room / issue / urgency /
department; demo clip clip_01.wav), `extraction.py` (deterministic glossary extraction
validated against a Pydantic schema and the glossary), `providers.py` (Groq Whisper, Sarvam,
local faster-whisper as swappable adapters; stdlib HTTP, no new dependency), `wer.py`,
`evaluate.py` (`python run.py eval-voice` -> docs/metrics/voice_eval.json), `api.py`
(`voice.extract`), `cache/demo_result.json` (demo fallback).
- PRIVACY: cloud adapters only get files listed in the manifest with source synthetic or
  hm_student (checked before any upload, size-capped); audio files are gitignored. Never real
  guest or staff audio.
- voice.extract tries providers in config order; if none can run and the file is the demo clip
  it returns the cached result with fallback_used=True; otherwise VoiceUnavailable says what is
  missing.
- Current numbers (no audio, no keys yet): extractor on the 12 reference transcripts 100% all
  fields (an UPPER BOUND and optimistic: transcripts and glossary were written together) vs the
  majority baseline 0% all fields (room 8%, issue 8%, urgency 58%, department 33%). No provider
  WER yet. The demo cache holds the reference transcript until a real clip is transcribed.
- TO SUPPLY: (1) the 12 recordings as ml/voice/clips/clip_01.wav .. clip_12.wav, read by the HM
  student from the manifest lines (or synthetic TTS); (2) GROQ_API_KEY and/or SARVAM_API_KEY as
  environment variables; (3) approval before installing faster-whisper (local, no upload);
  (4) the HM student's review of glossary.yaml (Hindi wording, Garhwali / Kumaoni variants, set
  verified_by_hm_student); (5) VERIFY the Groq / Sarvam URLs and model names in config.yaml.
  Then run `python run.py eval-voice`.

## T12: demo-ready ML fixes

- RISK BANDS (ml/attrition/bands.py, config attrition_model.band_high_share 0.10 /
  band_watch_share 0.15, ASSUMED): within each scoring week, active non-hero staff are ranked by
  calibrated risk inside their own group (permanent, seasonal). high = first ceil(10% x n) slots,
  watch = next ceil(15% x n), low = the rest. Identical (4-decimal) risks form a tie group that
  is never split: it takes a band only if it fits wholly in the remaining slots, else the next
  lower band (and that band is closed for everyone below). Heroes and re-scored employees are
  PLACED against the population and never take a slot. Output adds rank, group_size,
  rank_is_tied, is_demo_hero; the probability is kept.
  WHY CEIL-COUNT: the seasonal group has about 7 people, where a percentile rule can never create
  a high band. The rule was chosen AFTER one hero's rank was seen: Sunita sits ON the boundary
  (rank 5 of 48, risk 0.0905, between ranks 4 and 6), so her band is a ranking result, not a
  confident prediction. Her band: high (ceil-count, used) / watch (percentile rule).
  Backtest 2027-2029 (winner): resignation high precision 0.132 = 2.42x base 0.054, 52.3% of
  leaver-weeks in high + watch; contract_end (contract-date rule) 0.0: ~96% of seasonal risks
  per week are tied (risk is dominated by the contract-end date), the tie group is larger than
  the slots, so no seasonal employee lands in high / watch. Reported, not changed.
- FORECAST BAND: split-conformal. A twin trained on targets before
  forecast.conformal_calibration_start (2024-01-01) is scored on 2024; (n + 1)-corrected 10th /
  90th residual percentiles are added to the unchanged point forecast. 2025 coverage 1d 84.7%,
  7d 85.8% (just above the 75-85% target, reported, not tuned), 30d 83.3% (was 70 / 68 / 56%).
- EXPLANATIONS: drivers now come from the SAME model as the risk (FoldModel.contributions):
  calibrated log-odds relative to the training mean; logistic = Platt slope x coef x
  (standardised value - training mean), grouped into driver categories; contract-date rule =
  its days term. LightGBM TreeSHAP is a comparison only (drivers.json). Re-check: Deepak not
  high (PASS); Sunita's top drivers are overtime overload, pay gap, low engagement:
  clustered-leave burnout is NOT among them (FAIL, reported, not tuned; its logistic
  contribution nets to +0.02 because pre-festival leave was never planted in the hazard).
- CALIBRATION KEY: generator/calibrate.py config_fingerprint hashes only attrition-relevant
  sections (excludes signals, skills, forecast, attrition_model, label_horizon_days).
- SMOKE: python run.py smoke (fresh process; forecast.predict for the last data week,
  attrition.score for the latest week, Sunita rescore with two protected weekends off; exit 1 on
  any error). MOCKS: python run.py mocks writes data/mocks/{forecast_week,attrition_scores,
  rescore_sunita,heroes}.json with the Pydantic result types' field names (eval also runs it).

## T12b: seasonal rule bands, driver honesty

- SEASONAL BANDS: seasonal staff no longer get a model-rank band. band = contract-date rule:
  days to contract end <= 30 high, 31-60 watch, else low (attrition_model.seasonal_high_max_days /
  seasonal_watch_max_days, ASSUMED). A seasonal exit is a KNOWN date, not a prediction; about 96%
  of seasonal model risks were tied each week; this rule was chosen AFTER seeing the ties, not to
  place any hero. Output field band_basis: contract_date_rule (seasonal) / model_rank
  (permanent, unchanged). Backtest of the rule: high precision 0.368 = 1.97x base 0.187, 54.9% of
  leaver-weeks in high + watch (model ranks gave 0.0).
- DRIVER SUPPORT: clustered-leave burnout is WEAKLY SUPPORTED (the hazard has a weeks-without-
  leave term but no pre-festival leave term); manager relationship UNSUPPORTED. Marked in
  drivers.py (SUPPORT_LEVEL), playbook.json (support_level) and the model card; each Driver in
  the output carries contribution_logodds and support_level.
- DEMO CHECKS: the old "Sunita has overtime overload AND clustered-leave burnout" check was
  REMOVED (it came from the hero script, before we knew the generator never creates that driver).
  Now: Sunita's top 3 include overtime overload (PASS); Deepak is not high (PASS).
- Final-week drivers (calibrated log-odds): Sunita overtime_overload +0.619, pay_gap +0.464,
  low_engagement +0.280; Rajesh stalled_progression +0.395, low_engagement +0.122,
  overtime_overload +0.117; Meena pay_gap +0.580, overtime_overload +0.103; Arun season_end_exit
  +2.032; Deepak none above 0.1. Sunita: pay_ratio 0.97, months_since_raise 8.02,
  weeks_without_leave 8.

## Task 6: pulse prediction (regression, SYNTHETIC data)

Files: `ml/features/build_pulse_features.py`, `ml/features/split.py` (adds `split_like`,
`task5_reference_splits`, `load_pulse_splits`), `ml/models/pulse_common.py`,
`ml/models/train_pulse_baseline.py`, `ml/models/train_pulse_model.py`,
`ml/models/evaluate_pulse.py`. Outputs: `data/pulse_features.csv` (gitignored),
`artifacts/pulse/v1/` (since T10), `docs/metrics/{pulse_naive,pulse_model}.json`,
`docs/plots/pulse_pred_vs_actual.png`. Run: `python run.py train-pulse` (exit 1 if the model
does not beat naive on test MAE). Reads employee_v2.csv, weekly_behaviour.csv,
contract_renewals.csv only (never data/internal/).

Rows: employee-week t, active in t, with week t-1 history and an ACTIVE week t+1 (drops the first
week, the last observed week, the week right before an exit, and non-consecutive gaps).
Features (as of week t): department, role, contract_type (one-hot); tenure_days, load_ratio,
overtime_hours, leave_days, pulse_score, pulse_roll4_mean, pulse_trend_4w,
days_until_contract_end (capped at 56 then; 90 since T4). Label: next_week_pulse_score = the same
employee's pulse_score in week t+1.
Split: Task 5's week windows reused via split_like (train 2023-01-09..2026-12-07, 11041 rows;
val 2027-02-08..2028-04-17, 3399; test 2028-06-19..2029-10-29, 3877).

CURRENT (retrained in T7 on the T4 data, packaged in T10): test MAE 0.2498 vs naive 0.2567;
see artifacts/pulse/v1/. The numbers below are the ORIGINAL pre-T4 run.
Metrics (val / test):
- naive (next week = this week): MAE 0.2503 / 0.2453, RMSE 0.3189 / 0.3196, R2 0.832 / 0.802.
- LightGBM, L1 objective (325 trees): MAE 0.2447 / 0.2421, RMSE 0.3102 / 0.3099, R2 0.841 / 0.814.
The model beats naive on test MAE by 0.0032 (1.3%); no flag. An L2 objective was tried first and
only tied naive on test MAE (0.2456 vs 0.2453), which fired the NOT BETTER flag; L1 matches the
judged metric and was chosen on validation. The gain is small because naive is already near the
noise floor: the generator adds N(0, 0.3) each week, so even a perfect model has MAE ~0.239.
Top gains: pulse_score, pulse_roll4_mean, load_ratio, pulse_trend_4w, tenure_days.
Pulse drifts up over time (label mean 3.66 train, 3.81 val, 3.98 test), likely because
low-pulse (frustrated) staff are likelier to leave.

Presentation notes:
- Present this model as "matches a strong naive baseline, does not meaningfully beat it". The
  0.003 MAE margin is within the range another simulation seed could move it; it is not a
  strong result.
- Known limitation: the upward pulse drift across train / val / test (3.66 -> 3.81 -> 3.98)
  works against the tree model, which cannot extrapolate beyond the training range.

## Task 7: workload forecasting (department load_ratio, SYNTHETIC data)

Files: `ml/features/build_workload_features.py`, `ml/features/split.py` (adds
`load_workload_splits`, `main_workload`), `ml/models/workload_common.py`,
`ml/models/train_workload_baseline.py`, `ml/models/train_workload_model.py`,
`ml/models/evaluate_workload.py`. Outputs: `data/workload_features.csv` (gitignored),
`artifacts/workload/v1/` (since T10), `docs/metrics/{workload_naive,workload_model}.json`,
`docs/plots/workload_pred_vs_actual.png`. Run: `python run.py train-workload` (exit 1 if the
model does not beat naive on test MAE). Reads dept_week_load_dynamic.csv (Task 4's dynamic load,
not Task 3's static file) and event_calendar.csv only.

Rows: department-week t with >= 4 earlier weeks for that department and a next week t+1.
2160 rows = 6 departments x 360 weeks. Features (as of week t): department (one-hot);
week_of_year, occupied_room_nights, load_ratio, headcount, load_roll4_mean,
room_nights_roll4_mean, load_trend_4w (t minus t-4), is_festival_week (any festival day in week
t, from event_calendar.csv), next_week_is_festival (any festival day in week t+1; the festival
calendar is published in advance, so it is known at prediction time and is not leakage).
Label: next_week_load_ratio = the same department's load_ratio in week t+1.
Split: Task 5's week windows via split_like. train 2023-01-30..2026-12-07 (1212 rows), val
2027-02-08..2028-04-17 (378), test 2028-06-19..2029-10-29 (432); all 6 departments in each.

Metrics (val / test):
- naive (next week = this week): MAE 0.0815 / 0.0758, RMSE 0.1170 / 0.1134, R2 0.605 / 0.621.
- LightGBM, L1 objective (602 trees, hyperparameters fixed in advance): MAE 0.0582 / 0.0563,
  RMSE 0.0760 / 0.0804, R2 0.834 / 0.810.
The model clearly beats naive: test MAE -25.7%, RMSE -29%, R2 0.62 -> 0.81. No flag. That is
about 20x the relative gain of the Task 6 pulse model (-1.3%), as expected: load_ratio follows
occupancy's known seasonal calendar, while weekly pulse change is mostly random noise.
Per department (test MAE, naive -> model): the 5 occupancy-driven departments improve 25-28%;
security's load is flat (workload has no per-room hours), so naive is exact there (0.0000) and
the model adds a small error (0.0050).
Top gains: load_ratio, week_of_year, load_roll4_mean, load_trend_4w, room_nights_roll4_mean.

Notes:
- next_week_is_festival is NOT leakage: festival calendars are published well in advance of the
  week in question, so the flag is known at the end of week t. It describes the calendar, not
  next week's realised occupancy or load.
- booking_pace_7d (bookings already on the books for next week's stay dates, fully known by the
  end of week t) was deliberately left out. It is a likely future improvement, NOT implemented.
- Security's load does not depend on occupancy (its workload has 0 per-room hours), so the model
  adds negligible value over naive there (naive is exact; the model adds ~0.005 MAE). This is
  expected, not a bug; routing security to the naive rule would remove that small error.

## Fix: replacement hires missing skills (after T12b)

Replacement hires previously had NO skills: run_staff assigned skills to the original 55 only,
so by 2029-12-24 only 9 of 55 active staff held any skill and no active front-office employee
held fo_system (all 3 original holders had left in 2023-2024), which made the backend roster's
fo_system rule infeasible. Fixed by extending skill assignment to every employee:
`ml/generator/run_skills.py` (after run_attrition in `python run.py generate`) keeps the original
rows and gives each replacement hire, in hire order, the same skill draw (1-3 by role tier, heads
>= 2) from a NEW random stream `replacement_skills` appended at the END of STREAMS, then tops the
hire up with any department skill whose holders among the staff active on the hire date fell
below the minimum (3 fo_system, 2 otherwise). Only employee_skill.csv changed (99 -> 368 rows,
209 employees); every other data file, metric, plot, card and mock is byte-identical.
Demo week coverage: every active employee holds skills, no skill is below its minimum, front
office has 7 fo_system holders. Coverage can dip during a vacancy gap (leaver gone, replacement
not yet started; seen once in a quarterly sample, front_office 2023-07-03). validate gains 7
checks (ml/generator/validate_skills.py): 65 PASS.

## Commit-to-task map

Two task numbering series exist: the original Tasks 1-8, then a batch T4-T12b that reused the
numbers 4-8. Commits (oldest first) and the tasks they hold:

| Task | Commit | Note |
|---|---|---|
| Task 1 | e6d3bb0 | scaffold and config |
| Task 2, 2b, 2c | 4f9ab7c, dbe0ce0, 56511f4 | calendar / weather / occupancy; peak tuning |
| Task 3 (+ 3b) | 98af133 | Task 3b (workload calibration) has no commit of its own: folded into the task3 commit |
| Task 4, 4c | e585b09, a579baa | weekly behaviour and attrition; seasonal replacement drift fix |
| Task 5 (original) | 0682366 | old attrition training pipeline (retired in batch T7) |
| Task 5b | none | horizon extension to 2029 has no commit of its own; cited only in the Data files section ("since Task 5b") |
| repo reorganisation | 915e687, 9d11dbf | ml/ frontend/ backend/ split; root CLAUDE.md |
| Task 6, 7 (original) | 555aa68, 83e5dba | pulse and workload models |
| Task 8 (original) | 5798050 | consolidated model card, committed as "docs: add consolidated model card" |
| T4a, T4b (batch) | 2a7c64c, 9f002e7 | T4c (sustained-overtime fix) has no separate commit: it landed in 9f002e7 (task4b) |
| T5-T8 (batch) | bb79253, 7f3abb9, ef176a8, 2a44400 | weekly signals and heroes; occupancy forecast; attrition model; drivers |
| T9-T11 (batch) | f840dc4, 35c9abb, 498dc31 | interfaces; packaging; voice |
| final verification | 7570c09 | ml: final verification |
| T12, T12b | f022222, b9a65fa | demo-ready fixes; seasonal rule bands and driver honesty |

## Status

- Task 1 done: scaffold + config
- Task 2 done: calendar, weather, occupancy
- Task 2b done: reduced peak saturation. month_base_occupancy May 0.90 -> 0.78, Jun 0.88 -> 0.75
  (char_dham_bump unchanged at 0.05). May-Jun mean 0.949 -> 0.841, sold-out May-Jun days
  37.2% -> 2.7%, 2025 seasonal-naive MAPE 13.37% -> 13.86%. Validation now also checks
  sold-out share of May-Jun days < 15%.
- Task 2c done: Char Dham (May-Jun) is the peak season. month_base_occupancy Oct 0.70 -> 0.64,
  Dec 0.75 -> 0.68 (May/Jun untouched). Busiest non-peak month Dec 0.819 -> 0.749, Oct-Dec mean
  0.728 -> 0.684; May-Jun mean 0.841, sold-out 2.7%, MAPE 13.86% unchanged. Validation now also
  checks May-Jun mean <= 0.88 and May-Jun mean > every other month's mean.
- Task 3 done: staff, skills, workload. Workload standards are calibrated placeholders
  (Task 3b); load_ratio median 0.900, May-Jun mean 1.150, Feb mean 0.638, max 1.315.
  data/internal/ is gitignored.
- Task 4 done: weekly behaviour, attrition, exits, replacement hires. Final
  base_weekly_exit_hazard = 0.009 (ASSUMED, chosen for ~30% annualised attrition): attrition
  30.4%, pulse May-Jun 3.347 vs Feb 3.776, 50 exits (41 resignation, 9 seasonal_end), 4 renewals.
  Attrition settings are ASSUMED placeholders pending HM student confirmation. Hazard unit tests
  use a fixed base hazard independent of config. data/internal/ is still gitignored; this task
  only appends rows to employee_latent.csv.
- Task 4c done: replacement hires keep the leaver's contract type (fixes the seasonal-staff
  drain); horizon extended to 2029-12-31. All 38 Task 2-4 checks pass on 3-year and 7-year runs.
- Task 5 done: attrition training pipeline (features, time split, logreg + LightGBM, evaluation
  with relative WEAK / LEAK flags), days_until_contract_end capped at 56, models in
  ml/artifacts/. Test PR-AUC logreg 0.257, LightGBM 0.273 vs oracle 0.407. No flags.
- Repo reorganised: all ML code under ml/; empty frontend/ and backend/ at the repo root.
- Removed empty Task 1 placeholders ml/app/, ml/bot/, ml/dashboard/ (superseded by the
  repo-root backend/ and frontend/). Project-wide rules now live in the root CLAUDE.md.
- [HISTORICAL, superseded by the T7 retrain below: test MAE pulse 0.2498 vs naive 0.2567
  (-2.7%), workload 0.0530 vs 0.0729] Task 6 done: pulse regression (naive vs LightGBM L1). 223
  tests pass; test MAE 0.2421 vs naive 0.2453: matches a strong naive baseline, does not
  meaningfully beat it.
- [HISTORICAL, superseded by the T7 retrain] Task 7 done: workload forecasting (naive vs
  LightGBM L1). 232 tests pass; test MAE 0.0563 vs naive 0.0758 (-25.7%), clearly beats naive.
- Task 8 done: consolidated model card in docs/MODEL_CARD.md (documentation only).
- T4 done (T4a + T4b): logistic driver hazard with a 10-week sustained-overtime driver, raises,
  90-day label with censoring, calibrated intercept (fast fingerprinted reuse), expanding-window
  probes with a 90-day gap and ranked pooling, multi-seed validate-seeds; config A5 chosen on
  seeds 42-44, confirmed on 48-53.
- T5 done: weekly signals (task score, weekend offs, consecutive days, pre-festival leave), leave and
  pulse tables, 5 scripted demo heroes validated against their script.
- T6 done: occupancy forecast (ml/forecast), direct LightGBM per horizon vs seasonal-naive, train
  2023-2024 / test 2025. Test MAPE model vs baseline: 1d 6.7% vs 13.7%, 7d 7.2% vs 13.7%, 30d
  10.3% vs 13.7% (model used at all horizons). 80% quantile band UNDER-COVERS (70%, 68%, 56%;
  HISTORICAL, superseded by the T12 split-conformal band: 84.7%, 85.8%, 83.3%);
  high-demand alerts (>= 0.90) are weak (precision 0.29-0.56, recall 0.12-0.29). Artifacts in
  artifacts/occupancy_forecast/v1/; python run.py train-forecast.
- T7 done: attrition model (ml/attrition). Pooled backtest 2027-2029: resignation logistic ROC
  0.691 / PR 0.119 vs rules 0.542 / 0.071 (LightGBM 0.652 / 0.091); contract_end winner is the
  contract-date rule 0.736 / 0.316 (LightGBM 0.729, logistic 0.715). Pulse and workload retrained.
- [HISTORICAL, superseded by T12 / T12b: drivers now come from the scoring model, bands are
  rank-based (seasonal: contract-date rule)] T8 done: drivers via LightGBM TreeSHAP into 7
  categories (manager relationship UNSUPPORTED),
  playbook.json, bands. Sunita drivers overtime overload + clustered-leave burnout (PASS), Deepak
  low (PASS); Sunita's own risk is 0.090 = low band (reported, not tuned).
- T9 done: forecast.predict, attrition.score / rescore (SIMULATION), voice.extract stub (HISTORICAL:
  implemented in T11), Pydantic
  results, tests on the committed artifacts. Sunita rescore with two protected weekends off:
  0.0905 -> 0.0750.
- T10 done: versioned artifacts with model cards, dataset hashes and metrics vs baselines;
  python run.py eval / check-artifacts; docs/data_dictionary.md; shap removed, joblib added.
- T11 done: ml/voice (glossary 25 terms, 12-clip manifest, Groq / Sarvam / faster-whisper
  adapters, schema-validated extraction, WER + extraction eval, cached demo fallback). No audio or
  API keys yet: reference-transcript extraction 100% vs majority baseline 0% (all fields).
- ML final verification: test --all 322 passed, lint clean, generate byte-identical (calibration
  fingerprint refreshed), validate exit 0, validate-seeds exit 0 (rule 0.629, logistic 0.752,
  gap +0.122, no-driver 6.8%), eval exit 0 (all artifacts load, hashes match).
- T12 done: rank-based bands (Sunita high at rank 5/48, on the boundary), conformal forecast band
  (84.7 / 85.8 / 83.3%), same-model explanations (Sunita clustered-leave check FAILS, reported),
  attrition-only calibration key, run.py smoke + mocks.
- T12b done: seasonal contract-date rule bands (band_basis), clustered-leave burnout WEAKLY
  SUPPORTED, demo checks replaced (both PASS), contributions in the output.
- Fix done: replacement hires get skills (new stream replacement_skills); only employee_skill.csv
  changed; validate 65 PASS; demo-week front office has 7 fo_system holders.

## Hotel variants: the fictional Himsagar Ridge Resort (served default)

`ml/generator/hotel_variant.py` + `ml/generator/hotels/himsagar.yaml` (`python run.py generate-hotel himsagar`): the
same generator stages on a config merged over config.yaml, written to `ml/data/hotels/himsagar/` (same file set as
ml/data; `internal/` is gitignored; `demo/` hero files are header-only: no demo heroes in a variant; plus `hotel.json`
with the staff positions and role titles). FICTIONAL hotel, SYNTHETIC data, every value ASSUMED: 24 rooms, 19 rostered
staff (housekeeping 6, front office 3, F&B 3, kitchen 3, maintenance 2, security 2) plus the hotel manager HS01 (not in
the ml data, not rostered or scored). Mussoorie seasonality: May-Jun summer peak, Christmas-New Year winter peak
(festival_bump 0.18), monsoon dip. Workload standards scaled from the default hotel so load_ratio is the same function of
occupancy. Role codes and pay are the default vocabulary, so the trained artifacts score it unchanged (identical
feature columns; models NOT retrained). Demo-week staff are renamed HS02..HS20 in position order, earlier leavers
HSX001.. . Seed 4243 = first seed from 4242 whose demo week fills every position and is rosterable under
backend/hotels/himsagar.yaml (chosen once with CP-SAT; a demo-data choice). Small ml changes for this: forecast.predict
takes `rooms=` (booking pace is divided by the room count), attrition.explain skips empty hero files, run_skills.build
takes a cfg. The default ml/data dataset is byte-identical. Tests: tests/test_hotel_variant.py (reproducible generation).

## REAL public data (ml/realdata) - the one exception to "all data is synthetic"

`python run.py realdata` re-tests the forecast and attrition approaches on PUBLIC datasets
(Hotel Booking Demand, REAL, CC BY 4.0; IBM HR, FICTIONAL; Babushkin turnover, real but
unverified origin, CC BY-NC-SA = evaluation only). Outputs go ONLY to
`artifacts/{occupancy_forecast,attrition,realdata_gpu}/real_v1/`; the synthetic `v1` artifacts,
the API and the product never read them. Raw downloads (`data/realdata/raw/`, SHA-256 checked)
and fine-tuned TimesFM layers are gitignored. GPU deps (torch cu128, xgboost, timesfm):
`realdata/requirements-gpu.txt`. Protected columns are dropped in `realdata/attrition.py`.
Tests: `tests/test_realdata.py` (no download; the CV test needs the GPU). Results:
`docs/REAL_DATA_RESULTS.md` (repo root), `realdata/README.md`, and the plain-language
attrition rating `realdata/attrition/VALIDATION.md` (Babushkin HoReCa subset: 10 people;
US OPM federal data NOT used: no person id to link a snapshot to later separations; see
`realdata/attrition/DATA_CARD_OPM.md`).

## Hotel alerts: cancellation model (REAL data) and prediction checks for every model

- `ml/realdata/hotel_alerts/` (features.py, train.py, api.py, DATA_CARD.md, RESULTS.md):
  booking cancellation / no-show risk on Hotel Booking Demand (REAL, CC BY 4.0), booking-time
  features only (leaky columns excluded and tested), snapshots at booking and 1-90 days before
  arrival, split by arrival date (train <= 2016-10-31, val Dec-Jan, test Mar-Aug 2017).
  `python run.py train-cancellation` (GPU only) -> `artifacts/cancellation/real_v1/`. Test at
  booking: XGBoost ROC 0.820 / PR 0.786 / Brier 0.168 vs base rate 0.638 / 0.494 / 0.234
  (logistic 0.795).
  Night-level source (model vs base-rate table) chosen per horizon on validation: base-rate table at
  every horizon (the model was better on the test at 14 / 30 days; reported, not switched).
- `ml/guardrails.py`: schema / range checks, output clipping, drift (row z-score + range; PSI for
  batches >= 200 rows) against `reference_stats.json`, baseline fallback, confidence label,
  stale-model rejection (365 days), logging (`hoi.guardrails`). Guarded entry points:
  `ml/forecast/guarded.py`, `ml/attrition/guarded.py`, `ml/models/workload_api.py`,
  `ml/realdata/hotel_alerts/api.py`. `python run.py guard-reference` rewrites the v1 references
  (models unchanged). `python run.py backtest-monitor [--hotel himsagar] [--strict]`: rolling error
  vs baselines (finds: default-hotel workload worse than naive over the last 12 weeks; Himsagar
  forecast band covers ~67% instead of 80%). Tests: tests/test_guardrails.py, tests/test_hotel_alerts.py.

## GPU-only training (all models)

Every model fit, hyperparameter search, cross-validation and evaluation prediction in `ml/` runs
on the GPU: XGBoost with `device="cuda"` (it replaced LightGBM everywhere) and torch on CUDA for
logistic regression and Platt scaling (`ml/torch_logistic.py`, same L2 objective as
scikit-learn's default, C = 1). No scikit-learn estimator is trained any more (scalers / one-hot
encoders and sklearn.metrics remain). One shared check, `ml/gpu.py` `require_cuda()`, runs before
any training: torch.cuda.is_available() AND an XGBoost CUDA test fit; otherwise
GPURequiredError, never a CPU fallback. Every metrics.json records `train_device` and
`eval_device` ("cuda:0 NVIDIA GeForce RTX 4050 Laptop GPU").

Serving stays on the CPU (Render has no GPU, and the servers install neither torch nor xgboost):
trained XGBoost models are exported to numpy tree arrays (`ml/xgb_trees.py` TreeEnsemble,
checked against XGBoost at export) and torch logistic models keep numpy coefficients
(`to_cpu()` before saving). The crowd model's trees go to plain JSON for the pure-Python
`predict.py` (byte-identical copy in the portal). Tests that train are marked `gpu` and are
SKIPPED without a GPU (CI), never run on the CPU. The earlier task notes above quote LightGBM
results: they are historical; the current numbers are in each artifact's metrics.json.
