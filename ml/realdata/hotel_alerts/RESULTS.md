# Hotel alerts and prediction checks: results

**Run on:** 2026-10-15, RTX 4050 laptop GPU (XGBoost only; the deployed models run on the CPU).
**Reproduce:** `cd ml; python run.py train-cancellation` (about 1 minute), then
`python run.py guard-reference` and `python run.py backtest-monitor [--hotel himsagar]`.

Three things were built:

1. a booking cancellation model trained and tested on **REAL** public bookings;
2. a hotel alerts engine in the backend (`GET /alerts`);
3. prediction checks (guardrails) on every model the backend serves.

The cancellation numbers below come from real data. Everything about the HOI demo hotel
(forecast, shift plan, staff, alerts) is **SYNTHETIC**.

## 1. Booking cancellation risk (REAL data)

**Data.** *Hotel Booking Demand* (Antonio, Almeida & Nunes 2019, CC BY 4.0): 119,390 real
bookings from a Lisbon city hotel and an Algarve resort, arrivals July 2015 to August 2017.
Source, hash, access date and excluded columns: [DATA_CARD.md](DATA_CARD.md).

**Only what is known at the time.** Each booking becomes several snapshots. The first is the
moment it was booked. The others are 1, 2, 3, 5, 7, 10, 14, 21, 30, 45, 60 and 90 days before
arrival, taken only while the booking still exists. The question is always: will it still be
cancelled, or will the guest not show? Columns filled in later were removed: status, status
date, assigned room, parking spaces, number of changes and country. Party and family
composition are not used.

**Fair test, split by arrival date** (the same windows as our real-data forecast test). The
model learned from arrivals up to October 2016. The choice between models was made on
December 2016 to January 2017. It was then tested once on **March to August 2017**, which no
model had seen. Totals: 479,722 training snapshots, 43,531 validation and 229,620 test (32,829
at the moment of booking).

**Results at the moment of booking (test, both hotels; 40% of these bookings were cancelled):**

| Method | ROC-AUC | PR-AUC | Brier (lower is better) | Calibration error (ECE) |
|---|---|---|---|---|
| Base rate: the hotel's past cancel rate for that lead time | 0.638 | 0.494 | 0.234 | 0.086 |
| Logistic regression | 0.795 | 0.769 | 0.173 | 0.043 |
| **LightGBM (deployed; chosen on validation)** | **0.820** | **0.786** | **0.168** | 0.057 |
| XGBoost on the GPU (comparison only) | 0.820 | 0.786 | 0.168 | 0.062 |

In plain words, given one booking that will be cancelled and one that will not, the model
ranks the cancelling one higher 82% of the time. The base rate does this 64% of the time. By
hotel: city 0.826, resort 0.806 (base rate 0.621 and 0.641).

**Compared with other honest work.** Public work that also splits by date and drops the
post-booking columns reports ROC-AUC of about 0.81 to 0.84. We were pointed to two examples and
have not re-run either: a Hugging Face model card (AAUBS/hotel-cancellation-model, 0.81) and a
GitHub LightGBM project with a temporal split (0.84). Our 0.82 sits inside that range. Claims of
0.92 or more on this file come from random splits or leaky columns: parking spaces, assigned
room, country or reservation status. We checked that none of those columns can reach our model.
A test confirms that changing them leaves the model input unchanged.

**Calibration (test, at booking, LightGBM).** Predicted vs actual share cancelled, per bin
(number of bookings):

| Predicted | 0.0-0.1 | 0.1-0.2 | 0.2-0.3 | 0.3-0.4 | 0.4-0.5 | 0.5-0.6 | 0.6-0.7 | 0.7-0.8 | 0.9-1.0 |
|---|---|---|---|---|---|---|---|---|---|
| Mean predicted | 0.065 | 0.148 | 0.243 | 0.331 | 0.445 | 0.555 | 0.669 | 0.715 | 0.988 |
| Actually cancelled | 0.074 | 0.199 | 0.356 | 0.453 | 0.505 | 0.532 | 0.642 | 0.677 | 1.000 |
| Bookings | 5,858 | 6,560 | 8,524 | 2,051 | 636 | 725 | 2,697 | 2,399 | 3,376 |

From 0.1 to 0.4 the model **under-predicts by 5 to 12 points**: more bookings were cancelled in
spring and summer 2017 than in the training period. The AAUBS model card reports the same 2017
rise. Plot: `ml/docs/plots/realdata_cancellation_calibration.png`.

**Closer to arrival** (test, LightGBM vs base rate, ROC-AUC): 30 days 0.723 vs 0.528; 7 days
0.677 vs 0.510; 1 day 0.660 vs 0.494. Few bookings cancel this late: 12.6%, 4.0% and 1.9%. The
model still ranks them better than the base rate. Its Brier score is close to the base rate's
at 7 days (0.039 vs 0.039), so the gain there is in ranking, not in the probability values.

