> **SUPERSEDED, historical snapshot as of commit 5798050 (2026-10-10).** Everything below
> describes the repo BEFORE tasks T4-T12b (8-week label, old artifacts, PARTIAL statuses).
> For the current state see ml/CLAUDE.md, ml/docs/MODEL_CARD.md and the per-model cards in
> ml/artifacts/<name>/v1/model_card.md.

# Hospitality Operations Intelligence ML audit (read-only)

Audit date 2026-10-10, at commit `5798050` (main, in sync with origin/main). ALL data is
SYNTHETIC. Nothing was fixed, edited or deleted during the audit. Running `generate` and
`validate` rewrote the data files and plots, and `git status` stayed clean afterwards, so every
tracked file came out byte-identical. Paths are relative to the repo root; the brief's `data/`
and `docs/` are `ml/data/` and `ml/docs/` since the repo reorganisation (commit `915e687`), so
this report is saved at `ml/docs/ml_audit.md`.

## Final report

| Component | Status | Evidence (command and key numbers) | Gap |
|---|---|---|---|
| Staff data | DONE | `run.py validate`: staff 16/16 PASS (55 staff, 6 heads, skill coverage, no latent or protected columns, same-seed hash) | Values are ASSUMED placeholders awaiting the HM student |
| Attrition data | PARTIAL | `weekly_behaviour.csv` 20,051 rows, `exits.csv` 130 rows (87 resignation, 43 seasonal_end), attrition 33.8%/yr; 11/11 checks PASS | Label is 8 weeks, not 90 days; no hero employees; no weekly task score or weekend-off; 23.1% of exits have no visible driver (target 10-20%) |
| Forecast model (occupancy) | MISSING | `ml/forecast/` contains only `__init__.py`; `ml.forecast.predict` raises AttributeError | No model, no MAPE by horizon, no uncertainty band, no alerts. Only a seasonal-naive MAPE sanity check exists (16.66% on 2029) |
| Workload forecast (extra) | DONE | `run.py train-workload`: test MAE 0.0563 vs naive 0.0758 (-25.7%), R² 0.62 -> 0.81 | Not an occupancy forecast; booking_pace_7d unused |
| Pulse model (extra) | DONE | `run.py train-pulse`: test MAE 0.2421 vs naive 0.2453 (-1.3%) | Matches naive, does not meaningfully beat it |
| Attrition model | PARTIAL | Logistic regression + LightGBM, time split with 8-week gaps, calibration deciles; test ROC-AUC 0.787 / 0.751, PR-AUC 0.257 / 0.273 (base 0.044) | No rules baseline; threshold fixed at 0.5, not chosen; no SHAP; code is in `ml/features/` and `ml/models/`, while `ml/attrition/` is empty |
| Driver mapping | MISSING | `grep shap` finds no usage; no driver categories or intervention table anywhere | No SHAP values, no grouping into the 7 driver categories, no driver-to-intervention table |
| Rescore (what-if) | MISSING | `ml.attrition.rescore` raises AttributeError | No what-if function |
| Voice | MISSING | `ml/voice/` contains only `__init__.py`; `ml.voice.extract` raises AttributeError | No code, clips, bake-off report, glossary or cached demo result |
| Packaging | PARTIAL | `ml/artifacts/`: 4 `.joblib` files; `ml/docs/metrics/`: 6 JSON files; one consolidated `ml/docs/MODEL_CARD.md` | No per-model model_card.md, feature_list.json or data hash; no scoring API; no standalone eval command (evaluation runs inside the train commands) |
| Tests | DONE | `run.py test`: 232 passed, 0 failed, 0 skipped; `run.py lint`: All checks passed | No tests for components that do not exist yet |
| Docs | PARTIAL | `CLAUDE.md` (root + ml), `MODEL_CARD.md`, README | No standalone data dictionary (the "Data files" section of ml/CLAUDE.md serves as one); one stale line (see A2) |

### Top 10 problems (most severe first)

1. **The headline attrition result rests on a near-deterministic countdown.** Most of the
   model's skill comes from `days_until_contract_end` (seasonal contracts ending). On permanent
   staff it is near chance: LightGBM test PR-AUC 0.031 vs base 0.026. A judge seeing one
   dominant feature may suspect leakage. It is legitimate (contract end dates are known in
   advance), but it has to be framed explicitly, or the numbers will be distrusted.
2. **Config declares settings the code ignores.** `label_horizon_days: 90` and
   `target_annual_attrition: 0.40` in `ml/generator/config.yaml` are read by no code (grep
   finds no use outside config.py and tests). The real label is 8 weeks; the real rate is 33.8%.
