# Model card: pulse v1 (SYNTHETIC data)

## Intended use

Next week's pulse score (1-5) per employee, as an early engagement warning.

## Data

SYNTHETIC weekly pulse; time split 60/20/20 by week with a label embargo.

Dataset hash (combined SHA-256 of 5 input files, seed 42): `71ba241d23b4129f...` (dataset_hash.json).

## Training and serving

Trained and evaluated on the GPU only (cuda:0 NVIDIA GeForce RTX 4050 Laptop GPU): XGBoost with device=cuda and torch on CUDA for the logistic models (ml/gpu.py refuses to train without CUDA; there is no CPU fallback). The saved model.joblib is CPU-only inference (numpy tree arrays / coefficients), so the servers need no GPU, torch or xgboost.

## Metrics vs baseline (test)

| model | test MAE | test RMSE | test R2 |
|---|---|---|---|
| pulse_naive | 0.2567 | 0.3255 | 0.7924 |
| pulse_model | 0.2490 | 0.3127 | 0.8084 |

## Limitations

- Gain over the naive 'copy this week' baseline is small (see table).
- Pulse is generated from latent traits the model never sees; real surveys are noisier.

**Planted-drivers honesty note.** All data is SYNTHETIC, produced by the seeded generator in ml/generator with ASSUMED parameters. The relationships the model finds were PLANTED by that generator, so every metric here shows the pipeline recovering a known mechanism. None of it is evidence of accuracy on real hotel data.