**Ablation.** Without average daily rate and special requests (both may hold their final value,
not the value at booking), ROC-AUC is 0.797 instead of 0.820 and Brier 0.175 instead of 0.168.
Most of the signal does not depend on them.

### Use 1: expected occupancy (rooms on the books that will really stay)

For each test night, we compare three things: the rooms on the books 1, 7, 14 or 30 days
ahead; how many of those bookings really stayed; and three estimates. Average error in rooms
per night, both hotels (about 175 to 190 rooms on the books):

| Days ahead | Rooms that later cancelled | No adjustment | Base-rate table | Model | Deployed (chosen on validation) | 80% range held the actual |
|---|---|---|---|---|---|---|
| 1 | 1.0 | **0.97** | 1.20 | 1.09 | base-rate table | 72% |
| 7 | 5.3 | 5.25 | **4.49** | 5.24 | base-rate table | 54% |
| 14 | 10.9 | 10.94 | 7.95 | **5.10** | base-rate table | 48% |
| 30 | 18.7 | 18.67 | 10.56 | **5.33** | base-rate table | 48% |

Resort hotel only (the closer match to a hill resort), model vs base-rate table: 7 days 1.99 vs
2.25, 14 days 2.64 vs 3.92, 30 days 3.56 vs 6.34.

What this means:

- Subtracting expected cancellations helps a lot from 2 weeks out: the error falls from 18.7
  to 5.3 rooms at 30 days. One day out, nothing beats "assume they all come": only about 1 room
  cancels.
- **The deployed rule picked the base-rate table at every horizon**, because it was better on
  the winter validation window. On the summer test the model was better at 14 and 30 days, and
  for the resort at 7 days too. We kept the rule we fixed in advance and did not switch after
  seeing the test. Retraining on a hotel's own year of bookings should settle this.
- **The 80% ranges are too narrow.** They held the actual only 48-72% of the time (resort
  64-85%), even after widening them on validation for group cancellations. The 2017 shift is
  larger than anything seen in validation. In the product, treat the range as a minimum
  spread, not a guarantee.
- First run, for transparency: with snapshots only at 1, 7, 14 and 30 days before arrival, the
  model over-predicted for the days in between. Validation showed this too. Its 7-day error was
  6.07 rooms against 5.25 for no adjustment. Denser snapshot days fixed the in-between days.
  This change was made after looking at both windows, so the test is no longer fully untouched
  for that design choice.

### Use 2: overbooking / no-show alert

An alert fires when expected cancellations are at least 5% of the rooms (12 city, 10 resort),
7 days ahead. In the test:

- City: 15 such nights. The model flags 160 of 184 nights (precision 9%) and the base-rate
  table 155 (precision 7%). **Not useful:** both over-flag.
- Resort: 7 such nights. The model flags 2, both right (precision 100%, recall 29%). The
  base-rate table flags none.

One day ahead, each hotel had one such night, and the model flagged exactly that night.
Conclusion: the alert is only a prompt to reconfirm guests and keep a waitlist. It is never a
reason to overbook. That is the action the HOI alert suggests.

## 2. Hotel alerts (backend `GET /alerts`, `POST /alerts`)

Each alert is one plain sentence with a severity (high / medium / low), the reason with
numbers, one suggested action and a link to the right page. Alerts are deduplicated: one alert
per rule and subject (for example, one staff-short alert per week, not one per team). A 12-hour
cooldown (`notify` false) stops the same alert from being raised again unless its severity
rises. Thresholds: `backend/config.yaml` `alerts` (all ASSUMED).

Demo hotel output (fictional Himsagar Ridge Resort, 24 rooms, SYNTHETIC week of 24 Dec 2029):

- **high** "Short of staff in 6 team(s) this week; kitchen is the biggest gap (27 h)." Why: the
  shift plan leaves 120 of the hours the forecast needs uncovered (kitchen 27 h, front desk
  26 h, restaurant 24 h, housekeeping 18 h short); worst kitchen shifts Sat 29 Dec morning 4 h,
  and so on. Action: ask for about 1 extra kitchen person on the short days, or move someone
  from a quieter team.
- **medium** "Busy Sat 29 Dec: about 21 of 24 rooms expected." Why: Saturday about 21 of 24
  rooms (likely 20-23), last Saturday 22; also busy Mon 24 Dec about 19, ... Action: check the
  shift plan and line up extra housekeeping and kitchen help early.
- No cancellation alert: with the base-rate table, about 0.6 of 20 booked rooms are expected
  to cancel 5 days out, below the 2-room trigger. The staff-leaving rule also stayed quiet: the
  high band did not grow this week.

