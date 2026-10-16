# Char Dham crowd forecast on REAL data: results

**Question:** how many pilgrims will Kedarnath, Badrinath, Gangotri and Yamunotri see on each of
the next 14 days, and is that quiet, normal, busy or very busy?

**Data:** real official figures (UTDB, SEOC via SDC Foundation, news reports of official
counts) and real weather (Open-Meteo, CC BY 4.0). Sources, licences and cleaning rules are in
[DATA_CARD.md](DATA_CARD.md). Run on 2026-10-15; retrained on 2026-10-16 with XGBoost on
the GPU (training and evaluation on CUDA only, NVIDIA RTX 4050; serving stays pure Python).

## Where the target is real and where it is estimated

| Shrines | Target | Real or estimated |
|---|---|---|
| Kedarnath, Badrinath, Gangotri, Yamunotri, seasons 2022-2026 | Daily pilgrims | Totals between two reported figures are REAL (9-17 per shrine-season; weekly in May-Aug 2024). Day values inside a reporting interval are ESTIMATED by spreading the total evenly, except 115 officially reported single days and 11 nil days. |
| Every other destination in the portal | none | Only annual UTDB totals exist. No daily model was built and no curve was invented. These places keep the portal's existing estimate, which is labelled sample data. |

## Set-up

- **When a forecast is made.** Each forecast is made right after a real figure is published
  and covers the next 1-14 days. Lagged counts use only days up to that point. Each day value
  depends only on figures published up to that day, so later figures cannot leak in.
- **Features:**
  - calendar: day of season, days to closing, day of week, gazetted holidays, long weekends,
    festivals, share of Delhi / UP / Haryana schools on vacation;
  - weather on the day and the day before (rain, snow, maximum temperature, heavy rain of
    35 mm or more as a road-closure proxy), used only for the first 7 days of a forecast;
  - lagged counts (last day, 7-day mean, trend, this season against last season);
  - last season's level at the same day of the season.
- **Models compared:**
  - seasonal-naive: last season, same day of the season;
  - moving average: mean of the last 7 days;
  - XGBoost (point forecast plus 10% and 90% quantile models, `reg:quantileerror`), trained
    and evaluated on the GPU (RTX 4050). It replaced the earlier LightGBM models when all model
    training moved to the GPU.
- **How the 80% range is set.** The quantile range is widened by split conformal prediction:
  a twin model trained on seasons up to T-2 is scored on season T-1.
- **Splits are by season only, never random.**
  - Hyperparameters and objective: a 16-setting grid with L1 or L2 loss, chosen on 2024 only
    (the same grid as before). The chosen setting is L1, 15 leaves, minimum leaf weight 20,
    600 rounds. A wider grid was tried once (31 leaves, leaf weight 5, 1,000 rounds); it won on
    2024 but was not kept, because it was added after the test results had been seen; the
    original pre-set grid is the protocol.
  - Test 1: trained on 2022-2024, tested on **2025**, the latest complete season.
  - Test 2: trained on 2022-2025, tested on **2026 to date** (19 Apr - 7 Oct). This is the
    model the portal uses.

## Results

Daily error in pilgrims per day per shrine. MAPE is computed only on days with at least 100
pilgrims. Test 1 is 2025; test 2 is 2026 to 7 Oct.

| Model | MAE 2025 | MAPE 2025 | MAE 2026 | MAPE 2026 |
|---|---|---|---|---|
| Seasonal-naive (last season, same day of season) | 3,254 | 70% | 2,881 | 42% |
| Moving average (last 7 days) | 3,902 | 113% | 4,867 | 76% |
| **XGBoost on the GPU (deployed)** | 3,294 | 98% | **2,594** | 38% |

| Other checks | 2025 | 2026 |
|---|---|---|
| Band accuracy, model against seasonal-naive (4 bands) | 41% against 54% | 63% against 58% |
| 80% range coverage (target 80%) | 70% | 84% |
| Mean width of the 80% range | 8,014 | 9,997 |
| Error on REAL interval totals (forecast made at a report, summed to the next report, intervals of 14 days or less): model / seasonal-naive / moving average | 77% / 58% / 39% (38 intervals) | 26% / 31% / 38% (20 intervals) |

**In plain words**

