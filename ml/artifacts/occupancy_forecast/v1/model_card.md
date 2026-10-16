# Model card: occupancy_forecast v1 (SYNTHETIC data)

## Intended use

Daily occupancy forecast 1, 7 and 30 days ahead with an 80% band and high / low demand alerts, for roster planning in a small hill hotel. Interface: forecast.predict.

## Data

Daily SYNTHETIC occupancy, calendar and weather; train targets 2023-2024, test 2025 (split by time). One direct XGBoost model per horizon plus two quantile models.

Dataset hash (combined SHA-256 of 3 input files, seed 42): `c26733fd4a45e143...` (dataset_hash.json).

## Training and serving

Trained and evaluated on the GPU only (cuda:0 NVIDIA GeForce RTX 4050 Laptop GPU): XGBoost with device=cuda and torch on CUDA for the logistic models (ml/gpu.py refuses to train without CUDA; there is no CPU fallback). The saved model.joblib is CPU-only inference (numpy tree arrays / coefficients), so the servers need no GPU, torch or xgboost.

## Metrics vs baseline (test)

| horizon | model MAPE | seasonal-naive MAPE | used | 80% band coverage (split-conformal) | T6 quantile-band coverage |
|---|---|---|---|---|---|
| 1 d | 6.7% | 13.7% | model | 86.6% | 78.6% |
| 7 d | 7.2% | 13.7% | model | 85.5% | 76.4% |
| 30 d | 10.3% | 13.7% | model | 82.7% | 68.5% |

## Uncertainty band

Split-conformal (T12): a twin of the forecaster trained only on targets before the calibration window (2024) is scored on that window; the (n + 1)-corrected 10th / 90th percentiles of its residuals are added to the point forecast. The point forecast itself is unchanged from T6. The twin has less history than the deployed model, so the band is likely a little conservative.

Outside the 75%-85% target: 1 d (86.6%), 7 d (85.5%); reported as is, not tuned.

## Limitations

- The band is calibrated on one year (2024) of residuals; coverage can drift in a year unlike the calibration year.
- High-demand alerts (>= 0.90 forecast) are weak: low precision and recall in 2025.
- Only one synthetic property; the seasonality is the generator's assumption.

**Planted-drivers honesty note.** All data is SYNTHETIC, produced by the seeded generator in ml/generator with ASSUMED parameters. The relationships the model finds were PLANTED by that generator, so every metric here shows the pipeline recovering a known mechanism. None of it is evidence of accuracy on real hotel data.
