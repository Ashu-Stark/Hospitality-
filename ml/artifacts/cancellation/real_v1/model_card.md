# Model card: booking cancellation risk (cancellation/real_v1)

**Data: REAL** public bookings (not synthetic): Hotel Booking Demand, Antonio, Almeida & Nunes (2019), *Data in Brief* 22:41-49, CC BY 4.0. Two Portuguese hotels (Lisbon city, Algarve resort), arrivals 2015-07..2017-08. Data card: `ml/realdata/hotel_alerts/DATA_CARD.md`.

- Task: chance that a booking on the books is cancelled or a no-show. Deployed model: **lightgbm** (chosen on validation log loss before the test was read).
- Trained on 479,722 snapshots (arrivals <= 2016-10-31); test = arrivals 2017-03-01..2017-08-31.
- Features (22): booking-time fields only; excluded columns and reasons in `feature_list.json`.

| Test, at booking time | ROC-AUC | PR-AUC | Brier | ECE |
|---|---|---|---|---|
| base_rate | 0.6378 | 0.4937 | 0.2338 | 0.0864 |
| logistic | 0.7953 | 0.769 | 0.1729 | 0.0433 |
| lightgbm | 0.82 | 0.7858 | 0.1681 | 0.0565 |
| xgboost | 0.8202 | 0.7859 | 0.1684 | 0.0621 |

Occupancy use (rooms on the books that really stay, test, both hotels; source chosen per horizon on validation MAE):

| Days ahead | No adjustment | Base-rate table | Model | Deployed | 80% range coverage |
|---|---|---|---|---|---|
| 1 | 0.97 | 1.2 | 1.09 | base | 0.72 |
| 7 | 5.25 | 4.49 | 5.24 | base | 0.541 |
| 14 | 10.94 | 7.95 | 5.1 | base | 0.484 |
| 30 | 18.67 | 10.56 | 5.33 | base | 0.476 |

Limits: Portuguese city / resort hotels with high cancellation rates (city 42%, resort 28%), not Uttarakhand hill hotels; HOI's synthetic hotel has no booking records, so the product uses the base-rate table unless real bookings are sent. Retrain on the hotel's own bookings before trusting the numbers.
