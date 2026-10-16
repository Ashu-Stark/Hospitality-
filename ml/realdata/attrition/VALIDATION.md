# Staff-leaving (attrition) model: validation on public data and a plain-language rating

Run on 2026-10-16 with the GPU-trained pipeline (`python run.py realdata`; every fit, Platt
calibration and evaluation prediction on cuda:0 NVIDIA GeForce RTX 4050 Laptop GPU). Code:
`ml/realdata/attrition.py`. Numbers: `ml/artifacts/attrition/real_v1/metrics.json`.

## The rating, in plain words

**Useful for deciding whom to check in with first; not accurate enough for any decision about a
person.**

- On the fictional IBM set the model ranks well (a random leaver is ranked above a random stayer
  83% of the time).
- On the only dataset described as real (Babushkin), the same model is only a little better than
  a simple warning-signs checklist: right 60% of the time (logistic regression, the model type
  HOI deploys) or 65% (XGBoost), against 55% for the checklist and 50% for a coin flip.
- Its percentages are honest on average (2-3 points off), so "about 1 in 5" means about 1 in 5.
- There is **no public data on hotel staff**. The only hospitality rows (10 people, 2 leavers)
  are far too few to say anything; on them the models did worse than chance, which with 2
  leavers is noise, not evidence.

So in HOI the risk band should open a conversation (a check-in, a look at overtime and days
off), never decide pay, contracts or discipline.

## What was tested

| | IBM HR Analytics | Babushkin Employee Turnover |
|---|---|---|
| What it is | **FICTIONAL**, made by IBM data scientists for teaching | Described by its author as **real**; country, companies and collection method not documented; mostly HR staff |
| Licence | ODbL 1.0 / DbCL 1.0 | CC BY-NC-SA 4.0: non-commercial, **evaluation only**, never shipped |
| Rows / leavers | 1,470 / 237 (base rate 16.1%) | 982 / 150 (base rate 15.3%); label = quit within 12 months; people still employed with less than 12 months' tenure are excluded (outcome unknown) |
| Removed before modelling | age, gender, marital status | age, gender, the boss's gender, five personality-test scores |
| Checklist baseline (fixed before results) | count of: overtime, job satisfaction <= 2, work-life balance <= 2 | count of: unofficial ("grey") pay, no probation coach |

Protocol (unchanged): neither dataset has dates, so a time split is impossible. Repeated
stratified 5-fold cross-validation (3 repeats, seeds 42-44); every model is Platt-calibrated
inside its training fold (5 inner folds), so no test row touches anything fitted. Models: L2
logistic regression (C = 1, the deployed HOI model type; torch on the GPU) and XGBoost (GPU).

## Results (out-of-fold, mean of 3 repeats; 95% CI = bootstrap on the pooled predictions)

**IBM (fictional)**

| Scorer | ROC-AUC (95% CI) | PR-AUC (base rate 0.161) | Brier (base rate alone 0.135) | ECE |
|---|---|---|---|---|
| Checklist | 0.653 (0.615-0.686) | 0.247 | 0.129 | 0.017 |
| **Logistic regression** | **0.828 (0.797-0.861)** | **0.609** | **0.096** | 0.032 |
| XGBoost | 0.819 (0.791-0.856) | 0.598 | 0.096 | 0.024 |

**Babushkin (real, unverified origin)**

| Scorer | ROC-AUC (95% CI) | PR-AUC (base rate 0.153) | Brier (base rate alone 0.129) | ECE |
|---|---|---|---|---|
| Checklist | 0.552 (0.493-0.596) | 0.174 | 0.129 | 0.029 |
| Logistic regression | 0.601 (0.555-0.649) | 0.213 | 0.127 | 0.029 |
| **XGBoost** | **0.655 (0.609-0.708)** | **0.292** | **0.122** | 0.025 |

Calibration (seed 42, five equal-size groups, mean predicted vs observed):

- IBM, logistic: 0.01 / 0.04 / 0.09 / 0.19 / 0.46 predicted vs 0.04 / 0.03 / 0.09 / 0.15 / 0.49
  observed.
- Babushkin, logistic: 0.09 / 0.12 / 0.14 / 0.17 / 0.23 vs 0.08 / 0.11 / 0.16 / 0.18 / 0.23.
- Babushkin, XGBoost: 0.10 / 0.11 / 0.13 / 0.16 / 0.27 vs 0.08 / 0.10 / 0.11 / 0.16 / 0.32.

Reading: on Babushkin even the riskiest fifth leaves at only 23-32%, against 15% overall. The
Brier score barely improves on "everyone gets the base rate" (0.122-0.127 vs 0.129): the model
knows a little more than the average, not much more.

## Hospitality subset (Babushkin `industry == "HoReCa"`: hotels, restaurants, catering)

| Scorer | ROC-AUC | 95% bootstrap CI | Brier |
|---|---|---|---|
| Checklist | 0.06 | 0.00-0.33 | 0.175 |
| Logistic regression | 0.13 | 0.00-0.48 | 0.171 |
| XGBoost | 0.19 | 0.00-0.50 | 0.177 |

**10 people, 2 of whom left** (11 in the raw file; one excluded because the outcome is
unknown). These are the out-of-fold predictions of models trained on all industries. With 2
leavers a ROC-AUC compares only 2 x 8 = 16 pairs, so one person moves it by about 0.06-0.12 and
the interval spans almost everything from 0 to 0.5. **It tells us nothing either way** about
hospitality, except that there is no public evidence the model works for hotel staff.

## US OPM Federal Workforce Data: checked, not used

Details: [DATA_CARD_OPM.md](DATA_CARD_OPM.md). In short: the files are record-level, carry no
names, and the separation type IS identifiable (QUIT, retirement, RIF, ...), but **they hold no
person identifier**, so an employee in the September snapshot cannot be linked to a separation
in the following year. The only way would be matching on quasi-identifiers (service date,
agency, occupation, duty station, grade), which is close to re-identification, against the
spirit of OPM's privacy-protecting release, and would give a noisy label. We stopped there. No
explicit reuse licence was found on data.opm.gov either (works of the US federal government are
generally not copyrighted, but the site does not say so).

## Limits

- **No public hotel-staff data exists.** Babushkin is not hotel staff (mostly HR professionals,
  undocumented origin); IBM is fictional; OPM is government, not hospitality, and could not be
  labelled.
- No dates in either dataset: cross-validation cannot rule out leakage through time the way the
  synthetic backtests do.
- Only job and pay information is used. Real hotel signals (overtime, rest days, pulse surveys)
  exist only in HOI's synthetic data, where the drivers were planted, so the synthetic results
  (ROC-AUC 0.69 for resignations) are not evidence of real accuracy either.
- Retrain and re-validate on the hotel's own history before trusting any number.
