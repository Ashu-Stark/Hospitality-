# Model card: crowd_forecast real_v1 (Char Dham, REAL public data)

- **Task:** daily pilgrims, 1-14 days ahead, for Kedarnath, Badrinath, Gangotri and Yamunotri.
  The output is the expected count, an 80% range, a band (quiet / normal / busy / very busy, as
  a 0-100 index) and a confidence label.
- **Data:** real official figures and Open-Meteo weather (CC BY 4.0); see
  `ml/realdata/crowd/DATA_CARD.md`. The totals between reports are real; the day values inside
  a reporting interval are ESTIMATED by even spreading.
- **Model:** three XGBoost models, trained and evaluated on the GPU only (cuda:0 NVIDIA
  GeForce RTX 4050 Laptop GPU; `ml/gpu.py` refuses to train without CUDA): the point forecast
  (L1 loss, 15 leaves, minimum leaf weight 20, 600 rounds, seed 42) and the 10% and 90%
  quantiles (`reg:quantileerror`), with a split-conformal widening of 0.484 (scaled units).
  - Trained on the 2022-2025 seasons.
  - Exported as plain JSON trees in `bundle.json`. `predict.py` evaluates them with the
    standard library only, and is byte-identical to `portal/hoi_portal/services/crowd_model.py`.
- **Files:**

  | File | What |
  |---|---|
  | `bundle.json` | deployed model, context, guardrail settings |
  | `xgb_{point,q10,q90}.json` | native XGBoost models |
  | `metrics.json` | every model, baseline, ablation, failure analysis, dropped figure |
  | `feature_list.json` | features |
  | `daily_target.csv` | daily target with its basis |
  | `test_predictions_{2025,2026}.csv` | test-season predictions |

- **Metrics:** daily MAE, model against seasonal-naive against moving average (7 days):

  | Test season | Model | Seasonal-naive | Moving average | 80% range coverage | Band accuracy (model / seasonal-naive) |
  |---|---|---|---|---|---|
  | 2025 (trained 2022-2024) | 3,294 | 3,254 | 3,902 | 70% | 41% / 54% |
  | 2026 to 7 Oct (trained 2022-2025) | 2,594 | 2,881 | 4,867 | 84% | 63% / 58% |

  On real interval totals the model had 77% error in 2025 (seasonal-naive 58%) and 26% in 2026
  (seasonal-naive 31%). Overall it is about as good as last season's pattern (slightly worse in
  2025, better in 2026); it is not a large improvement, and the 2025 range was too narrow.
- **Guardrails:**
  - input validation;
  - closed season returns 0 and "closed"; a year with no announced dates is `unknown_season`;
  - missing or stale counts, or a drifting feature: last season's level, confidence low;
  - clipping to 0..cap (1.25 times the highest reported single day);
  - confidence from the range width, abstaining above 3 times the point forecast.
- **Limits:**
  - opening days are badly under-forecast (2026 Kedarnath: about 12,500-13,000 forecast
    against about 29,600 actual);
  - closures and landslide days cannot be predicted;
  - the 2026 closing dates are expected or provisional until 20 Oct 2026;
  - the last official count in the bundle is 7 Oct 2026; later days use last season's level;
  - the band cut points are ASSUMED percentiles, not safety limits.
- **Retrain:** `python -m ml.realdata.crowd.train` from the repo root (needs the GPU).