3. **No rules baseline for attrition.** It is compared only with chance and the generator's
   oracle ceiling. The audit computed an overtime-only rule: test ROC-AUC 0.512-0.522, PR-AUC
   0.043 (base 0.044), i.e. random. Not yet in the pipeline.
4. **The occupancy forecast model is MISSING**, though it is a core product claim. There is
   no seasonal-naive baseline comparison, no MAPE by day / week / month horizon, no uncertainty
   bands and no alert flags.
5. **No callable interfaces.** `forecast.predict`, `attrition.score`, `attrition.rescore` and
   `voice.extract` do not exist (all AttributeError), so a demo cannot call real model outputs.
6. **SHAP, driver categories and intervention table are MISSING.** The "why is this person
   at risk" story has no implementation. `shap` is installed but never imported.
7. **Models are not traceable to their data.** No data hash or feature list is saved next to
   each model. The data itself IS reproducible (verified: same seed gives byte-identical files),
   but a model file cannot prove which data it was trained on.
8. **Attrition label horizon mismatch:** 8 weeks used vs 90 days specified. Censoring is
   handled for 8 weeks (rows whose window passes the horizon are dropped), not for 90 days.
9. **Unverified calendar, and a horizon into 2029.** The test period is 2028-06 to 2029-10,
   and festival dates for 2026-2029 are unverified approximations. A judge may find "2029 data"
   odd; it is synthetic, extended to get enough test exits.
10. **Smaller gaps:**
    - voice entirely MISSING;
    - hero employees MISSING;
    - `joblib` imported directly but not in `requirements.txt`;
    - `shap` and `scipy` unused;
    - stale `validate` description in ml/CLAUDE.md.

Checked and NOT a problem: no feature reads `data/internal/` (grep: only docstrings mention
it); no random split, shuffle or KFold anywhere (grep: none); no protected-attribute features;
rolling features and contract-end features use only past data (unit-tested); data is
reproducible (generate + validate left `git status` clean).

### Recommended next tasks (in order)

1. Frame the attrition result honestly in-product: show "contract ending" separately from
   "resignation risk", and add the rules baseline to `evaluate.py`.
2. Make config honest: use `label_horizon_days` (or delete it) and remove or wire up
   `target_annual_attrition`.
3. Build `attrition.score(week_start, employee_ids=None)` loading the committed artifacts.
4. Build the occupancy forecast: seasonal-naive baseline, MAPE by horizon, bands, alerts,
   booking_pace_7d only for horizons of 7 days or less.
5. Add SHAP to the attrition model and map features to the 7 driver categories plus an
   intervention table.
6. Build `attrition.rescore(employee_id, feature_overrides)` on top of `score`.
7. Package each model with feature_list.json, a data hash and a short model card; add a
   standalone `eval` command.
8. Decide on hero employees (scripted, excluded from training) if the demo needs them.
9. Voice bake-off (WER and extraction accuracy), glossary, cached demo result.
10. Housekeeping: add `joblib` to requirements.txt, drop or justify `shap` and `scipy`, fix the
    stale `validate` line.

**Verdict: NO.** The data and three offline models are solid and reproducible, but there is no
occupancy forecast, no callable scoring or rescore interface, no drivers or SHAP, and no voice,
so a demo cannot yet show real model outputs end to end.

---

## Evidence by section

### A. Repo state

- `git status`: "On branch main. Your branch is up to date with 'origin/main'. nothing to
  commit, working tree clean". Ahead/behind origin: 0 / 0.
- `git branch -a`: main, origin/main only.
- `git log --oneline`, 13 commits:
  - 5798050 docs: model card
  - 83e5dba task7
  - 555aa68 task6
  - 9d11dbf cleanup
  - 915e687 reorg
  - 0682366 task5
  - a579baa task4c
  - e585b09 task4
  - 98af133 task3
  - 56511f4 task2c
  - dbe0ce0 task2b
  - 4f9ab7c task2
  - e6d3bb0 task1
- Untracked: none. Ignored only: `.venv/`, caches, `ml/data/internal/`,
  `ml/data/{features,pulse_features,workload_features}.csv`.
- **A2, CLAUDE.md vs reality.** The layout correctly marks forecast/, attrition/, voice/ and
  eval/ as empty, and status lines match the existing commits. Mismatches:
  - line 82 says `validate` runs "occupancy + staff" checks, but it runs 3 validators,
    including attrition;
  - CLAUDE.md does not say `label_horizon_days` and `target_annual_attrition` are unused (only
    MODEL_CARD.md does).

### B. Environment

