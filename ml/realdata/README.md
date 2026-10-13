# ml/realdata: our models on REAL public data (GPU)

Everything else in `ml/` runs on SYNTHETIC data. This folder is the exception: it re-tests our
forecasting and attrition approaches on **public datasets**, and every result here says which
dataset it came from and whether that dataset is real, fictional or of unverified origin.
It does not touch the synthetic pipeline, its artifacts (`ml/artifacts/*/v1`) or the API.

Plain-language results for judges: [docs/REAL_DATA_RESULTS.md](../../docs/REAL_DATA_RESULTS.md).

## Reproduce

```powershell
cd ml
python run.py realdata              # ~5 min on an RTX 4050 laptop GPU (TimesFM included)
python run.py realdata --no-timesfm # ~2 min, no torch / TimesFM needed
python run.py realdata --cpu        # force CPU (no fine-tune, no GPU evidence)
python -m pytest tests/test_realdata.py -q   # 20 tests, no download, no GPU
```

The command downloads each dataset (no Kaggle key), checks its SHA-256, and writes:

| Output | What |
|---|---|
| `ml/artifacts/occupancy_forecast/real_v1/` | `metrics.json` (every model x hotel x horizon, split, TimesFM fine-tune history), `results_table.md`, `test_predictions.csv`, `tree_models.joblib`, `feature_list.json`, `daily_room_nights.csv` |
| `ml/artifacts/attrition/real_v1/` | `metrics.json` (per dataset, per scorer: ROC-AUC, PR-AUC, Brier, ECE, calibration bins), `dataset_hash.json` |
| `ml/artifacts/realdata_gpu/real_v1/` | `gpu_evidence.json` (device, nvidia-smi before / after, CPU vs GPU timings), `run_log.txt` |
| `ml/docs/plots/realdata_forecast.png` | test period, 7 days ahead, both hotels |
| `ml/data/realdata/raw/`, `ml/data/realdata/timesfm_finetuned/` | downloads and the fine-tuned TimesFM layers (276 MB); both gitignored and rebuilt by the command |

Optional dependencies (torch CUDA, xgboost, timesfm): [requirements-gpu.txt](requirements-gpu.txt).
Seeded (42; attrition CV seeds 42-44). Re-running gives the same tree-model and baseline
numbers; GPU floating point can move TimesFM numbers in the last digit.

## Datasets

| Dataset | Real? | Source (direct download) | Licence | Size | Dates | SHA-256 |
|---|---|---|---|---|---|---|
| Hotel Booking Demand (Antonio, Almeida & Nunes 2019, *Data in Brief* 22:41-49) | **REAL** bookings, 2 Portuguese hotels (a city hotel in Lisbon, a resort in the Algarve) | `raw.githubusercontent.com/rfordatascience/tidytuesday/master/data/2020/2020-02-11/hotels.csv` (TidyTuesday mirror) | CC BY 4.0 | 119,390 bookings x 32 columns (City 79,330, Resort 40,060) | arrivals 2015-07-01 .. 2017-08-31 | `7c2ae42a...b1fc06` |
| IBM HR Analytics Employee Attrition & Performance | **FICTIONAL**: created by IBM data scientists | `raw.githubusercontent.com/IBM/employee-attrition-aif360/master/data/emp_attrition.csv` | ODbL 1.0 / DbCL 1.0 (per the IBM repo README) | 1,470 employees x 35 columns, 237 leavers | none (one snapshot) | `a5c31e38...be7659` |
| Employee Turnover (Edward Babushkin, 2017) | **REAL according to its author**; country, companies and collection method are NOT documented | `kaggle.com/api/v1/datasets/download/davinwijaya/employee-turnover` (public download endpoint, no key needed) | CC BY-NC-SA 4.0 on Kaggle: **non-commercial**, so evaluation only, never shipped in the product | 1,129 people x 16 columns, 571 quits | none (tenure only) | `50986006...e65ceb` |

