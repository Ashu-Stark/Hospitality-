# Model card: workload v1 (SYNTHETIC data)

## Intended use

Next week's department load ratio (required / available hours), for staffing.

## Data

SYNTHETIC department-weeks; same week windows as the attrition reference split.

Dataset hash (combined SHA-256 of 7 input files, seed 42): `7368e24b53ea3197...` (dataset_hash.json).

## Training and serving

Trained and evaluated on the GPU only (cuda:0 NVIDIA GeForce RTX 4050 Laptop GPU): XGBoost with device=cuda and torch on CUDA for the logistic models (ml/gpu.py refuses to train without CUDA; there is no CPU fallback). The saved model.joblib is CPU-only inference (numpy tree arrays / coefficients), so the servers need no GPU, torch or xgboost.

## Metrics vs baseline (test)

| model | test MAE | test RMSE | test R2 |
|---|---|---|---|
| workload_naive | 0.0729 | 0.1106 | 0.6756 |
| workload_model | 0.0534 | 0.0752 | 0.8500 |

## Limitations

- Workload standards are calibrated placeholders (ASSUMED) pending the HM student.
- Only ~8 departments: few rows per week.

**Planted-drivers honesty note.** All data is SYNTHETIC, produced by the seeded generator in ml/generator with ASSUMED parameters. The relationships the model finds were PLANTED by that generator, so every metric here shows the pipeline recovering a known mechanism. None of it is evidence of accuracy on real hotel data.
