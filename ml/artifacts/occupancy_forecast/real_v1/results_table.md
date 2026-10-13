| Horizon | Hotel | Model | MAPE | MAE (room-nights) | Typical error | 80% band coverage | Val MAE |
|---|---|---|---|---|---|---|---|
| 1d | City Hotel | xgb_pace_gpu **(chosen on validation)** | 0.9% | 1.9 | 1.4 | 96% | 3.0 |
| 1d | City Hotel | lgbm_pace_cpu | 0.9% | 1.9 | 1.4 | 96% | 3.1 |
| 1d | City Hotel | pickup_naive | 1.5% | 3.1 | 2.0 | 87% | 3.2 |
| 1d | City Hotel | timesfm_fine_tuned | 3.6% | 7.2 | 4.3 | 85% | 17.9 |
| 1d | City Hotel | timesfm_zero_shot | 3.6% | 7.3 | 4.3 | 90% | 18.4 |
| 1d | City Hotel | lgbm_calendar_cpu | 4.1% | 8.5 | 6.3 | 93% | 19.8 |
| 1d | City Hotel | snaive_week | 5.3% | 10.9 | 7.0 | 100% | 42.7 |
| 1d | City Hotel | snaive_year | 7.3% | 15.4 | 9.0 | 95% | 45.2 |
| 1d | Resort Hotel | lgbm_pace_cpu | 1.1% | 1.9 | 1.3 | 92% | 3.1 |
| 1d | Resort Hotel | xgb_pace_gpu **(chosen on validation)** | 1.1% | 1.9 | 1.3 | 91% | 3.0 |
| 1d | Resort Hotel | pickup_naive | 1.6% | 2.6 | 2.0 | 83% | 3.2 |
| 1d | Resort Hotel | timesfm_zero_shot | 4.3% | 7.1 | 4.5 | 82% | 18.4 |
| 1d | Resort Hotel | lgbm_calendar_cpu | 4.3% | 7.2 | 4.5 | 88% | 19.8 |
| 1d | Resort Hotel | timesfm_fine_tuned | 4.4% | 7.3 | 4.3 | 75% | 17.9 |
| 1d | Resort Hotel | snaive_week | 6.4% | 10.4 | 7.0 | 100% | 42.7 |
| 1d | Resort Hotel | snaive_year | 6.8% | 11.3 | 5.0 | 88% | 45.2 |
| 7d | City Hotel | xgb_pace_gpu **(chosen on validation)** | 2.5% | 5.3 | 4.1 | 96% | 8.9 |
| 7d | City Hotel | lgbm_pace_cpu | 2.6% | 5.5 | 4.6 | 96% | 9.6 |
| 7d | City Hotel | timesfm_zero_shot | 3.9% | 7.9 | 4.9 | 93% | 33.3 |
| 7d | City Hotel | timesfm_fine_tuned | 4.0% | 8.2 | 4.8 | 85% | 32.5 |
| 7d | City Hotel | lgbm_calendar_cpu | 4.2% | 8.7 | 6.4 | 99% | 34.3 |
| 7d | City Hotel | pickup_naive | 4.3% | 9.1 | 7.5 | 88% | 11.1 |
| 7d | City Hotel | snaive_week | 5.3% | 10.9 | 7.0 | 100% | 42.7 |
| 7d | City Hotel | snaive_year | 7.3% | 15.4 | 9.0 | 95% | 45.2 |
| 7d | Resort Hotel | lgbm_pace_cpu | 2.3% | 3.8 | 2.5 | 91% | 9.6 |
| 7d | Resort Hotel | xgb_pace_gpu **(chosen on validation)** | 2.4% | 3.9 | 2.5 | 91% | 8.9 |
| 7d | Resort Hotel | pickup_naive | 4.2% | 7.1 | 5.0 | 87% | 11.1 |
| 7d | Resort Hotel | lgbm_calendar_cpu | 5.0% | 8.3 | 5.5 | 97% | 34.3 |
| 7d | Resort Hotel | timesfm_zero_shot | 5.3% | 8.7 | 4.6 | 80% | 33.3 |
| 7d | Resort Hotel | timesfm_fine_tuned | 5.6% | 9.2 | 4.3 | 72% | 32.5 |
| 7d | Resort Hotel | snaive_week | 6.4% | 10.4 | 7.0 | 100% | 42.7 |
| 7d | Resort Hotel | snaive_year | 6.8% | 11.3 | 5.0 | 88% | 45.2 |
| 30d | City Hotel | lgbm_pace_cpu **(chosen on validation)** | 3.4% | 7.2 | 4.5 | 91% | 13.9 |
| 30d | City Hotel | xgb_pace_gpu | 3.5% | 7.4 | 4.4 | 94% | 14.3 |
| 30d | City Hotel | timesfm_zero_shot | 4.5% | 9.1 | 5.3 | 96% | 37.7 |
| 30d | City Hotel | timesfm_fine_tuned | 4.8% | 9.9 | 5.8 | 80% | 34.1 |
| 30d | City Hotel | lgbm_calendar_cpu | 5.2% | 11.1 | 9.4 | 95% | 35.4 |
| 30d | City Hotel | snaive_year | 7.3% | 15.4 | 9.0 | 95% | 45.2 |
| 30d | City Hotel | snaive_week | 8.9% | 18.5 | 9.5 | 93% | 54.5 |
| 30d | City Hotel | pickup_naive | 8.9% | 18.7 | 15.0 | 84% | 21.8 |
| 30d | Resort Hotel | xgb_pace_gpu | 4.1% | 6.8 | 4.4 | 92% | 14.3 |
| 30d | Resort Hotel | lgbm_pace_cpu **(chosen on validation)** | 4.1% | 6.8 | 4.4 | 89% | 13.9 |
| 30d | Resort Hotel | lgbm_calendar_cpu | 5.0% | 8.3 | 5.0 | 87% | 35.4 |
| 30d | Resort Hotel | timesfm_zero_shot | 5.6% | 9.3 | 4.7 | 81% | 37.7 |
| 30d | Resort Hotel | timesfm_fine_tuned | 5.8% | 9.6 | 4.5 | 70% | 34.1 |
| 30d | Resort Hotel | snaive_year | 6.8% | 11.3 | 5.0 | 88% | 45.2 |
| 30d | Resort Hotel | pickup_naive | 9.0% | 15.3 | 10.0 | 84% | 21.8 |
| 30d | Resort Hotel | snaive_week | 9.6% | 16.1 | 8.0 | 93% | 54.5 |