The other rules, each tested on hand-made inputs: **weather** (live Open-Meteo forecast for
Mussoorie; IMD "rather heavy" 35.6 mm and "heavy" 64.5 mm per day, snow 5 / 15 cm ASSUMED),
**staff leaving** (more people in the high band than last week; ids only; "support, not a
warning") and **stock-out** (an item runs out before the supplier's lead time plus 2 days, at
the forecast occupancy; it needs the platform's inventory rows, which the dashboard sends).
Rules that cannot run are listed in `not_checked` with the reason, never silently skipped.

## 3. Prediction checks (guardrails) on every model

Shared code: `ml/guardrails.py`. Guarded entry points:
`ml/forecast/guarded.py`, `ml/attrition/guarded.py` (score and rescore),
`ml/models/workload_api.py` and `ml/realdata/hotel_alerts/api.py`. The backend calls only
these, so `/forecast`, `/attrition/score`, `/attrition/rescore`, `/workload/next-week` and
`/cancellation/score` all return `confidence` and `checks`.

| Check | How |
|---|---|
| Input schema and range | required inputs present; fixed limits (occupancy 0-1, pulse 1-5, load ratio 0-3, lead time 0-800 days, ...) |
| Output bounds | occupancy clipped to 0-1 (0 to the room count), probabilities to 0-1, load ratio to 0-3; low <= mean <= high |
| Drift | per row: more than 4 standard deviations from the training mean **and** beyond the training range (plus 25%), or a category never seen in training. Per batch: PSI on comparable features when the batch has at least 200 rows (smaller batches give a biased PSI of about (bins - 1) / n). Training reference: `reference_stats.json` next to each model |
| Fallback | missing, out-of-range or out-of-distribution rows use the baseline: seasonal naive (forecast, band widened by baseline / model error), training base rate (attrition), this week's load (workload), base-rate table (cancellation) |
| Confidence | high / medium / low from the range width (forecast), drift and the share of fallbacks; a calibrated probability without a range is capped at medium |
| Stale models | older than 365 days (ASSUMED) or undated: rejected, baseline only |
| Logging | every non-pass check is logged on `hoi.guardrails` |
| Band coverage | the forecast also reports its stored split-conformal test coverage (84.7% / 85.8% / 83.3% for 1 / 7 / 30 days, acceptable 70-90%) |

On the demo data no check fires for the forecast or attrition. The forecast has medium
confidence because its band is about 0.15 wide, and attrition is medium by its cap.

**Backtest monitor** (`python run.py backtest-monitor`), last 84 days of SYNTHETIC actuals,
error in rooms (model vs seasonal naive):

| Hotel | 1 day ahead | 7 days ahead | 80% band coverage | Workload, last 12 weeks (model vs naive) |
|---|---|---|---|---|
| Default (45 rooms) | 1.53 vs 3.17 | 1.67 vs 3.17 | 89% / 88% | **0.059 vs 0.046: WARNING, model worse** |
| Himsagar (24 rooms) | 1.22 vs 1.79 | 1.49 vs 1.79 | **68% / 66%** | 0.078 vs 0.085 |

Two real findings:

1. On the default hotel, the workload model is worse than "same as this week" over the last 12
   weeks, although it beat it over the full test (0.053 vs 0.073).
2. On Himsagar, the forecast band holds the actual only about two thirds of the time. The band
   was calibrated on the 45-room hotel, and a 24-room hotel is noisier in occupancy terms.
   Himsagar's 7-day forecast was also worse than naive in 10 of 57 rolling windows.

## Limits

- The cancellation model learned from two Portuguese hotels with 28-42% cancellation rates.
  It is not validated for any Indian hill hotel. The HOI demo hotel is synthetic and has no
  booking records. So the product uses the base-rate table on synthetic "rooms on the books 7
  days before". The model runs only when real bookings are sent.
- The 2017 test period had more cancellations than training. The model under-predicts there
  and the 80% ranges under-cover. Retrain on the hotel's own recent bookings.
- Weather is a real live forecast for real dates. The other alerts use the synthetic 2029
  calendar, so in the demo they refer to different days.
- All alert thresholds and guardrail limits are design choices (ASSUMED), not measured.
- The PSI batch check needs 200 or more rows, so for a 20-55 person hotel only the per-row
  check runs.
- Drift references for the synthetic v1 models are dated by their last git commit
  (2026-10-13), because the artifacts carry no training timestamp.
- A future baseline worth trying for occupancy is a time-series foundation model such as
  Chronos-2. It is not installed: no new dependencies were added.

## How to retrain

```powershell
cd ml
python run.py train-cancellation            # REAL data; downloads + hash-checks the file if missing
python run.py train-cancellation --cpu      # without the GPU (XGBoost comparison on the CPU)
python run.py guard-reference               # after retraining any synthetic v1 model
python run.py backtest-monitor --hotel himsagar --strict   # exit 1 if a model is worse than its baseline
python -m pytest -q tests/test_guardrails.py tests/test_hotel_alerts.py
```

To use a hotel's own bookings, export them with the same booking fields (arrival date, booking
date, nights, deposit type, market segment, ...). Add a loader next to
`ml/realdata/hotels.py`, keep the arrival-date split, and retrain. The validation rule then
picks the model or the base-rate table per horizon for that hotel.
