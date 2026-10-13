"""Build the attrition feature matrix from SYNTHETIC Task 3/4 outputs.

Inputs (data/): employee_v2.csv, weekly_behaviour.csv, exits.csv, contract_renewals.csv,
pay_changes.csv. Never reads data/internal/.

Rows: one per employee-week where the employee is still employed at the end of the week
(weekly_behaviour.is_active == True). The prediction is made at the END of that week.

Features (all observable by the hotel at prediction time):
  categorical: department, role, contract_type
  numeric:
    is_department_head       0/1
    tenure_days              week_start - hire_date (computed, not stored)
    monthly_pay              pay in force at week_start (hire pay + pay_changes so far), INR
    pay_ratio                monthly_pay / the role's pay_mean (config.yaml roles)
    months_since_raise       (week_start - latest raise on or before week_start) / 30.44
    load_ratio               this week's dynamic department load
    overtime_hours           this week
    overtime_roll4_mean      mean overtime over this and the previous 3 weeks
    overtime_window_mean     mean overtime over the last attrition.hazard.overtime_window_weeks
                             weeks (the hazard's "sustained overtime"; fewer at the start)
    leave_days               this week
    weeks_without_leave      consecutive weeks up to and including this one with no leave
    pulse_score              this week (1-5)
    pulse_roll4_mean         mean pulse over this and the previous 3 weeks
    pulse_trend_4w           pulse this week minus pulse 4 weeks earlier (0 if < 5 weeks)
    peer_exits               department exits in [week_start - peer window, week_start)
    days_until_contract_end  min(days to the contract end in force, label horizon); permanent
                             staff are always at the cap
  Rolling and counter features only use the employee's own rows up to this week; pay, raises
  and contract renewals only use records dated on or before week_start.

  days_until_contract_end is not leakage: the hotel knows every contract's end date and every
  renewal it has already agreed (renewals dated after week_start are ignored). It says when a
  contract is due to end, never whether it will be renewed. It is capped at the label horizon:
  an end further out cannot cause an exit inside the label window, and a huge sentinel for
  permanent staff would dominate a linear model's coefficient.

Label: exits_within_horizon = 1 if exit_date (exits.csv) falls in the label_horizon_days
(config.yaml, 90) AFTER this row's week, i.e. week_start + 7 <= exit_date < week_start + 7 +
horizon. Computed from exits.csv only, never from a hazard value.

Censoring: rows whose label window runs past the last simulated week are kept but marked
is_censored = True with an empty label (exits after the horizon are unobserved). The time split
excludes them from training, validation and test.

Output: data/features.csv with employee_id, week_start, department, role, the features,
is_censored and the label.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from ml.generator.config import GeneratorConfig, load_config

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
LABEL = "exits_within_horizon"
CENSORED = "is_censored"
ROLL_WEEKS = 4
DAYS_PER_MONTH = 30.44

_CFG = load_config()
HORIZON_DAYS = _CFG.label_horizon_days
LABEL_WEEKS = math.ceil(HORIZON_DAYS / 7)  # embargo between time splits, in weeks
CONTRACT_END_CAP_DAYS = HORIZON_DAYS

CATEGORICAL_FEATURES = ["department", "role", "contract_type"]
NUMERIC_FEATURES = [
    "is_department_head",
    "tenure_days",
    "monthly_pay",
    "pay_ratio",
    "months_since_raise",
    "load_ratio",
    "overtime_hours",
    "overtime_roll4_mean",
    "overtime_window_mean",
    "leave_days",
    "weeks_without_leave",
    "pulse_score",
    "pulse_roll4_mean",
    "pulse_trend_4w",
    "peer_exits",
    "days_until_contract_end",
]
FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES
ID_COLUMNS = ["employee_id", "week_start"]

# Generator-only hidden traits that must never become features (see CLAUDE.md).
LATENT_NAMES = ("overtime_propensity", "baseline_pulse", "baseline_task_score",
                "latent_frustration")

EMPTY_RENEWALS = ("employee_id", "renewal_date", "new_contract_end_date")
EMPTY_PAY_CHANGES = ("employee_id", "effective_date", "monthly_pay")


def _dates(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s)


def _ns(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s).astype("datetime64[ns]")


def _weeks_without(flag_leave: pd.Series) -> pd.Series:
    """Running count of consecutive weeks without leave (resets to 0 in a leave week)."""
    out, n = [], 0
    for took_leave in flag_leave:
        n = 0 if took_leave else n + 1
        out.append(n)
    return pd.Series(out, index=flag_leave.index)


def add_rolling_features(
    behaviour: pd.DataFrame, overtime_window: int = _CFG.attrition.hazard.overtime_window_weeks
) -> pd.DataFrame:
    """Per-employee trailing features; rows must be one per employee-week.

    overtime_window defaults to the configured sustained-overtime window, so callers that only
    need the 4-week features (e.g. the pulse features) need not pass it.
    """
    df = behaviour.sort_values(ID_COLUMNS).copy()
    g = df.groupby("employee_id", sort=False)
    df["pulse_roll4_mean"] = g["pulse_score"].transform(
        lambda s: s.rolling(ROLL_WEEKS, min_periods=1).mean()
    )
    df["overtime_roll4_mean"] = g["overtime_hours"].transform(
        lambda s: s.rolling(ROLL_WEEKS, min_periods=1).mean()
    )
    df["overtime_window_mean"] = g["overtime_hours"].transform(
        lambda s: s.rolling(overtime_window, min_periods=1).mean()
    )
    df["pulse_trend_4w"] = (df["pulse_score"] - g["pulse_score"].shift(ROLL_WEEKS)).fillna(0.0)
    df["weeks_without_leave"] = g["leave_days"].transform(lambda s: _weeks_without(s > 0))
    return df


def _asof(rows: pd.DataFrame, events: pd.DataFrame, on: str, value: str) -> pd.Series:
    """Latest `value` per employee with event date `on` <= row week_start (NaN if none)."""
    if events.empty:
        return pd.Series(np.nan, index=rows.index, dtype=object)
    ev = events.assign(_key=_ns(events[on]), _value=events[value]).sort_values("_key")
    left = rows[["employee_id", "week_start"]].reset_index()
    left["week_start"] = _ns(left["week_start"])
    matched = pd.merge_asof(
        left.sort_values("week_start"), ev[["employee_id", "_key", "_value"]],
        left_on="week_start", right_on="_key", by="employee_id", direction="backward",
    ).set_index("index")["_value"]
    return matched.reindex(rows.index)


def contract_end_in_force(
    rows: pd.DataFrame, employees: pd.DataFrame, renewals: pd.DataFrame
) -> pd.Series:
    """Contract end known at each row's week_start (NaT for permanent staff).

    Initial end from employee contract_end_date, replaced by the latest renewal whose
    renewal_date <= week_start (point-in-time; future renewals are never used).
    """
    initial = _ns(employees.set_index("employee_id")["contract_end_date"].replace("", None))
    end = pd.Series(initial.reindex(rows["employee_id"]).to_numpy(), index=rows.index)
    renewed = _ns(_asof(rows, renewals, "renewal_date", "new_contract_end_date"))
    return renewed.fillna(end)


def days_until_contract_end(
    rows: pd.DataFrame, employees: pd.DataFrame, renewals: pd.DataFrame
) -> pd.Series:
    end = contract_end_in_force(rows, employees, renewals)
    days = (end - _ns(rows["week_start"])).dt.days
    return days.fillna(CONTRACT_END_CAP_DAYS).clip(upper=CONTRACT_END_CAP_DAYS).astype(int)


def add_pay_features(
    rows: pd.DataFrame, staff: pd.DataFrame, pay_changes: pd.DataFrame, cfg: GeneratorConfig
) -> pd.DataFrame:
    """Point-in-time monthly_pay, pay_ratio and months_since_raise."""
    changed_pay = _asof(rows, pay_changes, "effective_date", "monthly_pay")
    raised_on = _ns(_asof(rows, pay_changes, "effective_date", "effective_date"))
    pay = changed_pay.fillna(pd.Series(staff["monthly_pay"].to_numpy(), index=rows.index))
    last_raise = raised_on.fillna(pd.Series(_ns(staff["last_raise_date"]).to_numpy(),
                                            index=rows.index))
    role_mean = [cfg.roles[d][r].pay_mean for d, r in zip(rows["department"], rows["role"],
                                                          strict=True)]
    return rows.assign(
        monthly_pay=pay.astype(float),
        pay_ratio=(pay.astype(float) / np.array(role_mean)).round(4),
        months_since_raise=((_ns(rows["week_start"]) - last_raise).dt.days
                            / DAYS_PER_MONTH).round(2),
    )


def peer_exit_counts(
    rows: pd.DataFrame, employees: pd.DataFrame, exits: pd.DataFrame, window_weeks: int
) -> pd.Series:
    """Department exits with exit_date in [week_start - window, week_start)."""
    dept_of = employees.set_index("employee_id")["department"]
    ex = exits.assign(exit_date=_ns(exits["exit_date"]),
                      department=exits["employee_id"].map(dept_of))
    out = pd.Series(0, index=rows.index, dtype=int)
    ws = _ns(rows["week_start"])
    for dept, idx in rows.groupby("department").groups.items():
        dates = np.sort(ex.loc[ex["department"] == dept, "exit_date"].to_numpy())
        hi = ws.loc[idx].to_numpy()
        lo = hi - np.timedelta64(window_weeks * 7, "D")
        out.loc[idx] = np.searchsorted(dates, hi, "left") - np.searchsorted(dates, lo, "left")
    return out


def add_labels(rows: pd.DataFrame, exits: pd.DataFrame, horizon_end: pd.Timestamp) -> pd.DataFrame:
    """Label (exit in the horizon after the row's week) and the censoring flag."""
    exit_of = exits.set_index("employee_id")["exit_date"].pipe(_ns)
    # reindex (not .map) so an empty exits table works too; non-leavers get NaT.
    exit_date = pd.Series(exit_of.reindex(rows["employee_id"]).to_numpy(), index=rows.index)
    start = _ns(rows["week_start"]) + pd.Timedelta(days=7)
    end = start + pd.Timedelta(days=HORIZON_DAYS)
    label = ((exit_date >= start) & (exit_date < end)).astype(float)
    censored = end > horizon_end
    return rows.assign(**{CENSORED: censored, LABEL: label.where(~censored)})


def build_features(
    employees: pd.DataFrame,
    behaviour: pd.DataFrame,
    exits: pd.DataFrame,
    renewals: pd.DataFrame | None = None,
    pay_changes: pd.DataFrame | None = None,
    cfg: GeneratorConfig | None = None,
) -> pd.DataFrame:
    """Feature matrix + label + censoring flag (see module docstring for definitions)."""
    cfg = cfg if cfg is not None else _CFG
    renewals = renewals if renewals is not None else pd.DataFrame(columns=EMPTY_RENEWALS)
    pay_changes = (pay_changes if pay_changes is not None
                   else pd.DataFrame(columns=EMPTY_PAY_CHANGES))
    beh = behaviour.assign(week_start=_ns(behaviour["week_start"]))
    horizon_end = beh["week_start"].max() + pd.Timedelta(days=7)  # day after last week
    beh = add_rolling_features(beh, cfg.attrition.hazard.overtime_window_weeks)
    beh = beh.reset_index(drop=True)

    staff = employees.set_index("employee_id").loc[beh["employee_id"]].reset_index(drop=True)
    beh["contract_type"] = staff["contract_type"]
    beh["is_department_head"] = staff["is_department_head"].astype(bool).astype(int)
    beh["tenure_days"] = (beh["week_start"] - _ns(staff["hire_date"])).dt.days
    beh = add_pay_features(beh, staff, pay_changes, cfg)
    beh["peer_exits"] = peer_exit_counts(
        beh, employees, exits, cfg.attrition.hazard.peer_exit_window_weeks
    )
    beh["days_until_contract_end"] = days_until_contract_end(beh, employees, renewals)

    active = beh[beh["is_active"].astype(bool)]
    labelled = add_labels(active, exits, horizon_end)
    return labelled[ID_COLUMNS + FEATURES + [CENSORED, LABEL]].reset_index(drop=True)


def load_inputs(data_dir: Path) -> tuple[pd.DataFrame, ...]:
    return (
        pd.read_csv(data_dir / "employee_v2.csv", keep_default_na=False),
        pd.read_csv(data_dir / "weekly_behaviour.csv"),
        pd.read_csv(data_dir / "exits.csv"),
        pd.read_csv(data_dir / "contract_renewals.csv"),
        pd.read_csv(data_dir / "pay_changes.csv"),
    )


def main(data_dir: Path = DATA_DIR) -> Path:
    features = build_features(*load_inputs(data_dir))
    path = data_dir / "features.csv"
    features.to_csv(path, index=False, date_format="%Y-%m-%d")
    usable = features[~features[CENSORED]]
    print(f"SYNTHETIC features written: {path}")
    print(f"  {len(features)} rows ({int(features[CENSORED].sum())} censored, last "
          f"{HORIZON_DAYS} days), {features['employee_id'].nunique()} employees, "
          f"{len(FEATURES)} features, label horizon {HORIZON_DAYS} days, positive rate "
          f"{usable[LABEL].mean():.2%} ({int(usable[LABEL].sum())} positives)")
    return path


if __name__ == "__main__":
    main()
