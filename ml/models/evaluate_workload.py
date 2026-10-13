"""Compare the naive workload baseline with the trained workload model on the TEST split.

Flag (printed, exit code 1 so train-workload does not proceed silently): the trained model does
NOT beat the naive baseline on test MAE.
"""

from __future__ import annotations

import sys
from pathlib import Path

import joblib
import pandas as pd

from ml.features.split import Splits, load_workload_splits
from ml.models.common import MODEL_FILE, WORKLOAD_ARTIFACT_DIR
from ml.models.workload_common import naive_workload, regression_metrics, workload_xy

MODEL_NAME = "workload_model"


def compare(splits: Splits, models_dir: Path = WORKLOAD_ARTIFACT_DIR) -> pd.DataFrame:
    test = splits.test
    x, y = workload_xy(test)
    model = joblib.load(models_dir / MODEL_FILE)
    rows = [
        {"model": "naive (copy this week)", **regression_metrics(y, naive_workload(test))},
        {"model": MODEL_NAME, **regression_metrics(y, model.predict(x))},
    ]
    return pd.DataFrame(rows).drop(columns="rows")


def flags_for(table: pd.DataFrame) -> list[str]:
    naive, trained = table.iloc[0], table.iloc[1]
    if trained["mae"] >= naive["mae"]:
        return [f"NOT BETTER: {MODEL_NAME} test MAE {trained['mae']:.4f} >= naive "
                f"{naive['mae']:.4f}"]
    return []


def main(splits: Splits | None = None, models_dir: Path = WORKLOAD_ARTIFACT_DIR) -> int:
    splits = splits if splits is not None else load_workload_splits()
    table = compare(splits, models_dir)
    print("Workload model vs naive baseline on the TEST split (SYNTHETIC data):")
    print(table.to_string(index=False))
    naive_mae, model_mae = table["mae"].iloc[0], table["mae"].iloc[1]
    print(f"\nMAE change vs naive: {model_mae - naive_mae:+.4f} "
          f"({(model_mae - naive_mae) / naive_mae:+.1%})")
    flags = flags_for(table)
    print("\nFlags:")
    for f in flags or ["none (trained model beats naive on test MAE)"]:
        print(f"  {f}")
    return 1 if flags else 0


if __name__ == "__main__":
    sys.exit(main())
