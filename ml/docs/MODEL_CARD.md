# Hospitality Operations Intelligence model card

**Everything described here is built on SYNTHETIC data.** No real hotel, guest or employee data
was used. The data comes from a seeded simulator whose settings are ASSUMED placeholders. The
numbers below show how the models behave on that simulated hotel; they say nothing about a real
hotel until the placeholders in [section 3](#3-placeholders-that-need-real-values) are replaced
with real values and everything is regenerated.

Contents: [1. Overview](#1-overview) · [2. The models](#2-the-models-current-t7-t10) ·
[3. Placeholders](#3-placeholders-that-need-real-values) ·
[4. How to regenerate everything](#4-how-to-regenerate-everything) ·
[5. Known limitations](#5-known-limitations)

## 1. Overview

Hospitality Operations Intelligence (HOI) is for small hill hotels in Uttarakhand. The simulator creates one hypothetical
45-room hotel with 55 staff in 6 departments, week by week from 2023 to 2029: occupancy
(including the Char Dham peak in May-June and the monsoon slump), weather and road closures,
staff, their skills, weekly workload, overtime, leave, a 1-5 "pulse" mood score, weekly signals
(task score, weekend offs, pre-festival leave), resignations, seasonal contracts ending, and
replacement hires.

Four models are trained on that data, plus a voice-note pipeline:

| Component | Question it answers | Horizon | Detailed card |
|---|---|---|---|
| Occupancy forecast | How full will the hotel be, with an 80% band and demand alerts? | 1, 7, 30 days | [occupancy_forecast](../artifacts/occupancy_forecast/v1/model_card.md) |
| Attrition | Will this employee leave in the next 90 days, and why? Separate evaluations for resignations (permanent staff) and contract-end exits (seasonal staff) | 90 days | [attrition](../artifacts/attrition/v1/model_card.md) |
| Pulse | What will this employee's pulse score be next week? | 1 week | [pulse](../artifacts/pulse/v1/model_card.md) |
| Workload | How loaded will each department be next week (required ÷ available staff hours)? | 1 week | [workload](../artifacts/workload/v1/model_card.md) |
| Voice (not a trained model) | Which room, issue, urgency and department does a staff voice note describe? | — | ml/CLAUDE.md, section T11 (no audio clips or API keys yet) |

How to read the metrics:
- **MAE** (mean absolute error): the average size of a prediction's miss. Lower is better.
- **MAPE**: MAE as a share of the actual value (used for occupancy).
- **R²**: share of the ups and downs the model explains; 1.0 is perfect. Higher is better.
- **ROC-AUC**: chance the model ranks a random leaver above a random stayer; 0.5 is a coin flip.
- **PR-AUC**: how precise the model's "will leave" list is; a coin flip scores the base rate
  (the share of employee-weeks followed by an exit within 90 days: 5.4% for permanent staff,
  18.7% for seasonal staff). Higher is better.
- **Test periods**, always split by time, never at random:
  - attrition: an expanding-window backtest over 2027-2029. For each test year the model trains
    on rows whose 90-day label window ends before the previous year starts (a 90-day gap, so no
    training label looks into the evaluation years), calibrates and picks its threshold on the
    previous year, and is tested on the year itself.
  - occupancy forecast: trained on targets up to 2024, tested on 2025.
  - pulse and workload: the first ~60% of weeks train, the next ~20% validate, the last ~20%
    test, with a 13-week (label horizon) embargo between periods.

## 2. The models (current, T7-T10)

Each trained model has its own card next to its files: `ml/artifacts/<name>/v1/model_card.md`
(intended use, data, metrics vs baseline, limitations, planted-drivers honesty note), plus
metrics.json, feature_list.json and dataset_hash.json. Headline test numbers (SYNTHETIC data):

| model | metric | model | baseline |
|---|---|---|---|
| occupancy_forecast (1 / 7 / 30 days) | MAPE, 2025 | 6.7% / 7.2% / 10.3% | seasonal-naive 13.7% |
| attrition, resignation (permanent) | ROC-AUC / PR-AUC, 2027-2029 | logistic 0.691 / 0.119 | rules 0.542 / 0.071 |
| attrition, contract end (seasonal) | ROC-AUC / PR-AUC, 2027-2029 | contract-date rule 0.736 / 0.316 (winner) | rules 0.423 / 0.160 |
| pulse (next week) | MAE | 0.2498 | naive 0.2567 |
| workload (next week load ratio) | MAE | 0.0530 | naive 0.0729 |

The attrition label is now 90 days (it was 8 weeks before T4); the old Task 5 attrition models
were retired in T7. Drivers (T8), the interfaces (T9), rank-based bands and the conformal
forecast band (T12) and seasonal rule bands (T12b) are described in ml/CLAUDE.md and in the
per-model cards.

## Generator difficulty (Task T4)

The attrition simulator plants observable drivers (sustained overtime, weeks without leave, low
or falling pulse, pay gap, months since a raise, load, peer exits, first year) plus a hidden
frustration trait and weekly noise into a logistic weekly resignation hazard, calibrated to 40%
annual attrition. Difficulty probes on permanent staff check that the drivers are learnable but
not trivial. Section 2 holds the models retrained on this data (T7-T10).

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

## 3. Placeholders that need real values

Every value below is ASSUMED or CALIBRATED, not measured. Real values from the HM student
should replace them, followed by a full regenerate, validate and retrain (section 4).
"Where it lives" names the section key in `ml/generator/config.yaml` unless a file is given.

| What | Current placeholder | Where it lives | Status |
|---|---|---|---|
| Hotel size and date range | 45 rooms; 2023-01-01 to 2029-12-31 | `property` | ASSUMED; end date extended to 2029 for model testing |
| Staff total and per-department counts | 55 staff: housekeeping 16, F&B service 10, kitchen 10, front office 8, maintenance 6, security 5 | `staff_target`, `departments` | ASSUMED |
| Roles, headcount and monthly pay per role | e.g. head chef 45,000 ± 5,000 INR; attendant 14,000 ± 1,500 (17 roles) | `roles` | ASSUMED, to be confirmed by the HM student |
| Skills per department | e.g. housekeeping: room_cleaning, turndown, laundry, deep_clean | `skills` | PLACEHOLDER lists |
| Skill coverage rules | ≥ 3 staff hold fo_system, ≥ 2 hold every other skill | code: `ml/generator/config.py` (SKILL_MIN_HOLDERS) | ASSUMED |
| Tenure, seasonal share, contract end dates, weekly hours | tenure mean 1.5 years; 25-30% of attendants, waiters and helpers seasonal; contracts end 06-30 or 10-31; 48 h/week | `staff` | ASSUMED |
| Workload hours per occupied room-night | e.g. housekeeping 90 h base + 3.19 h per room-night; security 216 h flat | `workload` | CALIBRATED PLACEHOLDERS, not real standards: fitted so the median load_ratio is about 0.90. Per-room hours are inflated |
| Attrition hazard | logistic weekly hazard in observable drivers (10-week sustained overtime, weeks without leave, low and falling pulse, pay gap, months since a raise, load, peer exits, first year) plus a hidden frustration trait and noise; the intercept is calibrated to the 40% target (currently −7.3125, giving 40.0% a year, saved in `ml/data/attrition_calibration.json`); seasonal renewal chance 0.4; vacancy 2-30 days | `attrition` (`hazard`, `raises`, `calibration`), `target_annual_attrition` | ASSUMED (coefficient set A5), pending HM student confirmation |
| Attrition model settings | rules-baseline thresholds (6 h sustained overtime, 3 weeks without a weekend off, pulse drop 0.3); risk bands (top 10% high, next 15% watch, permanent staff); seasonal bands (contract ends within 30 days high, within 60 watch); minimum driver contribution 0.1 log-odds | `attrition_model` | ASSUMED |
| Weekly signals | task-score fatigue and noise, skipped-weekly-off odds, weekend-off share, festival lookahead 10 days | `signals` | ASSUMED |
| Forecast settings | horizons 1 / 7 / 30 days; 80% band; alerts at ≥ 0.90 and ≤ 0.35 occupancy; conformal calibration year 2024 | `forecast` | design choices; alert levels ASSUMED |
| Monthly base occupancy | e.g. May 0.78, June 0.75, February 0.30 | `month_base_occupancy` | ASSUMED; May, June, October and December re-tuned so Char Dham is the clear peak |
| Weekend, festival and Char Dham effects | weekend +0.12, festival +0.10, Char Dham +0.05 (May 1 to June 30) | `weekend_uplift`, `char_dham_season`, `occupancy` | ASSUMED |
| Weather and road closures | monthly temperature and rain chance; heavy-rain chance; about 4 closures a year, 70% in the monsoon | `weather`, `road_closures` | ASSUMED |
| Room rates and booking pace | ADR by month (e.g. May 5,200 INR); 70% of rooms booked 7 days out | `adr`, `booking_pace` | ASSUMED |
| Festival dates 2023-2025 | Holi, Dussehra, Diwali; Christmas-New Year window Dec 24 to Jan 1 | `ml/generator/festivals.yaml` (`festivals`, `recurring_festivals`) | From the project brief; must be verified |
| Festival dates 2026-2029 | Holi, Dussehra, Diwali | `ml/generator/festivals.yaml` (`festivals`) | UNVERIFIED approximations; check against a panchang |
| School holidays | about May 20 to June 30, December 24 to January 5 | `ml/generator/festivals.yaml` (`school_holidays`) | ASSUMED |
| Hidden employee traits | overtime propensity, baseline pulse (mean 3.8), baseline task score, frustration | code: `ml/generator/staff.py` (constants) | ASSUMED, generator-only |
| Skill level odds by role | heads mostly level 3, entry roles mostly level 1 | code: `ml/generator/skills.py` (LEVEL_PROBS) | ASSUMED |
| Demo heroes | 5 scripted fictional employees (Sunita, Rajesh, Meena, Arun, Deepak) over the last 12 weeks | `ml/generator/heroes.yaml` | Scripted demo ASSUMPTIONS, never in training |
| Voice glossary and clips | 25 hotel terms (English, Hindi, Hinglish); 12 scripted clip lines | `ml/voice/glossary.yaml`, `ml/voice/clips/manifest.yaml` | DRAFT, unverified by the HM student; no audio yet |

## 4. How to regenerate everything

From the repo root, once: `py -3.13 -m venv .venv`, then
`.\.venv\Scripts\Activate.ps1` and `pip install -r ml\requirements-lock.txt`. Then:

```powershell
cd ml
python run.py generate        # simulate occupancy, staff, attrition and signals; write data/
python run.py validate        # 65 PASS/FAIL checks on the generated data (+1 INFO line)
python run.py validate-seeds  # pooled difficulty checks over seeds 42-44
python run.py train           # attrition: backtest, calibration, bands, drivers
python run.py train-forecast  # occupancy forecast
python run.py train-pulse     # pulse: naive baseline vs model
python run.py train-workload  # workload: naive baseline vs model
python run.py eval            # all of the training above + packaging + load check + mocks
python run.py smoke           # fresh process: forecast, scores, Sunita rescore
python run.py test --all      # the full test suite (python run.py test skips slow tests)
```

`validate`, `validate-seeds`, `train`, `train-pulse`, `train-workload`, `eval`, `smoke` and
`test` exit non-zero when a check, quality flag or test fails, so a failure is never silent.

**Reproducibility**: every random draw comes from one seed (`seed: 42` in config.yaml).
The same seed and config always give byte-identical data files, metrics, plots, model cards and
mock files, and identical model predictions. The one exception is the attrition model file
(`ml/artifacts/attrition/v1/model.joblib`): its pickle bytes differ from run to run, but its
predictions match exactly (verified: maximum difference 0.0). The other model files are
byte-identical.

## 5. Known limitations

- **All data is synthetic** and every setting in section 3 is a placeholder; no result here is
  evidence about a real hotel.
- **The drivers are planted**: every attrition result shows the pipeline recovering a mechanism
  the generator put there. Logistic regression wins for resignations because the planted hazard
  is logistic.
- **Festival dates 2026-2029 are unverified**, and the 2023-2025 dates still need checking.
- **Workload hours are calibrated, not real**: they were fitted to give plausible load ratios,
  so absolute load_ratio values are not staffing standards.
- **Resignations are predictable but modestly**: resignation ROC-AUC 0.691 (PR-AUC 0.119 against
  a 5.4% base rate) on the 2027-2029 backtest. Seasonal exits follow a known contract date, so
  seasonal staff get a contract-date rule band, not a prediction. Contract renewals cannot be
  foreseen.
- **Small test sets**: 31 permanent and 16 seasonal leavers in the pooled 2027-2029 test years,
  and test rows are correlated employee-weeks; metric differences of a few points are within
  seed-to-seed noise.
- **Pulse model gains little over naive**: test MAE 0.2498 vs 0.2567 (−2.7%). The weekly noise
  floor leaves little to learn, and pulse drifts upward over time, which tree models cannot
  extrapolate.
- **Occupancy band**: the split-conformal 80% band covers 84.7% / 85.8% / 83.3% of 2025 days at
  1 / 7 / 30 days; the 7-day horizon is just above the 75-85% target (reported, not tuned).
  High-demand alerts are weak.
- **Attrition bands are ranks**: someone always fills the high slots, even in a calm week. Demo
  hero Sunita sits on the high / watch boundary (rank 5 of 48); see the attrition card.
- **Clustered-leave burnout is weakly supported** (the hazard has no pre-festival leave term) and
  **manager relationship is unsupported** (no manager signal in the data).
- **Workload model does not help security**, whose load is flat. Use the naive rule there.
- **booking_pace_7d is not used** by the workload or pulse models (the occupancy forecast uses it
  for horizons up to 7 days). It is known a week ahead and is probably the strongest missing
  workload feature.
- **Workforce drift was fixed** (Task 4c): replacements now keep the leaver's contract type.
  Before the fix, seasonal staff disappeared over the years and models trained on early years
  failed on later ones. Re-check the seasonal share by year if replacement rules change.
- **Attrition is calibrated to the 40% target**: 40.0% a year over 2023-2029 (intercept
  −7.3125). The target itself is an ASSUMED value.
- **First-year risk is a simple step**: the hazard adds a fixed term (coefficient 0.3) in an
  employee's first year.
- **manager_id is fixed at hire**: it is not updated when a department head is replaced.
- **Leave does not reduce available hours** in the workload calculation.
- **Hidden traits must stay hidden**: `ml/data/internal/` holds generator-only traits. Model,
  backend and frontend code must never read them (see the root CLAUDE.md).
