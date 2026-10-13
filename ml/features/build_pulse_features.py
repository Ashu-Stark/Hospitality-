"""Build the pulse-score regression features from SYNTHETIC Task 3/4 outputs.

Inputs (data/): employee_v2.csv, weekly_behaviour.csv, contract_renewals.csv.
Never reads data/internal/ (no baseline_pulse, latent_frustration or other latent traits).

Rows: one per employee-week t where
  - the employee is active in week t (is_active True),
  - the employee has at least 1 earlier week of history (week t-1 exists), and
  - week t+1 exists and the employee is still active in it. The week right before an exit is
    dropped, because its "next week" is the exit week; the last observed week is dropped too.
Prediction is made at the END of week t for week t+1.

Features (observable as of week t):
  categorical: department, role, contract_type
  numeric:
    tenure_days              week_start - hire_date
    load_ratio               week t dynamic department load
    overtime_hours           week t
    leave_days               week t
    pulse_score              week t (1-5)
    pulse_roll4_mean         mean pulse over weeks t-3..t (fewer at the start of a history)
    pulse_trend_4w           pulse(t) - pulse(t-4); 0 if fewer than 5 weeks of history
    days_until_contract_end  min(days to the contract end in force at week t, 90); permanent
                             staff are always 90 (same definition as the attrition features)

Label: next_week_pulse_score = pulse_score of the same employee in week t+1 (week_start + 7).

Output: data/pulse_features.csv with employee_id, week_start, the features, the label.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ml.features.build_features import (
    DATA_DIR,
    LATENT_NAMES,
    add_rolling_features,
    days_until_contract_end,
)

PULSE_LABEL = "next_week_pulse_score"
PULSE_CATEGORICAL = ["department", "role", "contract_type"]
PULSE_NUMERIC = [
    "tenure_days",
    "load_ratio",
    "overtime_hours",
    "leave_days",
    "pulse_score",
    "pulse_roll4_mean",
    "pulse_trend_4w",
    "days_until_contract_end",
]
PULSE_FEATURES = PULSE_CATEGORICAL + PULSE_NUMERIC
ID_COLUMNS = ["employee_id", "week_start"]

__all__ = ["LATENT_NAMES", "PULSE_FEATURES", "PULSE_LABEL", "build_pulse_features"]


def add_next_week_label(beh: pd.DataFrame) -> pd.DataFrame:
    """Attach next week's pulse and activity; rows must be sorted by employee, week."""
    g = beh.groupby("employee_id", sort=False)
    next_week = g["week_start"].shift(-1)
    consecutive = next_week == beh["week_start"] + pd.Timedelta(days=7)
    return beh.assign(
        **{PULSE_LABEL: g["pulse_score"].shift(-1)},
        _next_active=g["is_active"].shift(-1).astype("boolean").fillna(False) & consecutive,
        _has_prev=g["week_start"].shift(1).notna(),
    )


def build_pulse_features(
    employees: pd.DataFrame,
    behaviour: pd.DataFrame,
    renewals: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Pulse feature matrix + next-week label (see module docstring for definitions)."""
    beh = behaviour.assign(week_start=pd.to_datetime(behaviour["week_start"]))
    beh = add_rolling_features(beh).reset_index(drop=True)
    beh = add_next_week_label(beh)

    staff = employees.set_index("employee_id").loc[beh["employee_id"]].reset_index(drop=True)
    beh["contract_type"] = staff["contract_type"]
    beh["tenure_days"] = (beh["week_start"] - pd.to_datetime(staff["hire_date"])).dt.days
    no_renewals = pd.DataFrame(columns=["employee_id", "renewal_date", "new_contract_end_date"])
    beh["days_until_contract_end"] = days_until_contract_end(
        beh, employees, no_renewals if renewals is None else renewals
    )

    keep = beh["is_active"].astype(bool) & beh["_has_prev"] & beh["_next_active"]
    return beh.loc[keep, ID_COLUMNS + PULSE_FEATURES + [PULSE_LABEL]].reset_index(drop=True)


def load_inputs(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return (
        pd.read_csv(data_dir / "employee_v2.csv", keep_default_na=False),
        pd.read_csv(data_dir / "weekly_behaviour.csv"),
        pd.read_csv(data_dir / "contract_renewals.csv"),
    )


def main(data_dir: Path = DATA_DIR) -> Path:
    features = build_pulse_features(*load_inputs(data_dir))
    path = data_dir / "pulse_features.csv"
    features.to_csv(path, index=False, date_format="%Y-%m-%d")
    print(f"SYNTHETIC pulse features written: {path}")
    print(f"  {len(features)} rows, {features['employee_id'].nunique()} employees, "
          f"{len(PULSE_FEATURES)} features, label mean {features[PULSE_LABEL].mean():.3f} "
          f"(sd {features[PULSE_LABEL].std():.3f})")
    return path


if __name__ == "__main__":
    main()