Full hashes are in `sources.py`. No real hotel-staff turnover dataset is public: neither
attrition dataset is from a hotel (the turnover data has 11 HoReCa rows out of 1,129).

### Protected attributes dropped (before any modelling)

- IBM: `Age`, `Gender`, `MaritalStatus` (plus ids / constants `EmployeeNumber`,
  `EmployeeCount`, `Over18`, `StandardHours`).
- Turnover: `gender`, `age`, `head_gender` (supervisor's gender) and the five personality-test
  scores (`extraversion`, `independ`, `selfcontrol`, `anxiety`, `novator`). These are
  psychometric data that a hotel would not and should not hold.
- Kept although borderline: IBM `RelationshipSatisfaction` (a workplace survey item),
  `DistanceFromHome`, `Education`, `EducationField`. Hotels deciding what to collect should
  question these too.
- The hotel booking data contains guest country, adults / children / babies and similar. We
  use none of it: only dates, stay lengths, lead time and cancellation status, aggregated to
  nightly counts.

## Occupancy method

- **Room-nights.** One booking = one room (the file has no room count). A non-cancelled
  booking occupies a room on each night from arrival to arrival + weekend nights + week
  nights - 1. 715 zero-night (day-use) bookings occupy no night.
- **No room count is published**, so we forecast room-nights. The *capacity proxy* is the
  highest nightly count in the TRAINING window (City 226, Resort 187), used to scale the model
  target and to express errors as a share of the hotel.
- **Edges.** Guests who arrived before July 2015 are not in the file, so the series start late:
  Resort 2015-08-01; City 2015-09-01, because City July-August 2015 looks incomplete (2 of 3 July
  bookings are cancellations; nights are about half of September's). The series end 2017-08-31.
- **On the books (booking pace).** For night d at origin t = d - h: bookings created by t
  (arrival - lead_time) covering d and not cancelled by t (cancelled bookings count until their
  `reservation_status_date`). This is what a booking system shows at t, including bookings that
  later cancel, so the cancellation outcome does not leak. Limit: arrival dates are final, so a
  booking that was moved shows at its final date.
- **Holidays.** The `holidays` package is not installed, so `hotels.py` holds a small table of
  Portuguese national holidays 2015-2017 (Corpus Christi, 5 Oct, 1 Nov and 1 Dec restored from
  2016), plus Lisbon's 13 June for the City Hotel.
- **Split by target date, never random:** train to 2016-10-31 | 30-day gap | validation
  2016-12-01..2017-01-31 | 28-day gap | **test 2017-03-01..2017-08-31** (184 days per hotel).
  Learned models are fitted on train only. Model choice per horizon uses VALIDATION MAE, never
  test. Inputs at test time may use nights observed up to the origin, as a live system would.
- **Models** (direct, one per horizon 1 / 7 / 30, both hotels pooled with a hotel flag):
  `snaive_week` (same weekday, latest observed week), `snaive_year` (same weekday 52 weeks
  earlier), `pickup_naive` (on the books now + last year's pickup at the same horizon, a
  standard hotel revenue-management baseline), `lgbm_calendar_cpu` (our existing ml/forecast
  approach adapted: calendar + holidays + history), `lgbm_pace_cpu` and `xgb_pace_gpu`
  (+ on-the-books features), `timesfm_zero_shot`, `timesfm_fine_tuned`.
- **Bands (80% nominal):** split-conformal on validation residuals for baselines and trees;
  TimesFM's own 10% / 90% quantiles.
- **TimesFM fine-tune (GPU):** last 4 of 20 transformer layers + both output heads trainable
  (72.1M of 231.3M parameters), AdamW lr 1e-5, batch 16, 8 epochs, pinball loss on the next
  30 nights, 699 training windows (targets <= 2016-10-31), 66 validation windows; best
  validation epoch kept. A differentiable copy of the library's decode path is checked against
  the library on every run (max difference 1e-4 room-nights).

## Results (test Mar-Aug 2017, REAL data)

MAE in room-nights; "typical" = median absolute error. Full table: `results_table.md`.

| Horizon | Hotel | Same weekday last week | Calendar LightGBM (our approach) | TimesFM zero-shot | TimesFM fine-tuned | **Best (chosen on validation)** |
|---|---|---|---|---|---|---|
| 1 day | City | 10.9 (5.3%) | 8.5 (4.1%) | 7.3 (3.6%) | 7.2 (3.6%) | **1.9 (0.9%)** XGBoost GPU + pace |
| 1 day | Resort | 10.4 (6.4%) | 7.2 (4.3%) | 7.1 (4.3%) | 7.3 (4.4%) | **1.9 (1.1%)** XGBoost GPU + pace |
| 7 days | City | 10.9 (5.3%) | 8.7 (4.2%) | 7.9 (3.9%) | 8.2 (4.0%) | **5.3 (2.5%)** XGBoost GPU + pace |
| 7 days | Resort | 10.4 (6.4%) | 8.3 (5.0%) | 8.7 (5.3%) | 9.2 (5.6%) | **3.9 (2.4%)** XGBoost GPU + pace |
| 30 days | City | 18.5 (8.9%) | 11.1 (5.2%) | 9.1 (4.5%) | 9.9 (4.8%) | **7.2 (3.4%)** LightGBM + pace |
| 30 days | Resort | 16.1 (9.6%) | 8.3 (5.0%) | 9.3 (5.6%) | 9.6 (5.8%) | **6.8 (4.1%)** LightGBM + pace |

(MAE, with MAPE in brackets.) Same weekday last year: City 15.4 (7.3%), Resort 11.3 (6.8%) at
every horizon. 80% band coverage of the chosen models: 89-96%, so the bands are too wide.
They were calibrated on December-January, a more volatile period than the summer test.

## Attrition results (repeated 5-fold CV, out-of-fold, mean of 3 seeds)

| Dataset | Rows / leavers | Rules | Logistic | LightGBM (CPU) | XGBoost (GPU) |
|---|---|---|---|---|---|
| IBM HR (FICTIONAL) | 1,470 / 237 (16.1%) | ROC 0.653, PR 0.247 | **ROC 0.828, PR 0.610** | 0.813 / 0.579 | 0.821 / 0.602 |
| Babushkin turnover (real, unverified origin), quit within 12 months | 982 / 150 (15.3%) | ROC 0.552, PR 0.174 | 0.604 / 0.212 | **ROC 0.659, PR 0.322** | 0.651 / 0.289 |

Calibration (Platt inside each training fold): ECE 0.02-0.04 for every model. Rules are fixed,
ASSUMED conditions chosen before seeing results: IBM, the count of OverTime = Yes,
JobSatisfaction <= 2 and WorkLifeBalance <= 2; turnover, the count of grey (unofficial) wage
and no probation coach. Neither dataset has dates, so cross-validation replaces our usual time
split. Turnover: people still employed after less than 12 months (147) are excluded because
their outcome is unknown.

## Limits

- Portuguese city / resort hotels with 190-230 rooms are not Uttarakhand hill hotels with
  10-40 rooms: different guests, seasons (no monsoon, no Char Dham), booking channels and
  scale. In a 24-room hotel one booking is 4% of capacity, so errors in percent will be larger.
- One booking = one room is an assumption. The capacity proxy is a lower bound on the real room
  count. The on-the-books feature cannot see date changes.
- One test window (6 months, one season) and one seed for TimesFM fine-tuning.
- Attrition: IBM is fictional; the turnover set's origin is undocumented, it is mostly HR
  professionals (757 of 1,129) and non-commercial. Neither is a hotel. Neither has time
  stamps, so leakage through time cannot be ruled out the way our synthetic backtests rule it
  out.
