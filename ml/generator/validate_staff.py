"""Sanity checks and plot for the SYNTHETIC staff, skills and workload data.

Run from the repo root:  python run.py validate   (or python -m ml.generator.validate_staff)
Exits 1 if any check fails. Workload failures print diagnostics and suggestions only;
config values are never changed here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from ml.generator.config import GeneratorConfig, load_config  # noqa: E402
from ml.generator.run_occupancy import generate_daily  # noqa: E402
from ml.generator.run_staff import StaffFrames, generate_staff  # noqa: E402
from ml.generator.skills import coverage_shortfalls  # noqa: E402
from ml.generator.staff import LATENT_COLUMNS  # noqa: E402
from ml.generator.validate_occupancy import (  # noqa: E402
    AXIS,
    BLUE,
    BLUE_LIGHT,
    INK,
    MUTED,
    PLOTS_DIR,
    SURFACE,
    Check,
    frame_hash,
    print_table,
    style_axes,
    year_span,
)

MEDIAN_LOAD_RANGE = (0.80, 1.00)
MIN_PEAK_LOAD = 1.10  # mean load_ratio in May-June weeks must exceed this
MAX_FEB_LOAD = 0.75  # mean load_ratio in February weeks must be below this
PEAK_MONTHS = (5, 6)

# Column-name tokens that would indicate personal or protected attributes.
FORBIDDEN_TOKENS = frozenset(
    {"name", "gender", "sex", "age", "dob", "birth", "religion", "caste", "health",
     "disability", "medical", "marital", "family", "spouse", "children", "dependents"}
)


def forbidden_columns(columns: list[str]) -> list[str]:
    """Columns whose '_'-separated tokens include a personal / protected attribute."""
    return [c for c in columns if FORBIDDEN_TOKENS & set(c.lower().split("_"))]


def frames_hash(frames: StaffFrames) -> str:
    return frame_hash(
        pd.concat(
            [frames.employee, frames.employee_latent, frames.employee_skill,
             frames.dept_week_load],
            keys=["employee", "latent", "skill", "load"],
        )
    )


def load_summary(load: pd.DataFrame) -> dict[str, float]:
    month = pd.to_datetime(load["week_start"]).dt.month
    r = load["load_ratio"]
    return {
        "median": float(r.median()),
        "peak_mean": float(r[month.isin(PEAK_MONTHS)].mean()),
        "feb_mean": float(r[month == 2].mean()),
        "max": float(r.max()),
    }


def staff_checks(frames: StaffFrames, cfg: GeneratorConfig) -> list[Check]:
    emp = frames.employee
    start = cfg.property.start
    dept_counts = emp.groupby("department").size().to_dict()
    role_counts = emp.groupby(["department", "role"]).size().to_dict()
    want_roles = {(d, r): s.count for d, roles in cfg.roles.items() for r, s in roles.items()}
    heads = emp[emp["is_department_head"]]
    head_of = dict(zip(heads["department"], heads["employee_id"], strict=True))
    non_heads = emp[~emp["is_department_head"]]
    bad_mgr = non_heads[non_heads["manager_id"] != non_heads["department"].map(head_of)]
    hire = pd.to_datetime(emp["hire_date"])
    seasonal = emp[emp["contract_type"] == "seasonal"]
    permanent = emp[emp["contract_type"] == "permanent"]
    seasonal_end = pd.to_datetime(seasonal["contract_end_date"])
    shortfalls = coverage_shortfalls(emp, frames.employee_skill, cfg)
    leaked = sorted(set(LATENT_COLUMNS) & set(emp.columns))
    personal = forbidden_columns(list(emp.columns))
    heads_per_dept = heads.groupby("department").size()
    return [
        Check(f"{cfg.staff_target} employees", len(emp) == cfg.staff_target, f"{len(emp)}"),
        Check("department counts match config", dept_counts == cfg.departments,
              "ok" if dept_counts == cfg.departments else f"{dept_counts}"),
        Check("role counts match config", role_counts == want_roles,
              f"{len(role_counts)} roles"),
        Check("exactly one head per department",
              set(heads_per_dept.index) == set(cfg.departments) and (heads_per_dept == 1).all(),
              f"{len(heads)} heads"),
        Check("non-heads managed by own dept head", bad_mgr.empty, f"{len(bad_mgr)} bad"),
        Check("all hire_date < property start", bool((hire < pd.Timestamp(start)).all()),
              f"latest {hire.max().date()}"),
        Check("all monthly_pay > 0", bool((emp["monthly_pay"] > 0).all()),
              f"min {emp['monthly_pay'].min()}"),
        Check("seasonal contract_end_date after start",
              bool((seasonal_end > pd.Timestamp(start)).all()), f"{len(seasonal)} seasonal"),
        Check("permanent contract_end_date empty",
              bool(permanent["contract_end_date"].isna().all()), f"{len(permanent)} permanent"),
        Check("skill coverage guarantee holds", not shortfalls,
              "ok" if not shortfalls else "; ".join(shortfalls[:3])),
        Check("employee.csv has no latent columns", not leaked, f"{leaked or 'none'}"),
        Check("employee.csv has no personal/protected columns", not personal,
              f"{personal or 'none'}"),
    ]


def workload_checks(load: pd.DataFrame) -> list[Check]:
    s = load_summary(load)
    lo, hi = MEDIAN_LOAD_RANGE
    return [
        Check(f"median load_ratio in [{lo:.2f}, {hi:.2f}]", lo <= s["median"] <= hi,
              f"{s['median']:.3f}"),
        Check(f"May-Jun mean load_ratio > {MIN_PEAK_LOAD:.2f}", s["peak_mean"] > MIN_PEAK_LOAD,
              f"{s['peak_mean']:.3f}"),
        Check(f"Feb mean load_ratio < {MAX_FEB_LOAD:.2f}", s["feb_mean"] < MAX_FEB_LOAD,
              f"{s['feb_mean']:.3f}"),
    ]


def print_workload_diagnostics(load: pd.DataFrame, cfg: GeneratorConfig) -> None:
    """Per-department numbers and which config values drive them. Changes nothing."""
    month = pd.to_datetime(load["week_start"]).dt.month
    rows = []
    for dept, g in load.groupby("department", sort=False):
        m = month[g.index]
        std = cfg.workload[dept]
        rows.append({
            "department": dept,
            "median": round(g["load_ratio"].median(), 3),
            "may_jun": round(g.loc[m.isin(PEAK_MONTHS), "load_ratio"].mean(), 3),
            "feb": round(g.loc[m == 2, "load_ratio"].mean(), 3),
            "base_hours": std.base_hours,
            "per_rn_hours": std.per_occupied_room_night_hours,
            "available_h": g["available_hours"].iloc[0],
            "x_to_median_0.90": round(0.90 / g["load_ratio"].median(), 2),
        })
    print("\nWorkload diagnostics (nothing changed):")
    print(pd.DataFrame(rows).to_string(index=False))
    print(
        "\nload_ratio = (base_hours + per_occupied_room_night_hours * room_nights)"
        " / (headcount * staff.standard_weekly_hours)."
        "\nSuggestion: the workload.* standards in config.yaml are placeholders and too low for"
        " the headcount.\n  - Level: multiply a department's standards by 'x_to_median_0.90'"
        " to bring its median near 0.90.\n  - Seasonality: May-Jun > 1.10 and Feb < 0.75 needs"
        " May-Jun/Feb >= 1.47, so most hours must come from per_occupied_room_night_hours,"
        "\n    not base_hours (security has per-room hours 0, so its ratio is flat)."
        "\n  Confirm real standards with the HM student before changing them."
    )


def save_load_plot(load: pd.DataFrame, out_dir: Path = PLOTS_DIR) -> Path:
    """Boxplot of weekly load_ratio by month, one facet per department."""
    out_dir.mkdir(parents=True, exist_ok=True)
    depts = list(dict.fromkeys(load["department"]))
    month = pd.to_datetime(load["week_start"]).dt.month
    ncols = 3
    nrows = -(-len(depts) // ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(14, 4 * nrows), sharey=True,
                             facecolor=SURFACE, squeeze=False)
    for ax, dept in zip(axes.flat, depts, strict=False):
        g = load[load["department"] == dept]
        groups = [g.loc[month[g.index] == m, "load_ratio"] for m in range(1, 13)]
        ax.boxplot(groups, tick_labels=[str(m) for m in range(1, 13)], widths=0.5,
                   patch_artist=True,
                   boxprops={"facecolor": BLUE_LIGHT, "edgecolor": BLUE},
                   medianprops={"color": INK, "linewidth": 2},
                   whiskerprops={"color": BLUE}, capprops={"color": BLUE},
                   flierprops={"marker": "o", "markersize": 3, "markeredgecolor": MUTED})
        ax.axhline(1.0, color=AXIS, linewidth=1, linestyle="--")
        style_axes(ax, dept, "load_ratio")
    for ax in list(axes.flat)[len(depts):]:
        ax.set_visible(False)
    fig.suptitle(f"Weekly load_ratio by month and department, {year_span(load['week_start'])}"
                 " (SYNTHETIC data)"
                 "  - dashed line = capacity", x=0.01, ha="left", color=INK)
    fig.tight_layout()
    path = out_dir / "load_ratio_by_month.png"
    fig.savefig(path, dpi=110, facecolor=SURFACE)
    plt.close(fig)
    return path


def main() -> int:
    cfg = load_config()
    occupancy = generate_daily(cfg)[2]
    frames = generate_staff(cfg, occupancy)
    rerun = generate_staff(cfg, occupancy)
    checks = staff_checks(frames, cfg)
    h1, h2 = frames_hash(frames), frames_hash(rerun)
    checks.append(Check("same seed -> identical hash", h1 == h2, f"{h1[:12]} vs {h2[:12]}"))
    load_results = workload_checks(frames.dept_week_load)
    checks += load_results
    print("Validation of SYNTHETIC staff, skills and workload data\n")
    print_table(checks)
    s = load_summary(frames.dept_week_load)
    print(f"\nload_ratio: median {s['median']:.3f}, May-Jun mean {s['peak_mean']:.3f}, "
          f"Feb mean {s['feb_mean']:.3f}, max {s['max']:.3f}")
    if not all(c.passed for c in load_results):
        print_workload_diagnostics(frames.dept_week_load, cfg)
    print(f"\nplot saved: {save_load_plot(frames.dept_week_load)}")
    return 0 if all(c.passed for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
