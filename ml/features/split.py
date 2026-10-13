"""Time-based train / validation / test split of the SYNTHETIC feature matrix.

Splits by week_start, never randomly: first ~60% of weeks train, next ~20% validation,
final ~20% test. An embargo of LABEL_WEEKS weeks (the label horizon, rounded up to whole
weeks) is dropped from the END of train and of validation, because those rows' label windows
would otherwise look into the next split (e.g. a train row labelled 1 because the same employee
exits during validation). Censored rows (label window past the end of the data) are excluded
before splitting.

Other feature sets (Task 6 pulse) reuse the SAME week windows via split_like(), with the
attrition split rebuilt in memory as the reference, so every model is judged on one calendar.

Run: python -m ml.features.split             (attrition features)
     python -m ml.features.split pulse       (pulse features, Task 5 windows)
     python -m ml.features.split workload    (department-week workload features, Task 5 windows)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ml.features.build_features import (
    CENSORED,
    DATA_DIR,
    LABEL,
    LABEL_WEEKS,
    build_features,
    load_inputs,
)

FRACTIONS = (0.6, 0.2, 0.2)


@dataclass(frozen=True)
class Splits:
    train: pd.DataFrame
    val: pd.DataFrame
    test: pd.DataFrame

    def items(self) -> list[tuple[str, pd.DataFrame]]:
        return [("train", self.train), ("val", self.val), ("test", self.test)]


def time_split(features: pd.DataFrame, embargo_weeks: int = LABEL_WEEKS) -> Splits:
    """Drop censored rows, assign whole weeks to splits in time order, drop embargo weeks."""
    df = features.assign(week_start=pd.to_datetime(features["week_start"]))
    if CENSORED in df:
        df = df[~df[CENSORED].astype(bool)]
    weeks = sorted(df["week_start"].unique())
    n = len(weeks)
    n_train, n_val = round(n * FRACTIONS[0]), round(n * FRACTIONS[1])
    train_weeks = weeks[: max(n_train - embargo_weeks, 1)]
    val_weeks = weeks[n_train : max(n_train + n_val - embargo_weeks, n_train + 1)]
    test_weeks = weeks[n_train + n_val :]
    pick = df["week_start"].isin
    return Splits(
        train=df[pick(train_weeks)].reset_index(drop=True),
        val=df[pick(val_weeks)].reset_index(drop=True),
        test=df[pick(test_weeks)].reset_index(drop=True),
    )


def describe(splits: Splits) -> pd.DataFrame:
    rows = []
    for name, part in splits.items():
        rows.append({
            "split": name,
            "first_week": part["week_start"].min().date(),
            "last_week": part["week_start"].max().date(),
            "weeks": part["week_start"].nunique(),
            "rows": len(part),
            "positives": int(part[LABEL].sum()),
            "positive_rate": round(part[LABEL].mean(), 4),
        })
    return pd.DataFrame(rows)


def split_like(features: pd.DataFrame, reference: Splits) -> Splits:
    """Split another feature set into the reference's week windows [first, last] per split.

    Weeks outside every window (the embargo gaps, and anything after the reference test
    split) are dropped, so the windows never overlap.
    """
    df = features.assign(week_start=pd.to_datetime(features["week_start"]))

    def window(part: pd.DataFrame) -> pd.DataFrame:
        lo, hi = part["week_start"].min(), part["week_start"].max()
        return df[df["week_start"].between(lo, hi)].reset_index(drop=True)

    return Splits(train=window(reference.train), val=window(reference.val),
                  test=window(reference.test))


def describe_ranges(splits: Splits, label: str) -> pd.DataFrame:
    """Week ranges, row counts and label mean (for any label, including continuous ones)."""
    return pd.DataFrame([
        {
            "split": name,
            "first_week": part["week_start"].min().date(),
            "last_week": part["week_start"].max().date(),
            "weeks": part["week_start"].nunique(),
            "rows": len(part),
            "label_mean": round(part[label].mean(), 4),
        }
        for name, part in splits.items()
    ])


def task5_reference_splits(data_dir: Path = DATA_DIR) -> Splits:
    """The attrition (Task 5) split, rebuilt in memory so features.csv need not exist."""
    return time_split(build_features(*load_inputs(data_dir)))


def load_splits(data_dir: Path = DATA_DIR) -> Splits:
    return time_split(pd.read_csv(data_dir / "features.csv"))


def load_pulse_splits(data_dir: Path = DATA_DIR) -> Splits:
    pulse = pd.read_csv(data_dir / "pulse_features.csv")
    return split_like(pulse, task5_reference_splits(data_dir))


def main_pulse(data_dir: Path = DATA_DIR) -> Splits:
    from ml.features.build_pulse_features import PULSE_LABEL

    splits = load_pulse_splits(data_dir)
    print("Time-based split of SYNTHETIC pulse features (same week windows as Task 5):")
    print(describe_ranges(splits, PULSE_LABEL).to_string(index=False))
    return splits


def load_workload_splits(data_dir: Path = DATA_DIR) -> Splits:
    workload = pd.read_csv(data_dir / "workload_features.csv")
    return split_like(workload, task5_reference_splits(data_dir))


def main_workload(data_dir: Path = DATA_DIR) -> Splits:
    from ml.features.build_workload_features import WORKLOAD_LABEL

    splits = load_workload_splits(data_dir)
    table = describe_ranges(splits, WORKLOAD_LABEL)
    table.insert(4, "departments", [p["department"].nunique() for _, p in splits.items()])
    print("Time-based split of SYNTHETIC workload features (department-weeks, same week "
          "windows as Task 5):")
    print(table.to_string(index=False))
    return splits


def main(data_dir: Path = DATA_DIR) -> Splits:
    splits = load_splits(data_dir)
    print(f"Time-based split of SYNTHETIC features (embargo {LABEL_WEEKS} weeks after train "
          "and after val):")
    print(describe(splits).to_string(index=False))
    return splits


if __name__ == "__main__":
    {"pulse": main_pulse, "workload": main_workload}.get(" ".join(sys.argv[1:]), main)()
