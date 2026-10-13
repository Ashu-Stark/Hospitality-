"""Attrition model features (Task T7): the T4 feature matrix plus the T5 weekly signals.

Built from SYNTHETIC output tables only (employee_v2, weekly_behaviour, weekly_signals, exits,
contract_renewals, pay_changes); never reads data/internal/. The same function scores the demo
heroes (pass their rows appended to the tables), so training and scoring share one code path.

Added signal features (all trailing, from the employee's own rows up to this week):
  weeks_since_weekend_off   consecutive weeks without a weekend off (T5 counter)
  consecutive_days_worked   longest run of working days ending this week (T5)
  weekly_off_skipped_4w     weekly offs skipped in this and the previous 3 weeks
  task_score_roll4_mean     mean task score over this and the previous 3 weeks
  task_score_trend_4w       task score this week minus 4 weeks earlier (0 if < 5 weeks)
  festival_leave_days_12w   leave days taken just before a festival in the last
                            attrition_model.festival_leave_window_weeks weeks

Segment labels (same 90-day window and censoring as build_features.add_labels):
  label_resignation   resignation exit in the window (evaluated on PERMANENT staff)
  label_contract_end  seasonal contract-end exit in the window (evaluated on SEASONAL staff)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ml.features.build_features import (
    CATEGORICAL_FEATURES,
    CENSORED,
    ID_COLUMNS,
    LABEL,
    NUMERIC_FEATURES,
    ROLL_WEEKS,
    add_labels,
    build_features,
)
from ml.generator.attrition import RESIGNATION, SEASONAL_END
from ml.generator.config import GeneratorConfig, load_config

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "attrition" / "v1"
SIGNAL_FEATURES = [
    "weeks_since_weekend_off",
    "consecutive_days_worked",
    "weekly_off_skipped_4w",
    "task_score_roll4_mean",
    "task_score_trend_4w",
    "festival_leave_days_12w",
]
MODEL_NUMERIC = NUMERIC_FEATURES + SIGNAL_FEATURES
MODEL_FEATURES = CATEGORICAL_FEATURES + MODEL_NUMERIC
SEGMENTS = {  # segment -> (contract_type evaluated, label column, exit reason)
    "resignation": ("permanent", "label_resignation", RESIGNATION),
    "contract_end": ("seasonal", "label_contract_end", SEASONAL_END),
}


def signal_features(signals: pd.DataFrame, festival_window_weeks: int) -> pd.DataFrame:
    """Trailing per-employee signal features keyed by employee_id, week_start."""
    s = signals.assign(week_start=pd.to_datetime(signals["week_start"])).sort_values(ID_COLUMNS)
    g = s.groupby("employee_id", sort=False)
    out = s[ID_COLUMNS + ["weeks_since_weekend_off", "consecutive_days_worked"]].copy()
    out["weekly_off_skipped_4w"] = g["weekly_off_skipped"].transform(
        lambda x: x.astype(int).rolling(ROLL_WEEKS, min_periods=1).sum())
    out["task_score_roll4_mean"] = g["task_score"].transform(
        lambda x: x.rolling(ROLL_WEEKS, min_periods=1).mean())
    out["task_score_trend_4w"] = (s["task_score"] - g["task_score"].shift(ROLL_WEEKS)).fillna(0.0)
    out["festival_leave_days_12w"] = g["leave_before_festival"].transform(
        lambda x: x.rolling(festival_window_weeks, min_periods=1).sum())
    return out


def build_attrition_features(
    employees: pd.DataFrame,
    behaviour: pd.DataFrame,
    signals: pd.DataFrame,
    exits: pd.DataFrame,
    renewals: pd.DataFrame | None = None,
    pay_changes: pd.DataFrame | None = None,
    cfg: GeneratorConfig | None = None,
) -> pd.DataFrame:
    """One row per active employee-week: ids, MODEL_FEATURES, censoring and segment labels."""
    cfg = cfg if cfg is not None else load_config()
    base = build_features(employees, behaviour, exits, renewals, pay_changes, cfg)
    base["week_start"] = pd.to_datetime(base["week_start"])
    sig = signal_features(signals, cfg.attrition_model.festival_leave_window_weeks)
    df = base.merge(sig, on=ID_COLUMNS, how="left", validate="one_to_one")
    horizon_end = pd.to_datetime(behaviour["week_start"]).max() + pd.Timedelta(days=7)
    for _, label, reason in SEGMENTS.values():
        df[label] = add_labels(df, exits[exits["exit_reason"] == reason], horizon_end)[LABEL]
    return df.drop(columns=[LABEL])


def segment_rows(features: pd.DataFrame, segment: str) -> pd.DataFrame:
    """Uncensored rows of the segment's contract type, with its label as `label`."""
    contract, label, _ = SEGMENTS[segment]
    rows = features[~features[CENSORED].astype(bool) & (features["contract_type"] == contract)]
    return rows.assign(label=rows[label].astype(int)).reset_index(drop=True)


def load_tables(data_dir: Path = DATA_DIR) -> dict[str, pd.DataFrame]:
    return {
        "employees": pd.read_csv(data_dir / "employee_v2.csv", keep_default_na=False),
        "behaviour": pd.read_csv(data_dir / "weekly_behaviour.csv"),
        "signals": pd.read_csv(data_dir / "weekly_signals.csv"),
        "exits": pd.read_csv(data_dir / "exits.csv"),
        "renewals": pd.read_csv(data_dir / "contract_renewals.csv"),
        "pay_changes": pd.read_csv(data_dir / "pay_changes.csv"),
    }


def load_attrition_features(data_dir: Path = DATA_DIR,
                            cfg: GeneratorConfig | None = None) -> pd.DataFrame:
    t = load_tables(data_dir)
    return build_attrition_features(t["employees"], t["behaviour"], t["signals"], t["exits"],
                                    t["renewals"], t["pay_changes"], cfg)
