# Model card: attrition v1 (SYNTHETIC data)

## Intended use

Weekly 90-day exit risk per employee with a band (low / watch / high), the top-3 driver categories and playbook actions, to start a conversation, never to make a decision about a person. Interfaces: attrition.score, attrition.rescore (a SIMULATION).

## Data

SYNTHETIC employee-weeks 2023-2029. Separate evaluations: resignation (permanent staff) and contract-end exit (seasonal staff). Expanding-window backtest, test years 2027-2029, 90-day label gap; Platt calibration and threshold on the year before each test year. Heroes (demo employees) are never in training.

Dataset hash (combined SHA-256 of 6 input files, seed 42): `41163b06e51f2408...` (dataset_hash.json).

## Training and serving

Trained and evaluated on the GPU only (cuda:0 NVIDIA GeForce RTX 4050 Laptop GPU): XGBoost with device=cuda and torch on CUDA for the logistic models (ml/gpu.py refuses to train without CUDA; there is no CPU fallback). The saved model.joblib is CPU-only inference (numpy tree arrays / coefficients), so the servers need no GPU, torch or xgboost.

## Metrics vs baseline (test)

| segment | scorer | ROC-AUC | PR-AUC | precision | recall | base rate |
|---|---|---|---|---|---|---|
| resignation | rules | 0.542 | 0.071 | 0.058 | 0.270 | 0.054 |
| resignation | logistic (winner) | 0.691 | 0.118 | 0.170 | 0.326 | 0.054 |
| resignation | xgboost | 0.666 | 0.090 | 0.101 | 0.496 | 0.054 |
| contract_end | rules | 0.423 | 0.160 | 0.189 | 0.832 | 0.187 |
| contract_end | logistic | 0.715 | 0.276 | 0.373 | 0.777 | 0.187 |
| contract_end | xgboost | 0.761 | 0.327 | 0.391 | 0.717 | 0.187 |
| contract_end | contract_rule (winner) | 0.736 | 0.316 | 0.459 | 0.696 | 0.187 |

## Risk bands (T12, seasonal rule since T12b)

PERMANENT staff (band_basis model_rank): within each scoring week, active non-hero permanent staff are ranked by calibrated risk. high = the first ceil(10% x n) slots, watch = the next ceil(15% x n), low = the rest (shares ASSUMED, config.yaml). Staff with identical risk form a tie group that is never split: it takes a band only if it fits wholly in the remaining slots, otherwise the next lower band. The probability is still shown beside the band.

SEASONAL staff (band_basis contract_date_rule): days to contract end <= 30 = high, 31-60 = watch, else low (thresholds ASSUMED, config.yaml). A seasonal exit is a KNOWN date, not a prediction. About 96% of seasonal model risks were tied each week (the contract-date rule gives everyone whose contract ends more than 90 days out the same risk), so ranking them carried no information. This rule was chosen AFTER seeing those ties, not to place any hero.

Why ceil-count for permanent staff: ceil-count was first chosen because the seasonal group has about 7 people, where a percentile rule (rank / n <= 10%) can never create a high band. The rule was chosen AFTER demo hero Sunita's rank had been seen. She sits ON the high / watch boundary (rank 5 of 48, risk 0.0905, between ranks 4 and 6), so her band is a ranking result, not a confident prediction.

| hero | group | risk | model rank | band (used) | basis | percentile-rule band |
|---|---|---|---|---|---|---|
| Sunita | resignation | 0.0911 | 5 / 48 | high | model_rank | watch |
| Rajesh | resignation | 0.0404 | 17 / 48 | low | model_rank | low |
| Meena | resignation | 0.0400 | 17 / 48 | low | model_rank | low |
| Arun | contract_end | 0.7749 | 1 / 7 | high | contract_date_rule | n/a |
| Deepak | resignation | 0.0233 | 32 / 48 | low | model_rank | low |

Backtest (pooled test weeks 2027-2029), bands recomputed every week:

| segment | scorer | precision in high | lift over base rate | leaver-weeks in high + watch | tied share per week |
|---|---|---|---|---|---|
| resignation | rules | 0.066 | 1.22x (base 0.054) | 10.2% | 1.00 |
| resignation | logistic (winner) | 0.130 | 2.39x (base 0.054) | 52.3% | 0.04 |
| resignation | xgboost | 0.116 | 2.13x (base 0.054) | 50.1% | 0.05 |
| contract_end | rules | 0.185 | 0.99x (base 0.187) | 16.3% | 0.91 |
| contract_end | logistic | 0.161 | 0.86x (base 0.187) | 52.7% | 0.00 |
| contract_end | xgboost | 0.176 | 0.94x (base 0.187) | 50.0% | 0.00 |
| contract_end | contract_rule (winner) | 0.000 | 0.0x (base 0.187) | 0.0% | 0.96 |
| contract_end | contract-date RULE band (used since T12b) | 0.368 | 1.97x (base 0.187) | 54.9% | n/a |

Under model ranks, the big seasonal tie group overflowed the high and watch slots, so no seasonal employee was ever high or watch (the 0.0 row above); that is why seasonal staff now use the contract-date rule.

## Explanation method (T12)

Drivers come from the SAME model that produces the risk (the segment's calibrated winner): contributions in calibrated log-odds relative to the training mean. For the logistic winner that is Platt slope x coefficient x (standardised value - training mean), summed per driver category; for the contract-date rule it is the days-to-contract-end term. XGBoost TreeSHAP is kept only as a comparison (drivers.json).

Driver support in the SYNTHETIC generator: overtime overload, stalled progression, low engagement, season-end exit and pay gap are planted. Clustered-leave burnout is WEAKLY SUPPORTED: the hazard has a weeks-without-leave term but no pre-festival leave term. Manager relationship is UNSUPPORTED (no signal at all).

Demo checks (T12b): the earlier check "Sunita has overtime overload AND clustered-leave burnout" was REMOVED. It came from the hero script, written before we knew the generator never creates a pre-festival leave driver. It is replaced by two checks:

- PASS: Sunita's top 3 drivers include overtime overload: ['overtime_overload', 'pay_gap', 'low_engagement'] (risk 0.0911, rank 5/48, high)
- PASS: Deepak is not high risk: risk 0.0233, rank 32/48, band low

## Limitations

- Few leavers (a few dozen in the pooled test years); rows are correlated employee-weeks, so the metrics are noisy.
- Logistic wins for resignations because the planted hazard IS logistic; that is a property of the synthetic data, not evidence for logistic on real data.
- Seasonal calibration is set by one validation year and over-predicts in the top bin.
- Logistic contributions are relative to the training mean, so a one-hot category the employee is NOT in moves the log-odds too; such context features are never shown as drivers. Manager relationship is UNSUPPORTED (no signal in the data).
- Clustered-leave burnout is WEAKLY SUPPORTED: pre-festival leave was never planted in the hazard, so only weeks without leave pushes that category up.
- Seasonal bands come from the contract date, not the model: they flag who is about to reach a known end date, not who might resign.
- Bands are ranks: someone always fills the high slots, even in a calm week.

**Planted-drivers honesty note.** All data is SYNTHETIC, produced by the seeded generator in ml/generator with ASSUMED parameters. The relationships the model finds were PLANTED by that generator, so every metric here shows the pipeline recovering a known mechanism. None of it is evidence of accuracy on real hotel data.