1. **Against seasonal-naive the model loses 1% in 2025 and wins 10% in 2026 on daily error.**
   "Same day as last season" is a strong rule for a pilgrimage that follows the same calendar
   every year. The model clearly beats the moving average, by 16% in 2025 and 47% in 2026.
2. **Not consistently better.** On the real interval totals the model was worse than both
   baselines in 2025 and the best in 2026. Its band was right less often than seasonal-naive in
   2025 and more often in 2026. With 3-4 training seasons, one season's luck moves the ranking.
   Treat the model as being about as good as last season's pattern, plus a range.
3. **The 80% range is only roughly honest:** it held the actual value 70% of the time in 2025
   (too narrow) and 84% in 2026.
4. **Feature groups (ablations: drop one group and retrain):**

   | Group dropped | MAE 2025 | MAE 2026 |
   |---|---|---|
   | none (full model) | 3,294 | 2,594 |
   | weather | 3,372 | 2,619 |
   | school vacations | 3,367 | 2,661 |
   | holidays and festivals | 3,328 | 2,662 |
   | lagged counts | 3,070 | 3,086 |

   Weather, school vacations and holidays each help a little in both seasons (1-3%). Lagged
   counts help a lot in 2026 but hurt in 2025. Holidays make no difference, which is expected: day values inside
   an interval are spread evenly, so a holiday's own effect cannot show in the target. Weather
   was a *perfect* forecast in this test, because the archive was used; live forecasts will do
   worse.
5. **GPU.** Training and evaluation now run only on the GPU (ml/gpu.py refuses without
   CUDA). The data is a few thousand rows, so the GPU brings no speed gain here. The XGBoost
   trees are exported to plain JSON, so the portal still predicts in pure Python.

## Where the model is worst (failure analysis)

| Period | Model MAE 2025 | Seasonal-naive MAE 2025 | Model MAE 2026 | Seasonal-naive MAE 2026 |
|---|---|---|---|---|
| Opening week (days 0-6) | 2,184 | 3,349 | **4,507** | 3,211 |
| Days 7-29 | 3,067 | 3,470 | 3,508 | 3,258 |
| Days 30-89 | 3,341 | 3,415 | 2,580 | 3,899 |
| Day 90 onward | 3,592 | 2,873 | 1,482 | 1,454 |
| Heavy-rain days (35 mm or more, day or day before) | 2,648 (n = 3) | 2,500 | 1,053 (n = 9) | 1,645 |

- **Opening days are the biggest misses.** The 2026 opening at Kedarnath averaged about 29,600
  a day for the first week; the model said about 12,500-13,000. A forecast made before opening
  has no lags, and 2026 opened earlier (22 April) and bigger than any training season. The
  Badrinath opening day in 2025 (23,000 reported; model 10,133) is the same failure. The
  opening-week rush needs registration counts, which are published before the season, as an
  input.
- **Landslide and closure days:**
  - There are no officially nil days in either test season.
  - The 11 nil days in 2024 (Kedarnath, after the 31 July cloudburst) are in training.
  - Suspensions in 2025 (Dharali, 5 Aug) and 2026 (20 and 28-30 Jul, 26-27 Sep) fall inside long
    intervals without reports, so the target cannot show them.
  - The model cannot predict a closure; the guardrails and the weather warning on the page
    must cover that.
- **The days just before closing** (2025) were worse than seasonal-naive (3,724 against
  3,308), as were days 90 onward. The 2026 closing period
  is not in the test yet.

## Guardrails (built into `predict.predict`; tested in `ml/tests/test_crowd_real.py` and `portal/tests/test_crowd_model.py`)

1. **Input validation.** These are rejected with an error:
   - an unknown destination;
   - an invalid date;
   - a forecast outside 1-14 days ahead;
   - recent counts that are not numbers, or are outside 0 to 2 times the cap.

   Weather values that are not three numbers, or are outside physical ranges, are ignored, and
   a note says so.
2. **Closed season.** A day outside the announced opening and closing dates returns "closed"
   with 0 pilgrims. A year with no announced dates returns `unknown_season`, and the portal
   then uses its old estimate.
