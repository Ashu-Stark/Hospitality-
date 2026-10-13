"""Build department-level workload (load_ratio) forecasting features from SYNTHETIC data.

Inputs (data/): dept_week_load_dynamic.csv (Task 4's dynamic load, NOT Task 3's static file)
and event_calendar.csv. Never reads data/internal/.

Rows: one per department-week t with at least 4 earlier weeks for that department (weeks
t-4..t-1 exist) and a next week t+1 (week_start + 7) for that department.
Prediction is made at the END of week t for week t+1.

Features (observable as of week t):
  categorical: department
  numeric:
    week_of_year            ISO week number of week t
    occupied_room_nights    week t
    load_ratio              week t (dynamic: follows exits and hires)
    headcount               week t
    load_roll4_mean         mean load_ratio over weeks t-3..t
    room_nights_roll4_mean  mean occupied_room_nights over weeks t-3..t
    load_trend_4w           load_ratio(t) - load_ratio(t-4)
    is_festival_week        1 if any day of week t is a festival day (event_calendar.csv)
    next_week_is_festival   1 if any day of week t+1 is a festival day. Not leakage: the
                            festival calendar is published in advance, so it is known at the
                            end of week t; it says nothing about next week's realised load.

Label: next_week_load_ratio = the same department's load_ratio in week t+1.

Output: data/workload_features.csv with department, week_start, the features, the label.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ml.features.build_features import DATA_DIR

WORKLOAD_LABEL = "next_week_load_ratio"
HISTORY_WEEKS = 4
WORKLOAD_CATEGORICAL = ["department"]
WORKLOAD_NUMERIC = [
    "week_of_year",
    "occupied_room_nights",
    "load_ratio",
    "headcount",
    "load_roll4_mean",
    "room_nights_roll4_mean",
    "load_trend_4w",
    "is_festival_week",
    "next_week_is_festival",
]
WORKLOAD_FEATURES = WORKLOAD_CATEGORICAL + WORKLOAD_NUMERIC
ID_COLUMNS = ["department", "week_start"]


def festival_weeks(calendar: pd.DataFrame) -> pd.Series:
    """Monday week_start -> 1 if any day that week is a festival day."""
    cal = calendar.assign(date=pd.to_datetime(calendar["date"]))
    monday = cal["date"] - pd.to_timedelta(cal["date"].dt.dayofweek, unit="D")
    return cal["is_festival"].astype(bool).groupby(monday).any().astype(int)


def add_department_history(load: pd.DataFrame) -> pd.DataFrame:
    """Per-department rolling features and the next-week label; rows sorted by dept, week."""
    df = load.sort_values(ID_COLUMNS).reset_index(drop=True)
    g = df.groupby("department", sort=False)
    df["load_roll4_mean"] = g["load_ratio"].transform(
        lambda s: s.rolling(HISTORY_WEEKS, min_periods=1).mean()
    )
    df["room_nights_roll4_mean"] = g["occupied_room_nights"].transform(
        lambda s: s.rolling(HISTORY_WEEKS, min_periods=1).mean()
    )
    df["load_trend_4w"] = df["load_ratio"] - g["load_ratio"].shift(HISTORY_WEEKS)
    df[WORKLOAD_LABEL] = g["load_ratio"].shift(-1)
    next_week = g["week_start"].shift(-1)
    df["_has_next"] = next_week == df["week_start"] + pd.Timedelta(days=7)
    df["_history"] = g.cumcount()  # number of earlier weeks for this department
    return df


def build_workload_features(load: pd.DataFrame, calendar: pd.DataFrame) -> pd.DataFrame:
    """Department-week feature matrix + next-week label (see module docstring)."""
    df = add_department_history(load.assign(week_start=pd.to_datetime(load["week_start"])))
    fest = festival_weeks(calendar)
    df["week_of_year"] = df["week_start"].dt.isocalendar().week.astype(int)
    df["is_festival_week"] = df["week_start"].map(fest).fillna(0).astype(int)
    df["next_week_is_festival"] = (
        (df["week_start"] + pd.Timedelta(days=7)).map(fest).fillna(0).astype(int)
    )
    keep = (df["_history"] >= HISTORY_WEEKS) & df["_has_next"]
    return df.loc[keep, ID_COLUMNS + WORKLOAD_FEATURES[1:] + [WORKLOAD_LABEL]].reset_index(
        drop=True
    )


def load_inputs(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    return (
        pd.read_csv(data_dir / "dept_week_load_dynamic.csv"),
        pd.read_csv(data_dir / "event_calendar.csv"),
    )


def main(data_dir: Path = DATA_DIR) -> Path:
    features = build_workload_features(*load_inputs(data_dir))
    path = data_dir / "workload_features.csv"
    features.to_csv(path, index=False, date_format="%Y-%m-%d")
    print(f"SYNTHETIC workload features written: {path}")
    print(f"  {len(features)} rows = {features['department'].nunique()} departments x "
          f"{features['week_start'].nunique()} weeks, {len(WORKLOAD_FEATURES)} features, "
          f"label mean {features[WORKLOAD_LABEL].mean():.3f} "
          f"(sd {features[WORKLOAD_LABEL].std():.3f})")
    return path


if __name__ == "__main__":
    main()
