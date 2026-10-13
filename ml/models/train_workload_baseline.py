"""Naive workload baseline (SYNTHETIC data): next week's load_ratio = this week's load_ratio.

No model is fitted. This is the bar the real workload model must beat.
"""

from __future__ import annotations

from pathlib import Path

from ml.features.split import Splits, load_workload_splits
from ml.models.workload_common import (
    naive_workload,
    print_regression,
    regression_metrics,
    save_metrics,
    workload_xy,
)

NAME = "workload_naive"


def evaluate_naive(splits: Splits) -> dict:
    metrics: dict = {"model": NAME, "rule": "next_week_load_ratio = load_ratio"}
    for name, part in (("val", splits.val), ("test", splits.test)):
        _, y = workload_xy(part)
        metrics[name] = regression_metrics(y, naive_workload(part))
    return metrics


def main(splits: Splits | None = None, metrics_dir: Path | None = None) -> dict:
    splits = splits if splits is not None else load_workload_splits()
    metrics = evaluate_naive(splits)
    path = save_metrics(metrics, NAME) if metrics_dir is None else save_metrics(
        metrics, NAME, metrics_dir)
    print("Naive workload baseline (SYNTHETIC data): predict next week = this week")
    print_regression(NAME, metrics)
    print(f"  metrics saved: {path}")
    return metrics


if __name__ == "__main__":
    main()
