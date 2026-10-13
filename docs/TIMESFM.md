# Can Google's TimesFM be used in HOI?

**Audience:** the ML owner and the team lead. **Checked:** 2026-10-13.

## Short answer

**Yes, as an offline challenger to the occupancy forecast. Use version 2.5, not 3.0, and not inside the Render API.**

## Facts (verified on the model cards / repo)

| | TimesFM 2.5 | TimesFM 3.0 |
|---|---|---|
| Weights licence | **Apache-2.0** (commercial use OK) | **"TimesFM Non-Commercial License v1.0"**: not usable in a product we sell; commercial use goes through Google Cloud (e.g. BigQuery ML) |
| Size | ~200M params | ~0.3B params |
| Outputs | point + quantiles (continuous quantile head) | point + 9 quantiles |
| Covariates | via XReg (in-context regression) | native dynamic covariates |
| Install | clone `google-research/timesfm`, `pip install -e .[torch]` | same repo |

Sources: github.com/google-research/timesfm, huggingface.co/google/timesfm-2.5-200m-pytorch, huggingface.co/google/timesfm-3.0-pytorch.

## Measured here (CPU laptop, synthetic hotel-like series; NOT our project data)

Script: `C:\tmp\tfm\bench.py`. 3 years of daily occupancy with yearly season, weekend uplift, festival spikes and noise; 10 rolling 30-day backtests.

| Metric | Result |
|---|---|
| Load + compile | 57.5 s |
| Memory after load | ~1.1 GB RSS |
| Inference | 2.85 s for 10 series × 30 days (≈285 ms per series) |
| 30-day MAPE | **5.8%** TimesFM vs 11.0% seasonal-naive |
| 10–90% interval coverage | 86% (nominal 80%) |

Read with care: this series is cleaner than real data. It shows that TimesFM runs and is in the right ballpark. It does not show that TimesFM beats our model.

## What this means for HOI

1. **Deployment:** ~1.1 GB RAM rules out the Render free instance (512 MB). Run it as a nightly batch job (GitHub Actions / a small VM) and write forecasts to the database, or run it in the ML pipeline, not the request path.
2. **Fair test before adoption:** backtest it on *our* synthetic history, with the same time splits and 90-day gap as the LightGBM model (7d MAPE 7.2%, 30d 10.3%). Report MAPE **and** interval coverage. Our current 80% band covers only ~68% at 7 days, and better-calibrated intervals may be TimesFM's most useful contribution.
3. **Covariates:** festivals, weather and road closures matter in hill hotels. Test with XReg covariates and without; zero-shot without covariates will likely miss festival spikes.
4. **Where else:** department workload forecasting and inventory demand (consumption per occupied room) are both short univariate series where a zero-shot model is a cheap baseline.
5. **Pitch line (honest):** "We benchmark against Google's TimesFM foundation model as a zero-shot challenger." Only say it beats or matches us after step 2.
