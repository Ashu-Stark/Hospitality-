# Hospitality Operations Intelligence (HOI)

An AI platform for small hill hotels in Uttarakhand that predicts employee attrition,
forecasts occupancy and generates duty rosters. Hackathon project.

**All data in this repo is SYNTHETIC.** It is produced by a seeded generator from ASSUMED
parameters, not measured from any real hotel or employee.

## Repository layout

| Folder | What it contains |
|---|---|
| [`ml/`](ml/) | Synthetic data generator, attrition feature pipeline, model training and evaluation (Python 3.13). |
| [`frontend/`](frontend/) | User-facing web app. Not started yet. |
| [`backend/`](backend/) | API serving the models and data to the frontend. Not started yet. |

## Quick start (ml)

Windows / PowerShell, from the repo root:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r ml\requirements-lock.txt
cd ml
python run.py test       # pytest
python run.py generate   # write synthetic CSVs to ml/data/
python run.py validate   # PASS/FAIL checks on the generated data
python run.py eval       # train + package every model -> ml/artifacts/<name>/v1/
python run.py check-artifacts  # load the committed artifacts, no retraining
```

Project rules and a full description of every data file are in [`ml/CLAUDE.md`](ml/CLAUDE.md).

Data dictionary (every table and column; hidden, derived and label columns marked): [`ml/docs/data_dictionary.md`](ml/docs/data_dictionary.md).

Model card (what each model is good for, its limits, and every placeholder value to replace): [`ml/docs/MODEL_CARD.md`](ml/docs/MODEL_CARD.md).