3. **Missing inputs.** When no recent counts are available, or when the day is more than 14
   days after the last official count, the forecast falls back to last season's level. It uses
   the same day of the season, or, if last season was shorter, the same number of days before
   closing. Confidence is then "low".
4. **Drift.** A non-calendar feature more than 25% of its training range outside the 0.5-99.5%
   training range triggers the same fallback, with confidence "low" and the drifting features
   named.
5. **Clipping.** Every number is clipped to 0..cap, where the cap is 1.25 times the highest
   single day reported: Kedarnath 48,400, Badrinath 35,100, Gangotri 23,700, Yamunotri 22,600.
   The range is ordered so that low <= point <= high.
6. **Width.**
   - If the range width is 0.6 times the forecast or less, confidence is "high".
   - If it is 1.2 times the forecast or less, confidence is "medium".
   - If it is wider, confidence is "low".
   - If it is wider than 3 times the forecast (with a floor of 200), the model abstains and no
     band is shown.

   These thresholds are ASSUMED. In mid-October the ranges are wide relative to the low
   counts, so the portal shows "Low confidence (rough guide)".

**Bands.** Per shrine, the bands use the 25th, 60th and 85th percentiles of in-season daily
counts over every real season, mapped to the portal's 40 / 65 / 85 index cut points: quiet,
normal, busy, very busy. Very busy starts at:
- Kedarnath: 19,780;
- Badrinath: 16,841;
- Gangotri: 9,471;
- Yamunotri: 7,948.

The cut points are ASSUMED. "Very busy" means the busiest 15% of days at that shrine, not a
safety limit.

## Portal

The shrine pages and the officials' "How busy" tab now use this model for the four shrines.
The model's predict code is copied byte-for-byte into the portal, so the portal needs no
numpy, XGBoost or GPU. Each day carries:
- the expected pilgrims;
- the 80% range;
- a confidence label;
- its basis: model, last season's level, official count, or closed season.

When a day in the next 14 is very busy, the page and the officials' tab show it in plain
words, for example "Very busy expected Sat 17 Oct · usual for opening weeks". Every other
destination keeps the old estimate, labelled "low" confidence and sample data.

## Limits

- **Estimated day values.** Most day values are even shares of real interval totals. Day-level
  accuracy is therefore measured against partly estimated values; only the interval-total
  check is fully real.
- **Thin history.** Only 4-5 seasons; the 2022 and 2023 data is mostly Amar Ujala reports of
  official figures.
- **News dates.** News figures are dated to plus or minus one day. Several official sources
  contradict each other (see DATA_CARD.md).
- **2026 closing dates** are expected or provisional until they are announced on 20 Oct 2026.
- **Weather.** The tests used a perfect weather forecast, and the grid weather is not the
  temple's microclimate.
- **Rules chosen after looking at results.** Two cleaning rules were added after the first
  results were seen:
  - an exact multiple of 1,000 at or above 100,000 is treated as rounded;
  - a cumulative figure within 3 days of the previous one is dropped.

  Both are motivated by data quality; with them, the 2025 model error (earlier LightGBM model)
  moved from 3,360 to 3,140. The hyperparameter grid was always chosen on 2024 only.
- **Stale data.** The bundle's last official count is 7 Oct 2026. From about 22 Oct the portal
  falls back to last season's level until new counts are added.

## Retrain

```powershell
# from the repo root
.venv\Scripts\python.exe -m ml.realdata.crowd.fetch            # raw PDFs + weather archive (gitignored)
# add new official figures to ml\data\real\crowd\checkpoints.csv (source URL per row, use=1)
# and announced dates to season_dates.csv
.venv\Scripts\python.exe -m ml.realdata.crowd.train            # GPU only, ~2 minutes; writes ml\artifacts\crowd_forecast\real_v1
                                                                # and copies bundle + predict code to the portal
.venv\Scripts\python.exe -m pytest -q ml\tests\test_crowd_real.py
```

To use more data, extend `WEATHER_END` in `sources.py` and re-fetch. The portal picks up
`portal/hoi_portal/models/crowd_real_v1.json` at start-up.

**Possible next steps:**
- the SDC Foundation 2025 report (weekly data, not found online);
- registration counts as an opening-week input;
- Chronos-2, a time-series model that accepts covariates, as a zero-shot baseline (needs a new
  dependency; not installed).