- Python 3.13.9. `pip check`: "No broken requirements found".
- All of these import: numpy 2.5.3, pandas 3.0.6, scipy 1.18.1, sklearn 1.9.1, lightgbm 4.7.0,
  shap 0.52.0, pydantic 2.13.5, yaml 6.0.3, matplotlib 3.11.2, pytest 9.1.1, ruff 0.16.10
  (plus joblib 1.6.0).
- Used but not in requirements.txt: **joblib** (7 imports; only in requirements-lock.txt as a
  scikit-learn dependency).
- In requirements but unused: **shap**, **scipy**.

### C. Tests and lint

- `python run.py test`: **232 passed** in 34.78s, 0 failed, 0 skipped.
- `python run.py lint`: **All checks passed!**

### D. Data generator

**5. Files** (rows, columns):

Tracked:
- event_calendar.csv: 2,557. date, day_of_week, month, is_weekend, is_public_holiday,
  festival_name, is_festival, is_festival_window, is_char_dham, is_school_holiday
- weather_daily.csv: 2,557. date, temp_c, rain_day, heavy_rain, road_closure_flag
- occupancy_daily.csv: 2,557. date, occupancy_pct, rooms_sold, adr, room_revenue,
  booking_pace_7d
- employee.csv: 55. employee_id, department, role, is_department_head, manager_id, hire_date,
  contract_type, contract_end_date, monthly_pay, last_raise_date
- employee_v2.csv: 185. Same columns as employee.csv.
- employee_skill.csv: 99. employee_id, skill, level
- dept_week_load.csv and dept_week_load_dynamic.csv: 2,190 each. week_start, department,
  occupied_room_nights, required_hours, headcount, available_hours, load_ratio
- weekly_behaviour.csv: 20,051. employee_id, week_start, department, role, load_ratio,
  overtime_hours, pulse_score, leave_days, is_active
- exits.csv: 130. employee_id, exit_date, exit_reason, tenure_days_at_exit,
  replacement_employee_id
- contract_renewals.csv: 23. employee_id, renewal_date, new_contract_end_date

Ignored:
- internal/employee_latent.csv: 185. employee_id, overtime_propensity, baseline_pulse,
  baseline_task_score, latent_frustration
- features.csv: 19,486
- pulse_features.csv: 19,559
- workload_features.csv: 2,160

**6. Generate and validate**
- `python run.py generate`: exit 0. Staff sha256 47d2f11edcd7074f; weekly_behaviour
  a7f33c31018acf9d; exits 71ac7735c3e366f9.
- `python run.py validate`: exit 0, **38/38 PASS**:
  - occupancy 11/11: May-Jun 0.838, Feb 0.326, MAPE 16.66%;
  - staff 16/16: median load 0.900, May-Jun 1.147, Feb 0.626;
  - attrition 11/11: 33.8%, pulse May-Jun 3.392 < Feb 3.858.
- `git status` afterwards: empty. No tracked file changed; data is reproducible.

**7. Inventory**

| Item | Status |
|---|---|
| occupancy_daily, weather_daily, event_calendar | exist |
| employee, employee_skill, dept_week_load, employee_latent | exist |
| Weekly employee features | overtime, leave and pulse exist (weekly_behaviour.csv). **Weekend off: MISSING. Weekly task score: MISSING** (only a latent baseline_task_score) |
| Leave table | no separate table; leave_days is a column of weekly_behaviour |
| Pulse responses | no survey-response table; weekly pulse_score only |
| Attrition labels | exits.csv; label exits_within_8_weeks in features.csv |
| Hero employees | **MISSING** (grep for Sunita, Rajesh, Meena, Arun, Deepak, "hero": no match) |
| Exits and replacement hires | exist (exits.csv, employee_v2.csv) |
| Data dictionary | PARTIAL: "Data files" section of ml/CLAUDE.md; no standalone file |
| Dataset version hash | PARTIAL: hashes are printed by `generate` and checked by `validate`, but not stored in a file |

### E. Attrition data quality

**8.**
- Annual attrition **33.8%** vs the 0.40 target. The 0.40 in config is unused; the hazard was
  tuned for about 30%.
