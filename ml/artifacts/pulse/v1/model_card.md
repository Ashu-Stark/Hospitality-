# Model card: pulse v1 (SYNTHETIC data)

## Intended use

Next week's pulse score (1-5) per employee, as an early engagement warning.

## Data

SYNTHETIC weekly pulse; time split 60/20/20 by week with a label embargo.

Dataset hash (combined SHA-256 of 5 input files, seed 42): `71ba241d23b4129f...` (dataset_hash.json).

## Metrics vs baseline (test)

| model | test MAE | test RMSE | test R2 |
|---|---|---|---|
| pulse_naive | 0.2567 | 0.3255 | 0.7924 |
| pulse_model | 0.2498 | 0.3143 | 0.8064 |

## Limitations

- Gain over the naive 'copy this week' baseline is small (see table).
- Pulse is generated from latent traits the model never sees; real surveys are noisier.

**Planted-drivers honesty note.** All data is SYNTHETIC, produced by the seeded generator in ml/generator with ASSUMED parameters. The relationships the model finds were PLANTED by that generator, so every metric here shows the pipeline recovering a known mechanism. None of it is evidence of accuracy on real hotel data.
