"""Sanity checks and plots for the SYNTHETIC weekly behaviour and attrition data.

Run from the repo root:  python run.py validate   (or python -m ml.generator.validate_attrition)
Exits 1 if any check fails. Failures print diagnostics and suggestions only; config values
are never changed here. Task T4 signal checks (validate_signal.py) are appended to the table.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ml.generator.attrition import (  # noqa: E402
    SEASONAL_END,
    AttritionResult,
    annual_attrition_rate,
)
from ml.generator.calibrate import (  # noqa: E402
    DEFAULT_CALIBRATION_PATH,
    Calibration,
    calibrate_intercept,
    load_prior,
)
from ml.generator.config import GeneratorConfig, load_config  # noqa: E402
from ml.generator.run_occupancy import generate_daily  # noqa: E402
from ml.generator.run_staff import generate_staff  # noqa: E402
from ml.generator.validate_occupancy import (  # noqa: E402
    BLUE,
    BLUE_LIGHT,
    INK,
    INK_2,
    MUTED,
    PLOTS_DIR,
    SURFACE,
    Check,
    frame_hash,
    print_table,
    style_axes,
    year_span,
)
from ml.generator.validate_signal import (  # noqa: E402
    no_driver_info,
    probe_table,
    signal_checks,
    signal_numbers,
)

ATTRITION_RANGE = (0.20, 0.45)
PEAK_MONTHS = (5, 6)
ORANGE = "#eb6834"  # categorical slot 2 of the reference palette


def calibrate_default(cfg: GeneratorConfig) -> Calibration:
    """Rebuild Task 2/3 inputs in memory, calibrate the hazard and run the attrition process."""
    staff = generate_staff(cfg, generate_daily(cfg)[2])
    return calibrate_intercept(cfg, staff.employee, staff.employee_latent, staff.dept_week_load,
                               prior=load_prior(DEFAULT_CALIBRATION_PATH))


def simulate_default(cfg: GeneratorConfig) -> AttritionResult:
    return calibrate_default(cfg).result


def result_hash(result: AttritionResult) -> str:
    return frame_hash(
        pd.concat(
            [result.weekly_behaviour, result.exits, result.contract_renewals, result.employees,
             result.latent, result.dept_week_load_dynamic, result.pay_changes],
            keys=["behaviour", "exits", "renewals", "employees", "latent", "load", "pay"],
        )
    )


def simulated_weeks(result: AttritionResult) -> list[date]:
    return sorted(pd.to_datetime(result.dept_week_load_dynamic["week_start"]).dt.date.unique())


def expected_rows(result: AttritionResult) -> set[tuple[str, date]]:
    """(employee_id, week_start) for every week each employee is employed at least one day."""
    exit_of = dict(zip(result.exits["employee_id"], result.exits["exit_date"], strict=True))
    weeks = simulated_weeks(result)
    rows = set()
    for emp_id, hire in zip(result.employees["employee_id"], result.employees["hire_date"],
                            strict=True):
        exit_date = exit_of.get(emp_id)
        for ws in weeks:
            if hire <= ws + timedelta(days=6) and (exit_date is None or exit_date >= ws):
                rows.add((emp_id, ws))
    return rows


def effective_contract_ends(result: AttritionResult) -> dict[str, date]:
    """Seasonal employee -> contract end after following every renewal."""
    emp = result.employees
    ends = dict(zip(emp.loc[emp["contract_type"] == "seasonal", "employee_id"],
                    emp.loc[emp["contract_type"] == "seasonal", "contract_end_date"],
                    strict=True))
    for r in result.contract_renewals.sort_values("renewal_date").itertuples():
        ends[r.employee_id] = r.new_contract_end_date
    return ends


def seasonal_violations(result: AttritionResult, cfg: GeneratorConfig) -> list[str]:
    """Seasonal contracts that ended in the horizon without renewal must exit as seasonal_end."""
    if not cfg.attrition.seasonal_contract_end_is_exit:
        return []
    weeks = simulated_weeks(result)
    first, last = weeks[0], weeks[-1] + timedelta(days=6)
    exits = result.exits.set_index("employee_id")
    ends = effective_contract_ends(result)
    problems = []
    for emp_id, end in ends.items():
        exit_date = exits["exit_date"].get(emp_id)
        if first <= end <= last and (exit_date is None or exit_date >= end):
            ok = exit_date == end and exits.loc[emp_id, "exit_reason"] == SEASONAL_END
            if not ok:
                problems.append(f"{emp_id} contract ended {end} but exit is {exit_date}")
    for emp_id, r in exits[exits["exit_reason"] == SEASONAL_END].iterrows():
        if ends.get(emp_id) != r["exit_date"]:
            problems.append(f"{emp_id} seasonal_end on {r['exit_date']} != contract end")
    return problems


def vacancy_gaps(result: AttritionResult) -> pd.Series:
    hire_of = result.employees.set_index("employee_id")["hire_date"]
    replaced = result.exits["replacement_employee_id"].map(hire_of)
    return (replaced - result.exits["exit_date"]).map(lambda d: d.days if pd.notna(d) else np.nan)


def attrition_numbers(result: AttritionResult) -> dict[str, float]:
    weeks = simulated_weeks(result)
    years = len(weeks) / 52
    in_horizon = result.exits[result.exits["exit_date"] <= weeks[-1] + timedelta(days=6)]
    headcount = result.dept_week_load_dynamic.groupby("week_start")["headcount"].sum().mean()
    seasonal = int((in_horizon["exit_reason"] == SEASONAL_END).sum())
    beh = result.weekly_behaviour
    month = pd.to_datetime(beh["week_start"]).dt.month
    return {
        "rate": annual_attrition_rate(result),
        "resignation_rate": (len(in_horizon) - seasonal) / years / headcount,
        "seasonal_rate": seasonal / years / headcount,
        "mean_headcount": float(headcount),
        "pulse_peak": float(beh.loc[month.isin(PEAK_MONTHS), "pulse_score"].mean()),
        "pulse_feb": float(beh.loc[month == 2, "pulse_score"].mean()),
    }


def run_checks(result: AttritionResult, cfg: GeneratorConfig, rerun_hash: str) -> list[Check]:
    a = cfg.attrition
    beh = result.weekly_behaviour
    actual = list(zip(beh["employee_id"], beh["week_start"], strict=True))
    expected = expected_rows(result)
    exit_week = {
        (e, ws) for e, d in zip(result.exits["employee_id"], result.exits["exit_date"], strict=True)
        for ws in [d - timedelta(days=d.weekday())]
    }
    inactive = {(e, ws) for e, ws, act in zip(beh["employee_id"], beh["week_start"],
                                                beh["is_active"], strict=True) if not act}
    ot = beh["overtime_hours"]
    ot_ok = bool(ot.between(0, a.overtime_hours_cap_weekly).all()) and not (
        (ot > 0) & (beh["load_ratio"] <= a.overtime_trigger_load_ratio)
    ).any()
    n = attrition_numbers(result)
    lo, hi = ATTRITION_RANGE
    gaps = vacancy_gaps(result)
    gaps_ok = bool(gaps.between(a.vacancy_days_min, a.vacancy_days_max).all())
    seasonal_bad = seasonal_violations(result, cfg)
    min_hc = int(result.dept_week_load_dynamic["headcount"].min())
    ids = result.employees["employee_id"]
    h = result_hash(result)
    return [
        Check("one row per employed employee-week, none after exit",
              len(actual) == len(set(actual)) and set(actual) == expected,
              f"{len(actual)} rows, {len(expected)} expected"),
        Check("is_active False exactly in each exit week", inactive == exit_week,
              f"{len(inactive)} exit-week rows"),
        Check(f"overtime only when load_ratio > {a.overtime_trigger_load_ratio}, "
              f"within [0, {a.overtime_hours_cap_weekly:g}]", ot_ok, f"max {ot.max():.1f}"),
        Check("pulse_score in [1, 5]", bool(beh["pulse_score"].between(1, 5).all()),
              f"min {beh['pulse_score'].min():.2f}, max {beh['pulse_score'].max():.2f}"),
        Check(f"annualised attrition in [{lo:.0%}, {hi:.0%}]", lo <= n["rate"] <= hi,
              f"{n['rate']:.1%}"),
        Check("May-Jun mean pulse < Feb mean pulse", n["pulse_peak"] < n["pulse_feb"],
              f"{n['pulse_peak']:.3f} < {n['pulse_feb']:.3f}"),
        Check("ended seasonal contracts exit as seasonal_end", not seasonal_bad,
              "ok" if not seasonal_bad else "; ".join(seasonal_bad[:2])),
        Check(f"every exit replaced, gap in [{a.vacancy_days_min}, {a.vacancy_days_max}] days",
              gaps_ok and gaps.notna().all(), f"gaps {gaps.min():.0f}-{gaps.max():.0f}"),
        Check("department headcount never 0", min_hc > 0, f"min {min_hc}"),
        Check("employee ids unique, never reused", ids.is_unique, f"{len(ids)} ids"),
        Check("same seed -> identical hash (all outputs)", h == rerun_hash,
              f"{h[:12]} vs {rerun_hash[:12]}"),
    ]


def print_diagnostics(result: AttritionResult, cfg: GeneratorConfig) -> None:
    """Numbers and config levers when a check fails. Changes nothing."""
    a = cfg.attrition
    n = attrition_numbers(result)
    print("\nAttrition diagnostics (nothing changed):")
    print(f"  annualised attrition {n['rate']:.1%} = resignations {n['resignation_rate']:.1%}"
          f" + seasonal_end {n['seasonal_rate']:.1%} (mean headcount {n['mean_headcount']:.1f});"
          f" hazard intercept {result.intercept:.4f} (calibrated to"
          f" target_annual_attrition {cfg.target_annual_attrition})")
    print(f"  pulse: May-Jun {n['pulse_peak']:.3f}, Feb {n['pulse_feb']:.3f}")
    print("  Levers (config.yaml attrition.hazard): raise a driver's coef_* to make it more"
          " visible; raise noise_sd or coef_latent_frustration to make exits less predictable;"
          " raise attrition.visible_driver_min_logit to count fewer weak drivers as visible.")
    print(f"  Seasonal route: seasonal_renewal_prob (now {a.seasonal_renewal_prob}).")


def save_plots(result: AttritionResult, out_dir: Path = PLOTS_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    beh = result.weekly_behaviour
    month = pd.to_datetime(beh["week_start"]).dt.month

    fig, ax = plt.subplots(figsize=(10, 4.5), facecolor=SURFACE)
    groups = [beh.loc[month == m, "pulse_score"] for m in range(1, 13)]
    ax.boxplot(groups, tick_labels=[str(m) for m in range(1, 13)], widths=0.5, patch_artist=True,
               boxprops={"facecolor": BLUE_LIGHT, "edgecolor": BLUE},
               medianprops={"color": INK, "linewidth": 2},
               whiskerprops={"color": BLUE}, capprops={"color": BLUE},
               flierprops={"marker": "o", "markersize": 2, "markeredgecolor": MUTED})
    span = year_span(beh["week_start"])
    style_axes(ax, f"Weekly pulse score by month, {span} (SYNTHETIC data)", "Pulse score (1-5)")
    ax.set_xlabel("Month", color=INK_2)
    pulse_path = out_dir / "pulse_score_by_month.png"

    fig2, ax2 = plt.subplots(figsize=(10, 4.5), facecolor=SURFACE)
    weeks = simulated_weeks(result)
    in_horizon = result.exits[result.exits["exit_date"] <= weeks[-1] + timedelta(days=6)]
    exit_month = pd.to_datetime(in_horizon["exit_date"]).dt.month
    headcount = result.dept_week_load_dynamic.groupby("week_start")["headcount"].sum().mean()
    years = len(weeks) / 52
    bottom = np.zeros(12)
    for reason, color in (("resignation", BLUE), (SEASONAL_END, ORANGE)):
        counts = exit_month[in_horizon["exit_reason"] == reason].value_counts()
        rate = counts.reindex(range(1, 13), fill_value=0).to_numpy() / years / headcount * 100
        ax2.bar(range(1, 13), rate, bottom=bottom, color=color, width=0.6, label=reason,
                edgecolor=SURFACE, linewidth=2)
        bottom += rate
    ax2.set_xticks(range(1, 13))
    ax2.legend(frameon=False, labelcolor=INK_2)
    style_axes(ax2, f"Monthly attrition rate by exit reason, {span} avg (SYNTHETIC data)",
               "Exits per 100 staff per month")
    ax2.set_xlabel("Month", color=INK_2)
    rate_path = out_dir / "attrition_rate_by_month.png"

    for f, p in ((fig, pulse_path), (fig2, rate_path)):
        f.tight_layout()
        f.savefig(p, dpi=120, facecolor=SURFACE)
        plt.close(f)
    return [pulse_path, rate_path]


def main() -> int:
    cfg = load_config()
    cal = calibrate_default(cfg)
    result = cal.result
    checks = run_checks(result, cfg, result_hash(simulate_default(cfg)))
    signal = signal_numbers(result, cfg)
    checks += signal_checks(result, cfg, signal)
    print("Validation of SYNTHETIC weekly behaviour and attrition data\n")
    print_table(checks)
    print(f"\nhazard intercept {cal.intercept:.4f} ({cal.mode} search, {cal.iterations} sims) "
          f"to annual attrition {cal.achieved_rate:.3f} (target {cal.target_rate})")
    print(f"\n{no_driver_info(signal)}")
    print("\nDifficulty probes per expanding-window test year (permanent staff, 90-day gap):")
    print(probe_table(signal.predictions, signal.probes).to_string(index=False))
    n = attrition_numbers(result)
    reasons = result.exits["exit_reason"].value_counts().to_dict()
    print(f"\nannualised attrition {n['rate']:.1%} | pulse May-Jun {n['pulse_peak']:.3f} vs Feb "
          f"{n['pulse_feb']:.3f} | exits {len(result.exits)} {reasons} | "
          f"renewals {len(result.contract_renewals)}")
    failed = {c.name for c in checks if not c.passed}
    if failed:
        print_diagnostics(result, cfg)
    print()
    for p in save_plots(result):
        print(f"plot saved: {p}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