- Driver definition (the audit's own; no driver taxonomy exists in the repo). A driver counts
  if, in the last active week before exit, any of these hold:
  - contract end (exit_reason seasonal_end);
  - tenure under 365 days;
  - 4-week mean pulse under 3.26 (the 25th percentile of active weeks);
  - 4-week mean overtime of 4 h or more;
  - 4-week mean department load above 1.1.
- Exits with **no visible driver: 30/130 = 23.1%** (resignations only: 34.5%). Target 10-20%:
  slightly above.
- Driver frequency among exits: short tenure 60, low pulse 54, contract end 43, high overtime
  40, high load 32.
- High-driver employee-weeks (2 or more behavioural drivers): 4,452; **92.4% had no exit in
  the next 8 weeks**. At employee level, 155 high-driver employees, of whom **29.0% never
  left**. Target 15% or more: met, so drivers are far from deterministic.

**9.** Label `exits_within_8_weeks` = exit in [week_start + 7d, week_start + 63d). Horizon is
**8 weeks, not 90 days**. Censoring: rows whose 8-week window passes the end of data are
dropped. The last 90 days are not specifically excluded, since the horizon is 8 weeks.

**10.** Hero employees: **MISSING**. No scripted signals exist, so there is nothing to exclude.

**11.** Overtime-only rule, test split:
- score = overtime_hours: ROC-AUC 0.522, PR-AUC 0.043 (base 0.044);
- score = 4-week overtime mean: ROC-AUC 0.512;
- rule "4-week overtime above 0": precision 0.049, recall 0.474.

On all rows: ROC-AUC 0.552. So the data is **too hard for a single signal (near random)**, not
too easy. For reference, the generator's true probabilities reach test ROC-AUC 0.874 and
PR-AUC 0.407.

### F. Forecast model

**12.** `ml/forecast/` holds only `__init__.py`: **MISSING**. No models, time split, baseline,
MAPE by horizon, uncertainty band or alerts. The only related item is a validation check:
seasonal-naive MAPE on the final year = 16.66%. (Task 7 forecasts department load_ratio, not
occupancy.)

**13.** `booking_pace_7d` is not used by any feature or model code (grep: no match in
ml/features or ml/models), so there is no leakage from it. No target leakage was found in the
workload or pulse features. next_week_is_festival comes from a calendar published in advance.

### G. Attrition model

**14.** `ml/attrition/` holds only `__init__.py`; the attrition code is in `ml/features/` and
`ml/models/`.
- Models tried: logistic regression and LightGBM.
- Time split: 60/20/20 by week with 8-week gaps (train 2023-01-02 to 2026-12-07, val
  2027-02-08 to 2028-04-17, test 2028-06-19 to 2029-10-29).
- Rules baseline: **MISSING**.
- Calibration: by-decile table printed and saved.
- Precision / recall at the fixed 0.5 threshold, test: logreg 0.507 / 0.210; LightGBM
  0.524 / 0.386. The threshold is not tuned.
- SHAP: **MISSING**. 7 driver categories: **MISSING**. Intervention table: **MISSING**.
  rescore: **MISSING**.

**15.** Leakage audit.
- Attrition features: department, role, contract_type, is_department_head, tenure_days,
  monthly_pay, load_ratio, overtime_hours, leave_days, pulse_score, pulse_roll4_mean,
  overtime_roll4_mean, pulse_trend_4w, weeks_since_last_raise, days_until_contract_end.
- Label: exits_within_8_weeks.
- None reads `data/internal/employee_latent.csv`: grep finds only docstrings saying it is
  never read.
- No future data: rolling features use the employee's past rows (test
  `test_rolling_uses_only_past`); contract end uses only renewals dated on or before week_start
  (test `test_days_until_contract_end_ignores_future_renewals`).
- No protected attributes: token check over all three feature lists found none.
- Split is by time: no train_test_split, shuffle or KFold anywhere (grep: none).

### H. Voice

**16.** `ml/voice/` holds only `__init__.py`. Code, clips, bake-off report (WER, extraction
accuracy), glossary and cached demo result are all **MISSING**.

### I. Packaging and interfaces

**17.** `ml/artifacts/` holds baseline_logreg.joblib (4.9 KB), tree_model.joblib (106 KB),
pulse_model.joblib (301 KB) and workload_model.joblib (530 KB). Metrics are in
`ml/docs/metrics/*.json`; their keys are model, seed, val, test, plus coefficients or
feature_importance_gain. They hold **no data hash**. Per-model model_card.md: **MISSING** (one
consolidated MODEL_CARD.md). feature_list.json: **MISSING**. Eval command: **no standalone
one**; evaluation runs inside `train`, `train-pulse` and `train-workload`.

**18.** Each requested call was made with a tiny example:

| Call | Result |
|---|---|
| `ml.forecast.predict('2029-01-01', '2029-01-07')` | AttributeError: module 'ml.forecast' has no attribute 'predict' |
| `ml.attrition.score('2029-01-01', employee_ids=None)` | AttributeError: module 'ml.attrition' has no attribute 'score' |
| `ml.attrition.rescore('E001', {'overtime_hours': 0})` | AttributeError: module 'ml.attrition' has no attribute 'rescore' |
| `ml.voice.extract('clip.wav')` | AttributeError: module 'ml.voice' has no attribute 'extract' |

All four are **MISSING**.
