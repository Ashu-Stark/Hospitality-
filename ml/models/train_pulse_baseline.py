"""Naive pulse baseline (SYNTHETIC data): next week's pulse_score = this week's pulse_score.

No model is fitted. This is the bar every real pulse model must beat.
"""

from __future__ import annotations

from pathlib import Path

from ml.features.split import Splits, load_pulse_splits
from ml.models.pulse_common import (
    naive_prediction,
    print_regression,
    pulse_xy,
    regression_metrics,
    save_metrics,
)

NAME = "pulse_naive"


def evaluate_naive(splits: Splits) -> dict:
    metrics: dict = {"model": NAME, "rule": "next_week_pulse_score = pulse_score"}
    for name, part in (("val", splits.val), ("test", splits.test)):
        _, y = pulse_xy(part)
        metrics[name] = regression_metrics(y, naive_prediction(part))
    return metrics


def main(splits: Splits | None = None, metrics_dir: Path | None = None) -> dict:
    splits = splits if splits is not None else load_pulse_splits()
    metrics = evaluate_naive(splits)
    path = save_metrics(metrics, NAME) if metrics_dir is None else save_metrics(
        metrics, NAME, metrics_dir)
    print("Naive pulse baseline (SYNTHETIC data): predict next week = this week")
    print_regression(NAME, metrics)
    print(f"  metrics saved: {path}")
    return metrics


if __name__ == "__main__":
    main()
