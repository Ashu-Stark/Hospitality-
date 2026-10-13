"""Sanity checks and plots for the SYNTHETIC daily occupancy data.

Run from the repo root:  python run.py validate   (or python -m ml.generator.validate_occupancy)
Exits 1 if any check fails.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ml.generator.config import GeneratorConfig, load_config  # noqa: E402
from ml.generator.run_occupancy import generate_daily  # noqa: E402

PLOTS_DIR = Path(__file__).resolve().parents[1] / "docs" / "plots"
MAPE_RANGE = (0.08, 0.35)
SEASONAL_LAG_DAYS = 364  # 52 weeks, so the weekday matches
PEAK_MONTHS = (5, 6)
MAX_PEAK_SOLD_OUT_SHARE = 0.15
MAX_PEAK_MEAN = 0.88

# Reference palette (dataviz skill): one series hue, text inks, recessive grid/axes.
BLUE, BLUE_LIGHT = "#2a78d6", "#86b6ef"
SURFACE, INK, INK_2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def frame_hash(df: pd.DataFrame) -> str:
    """SHA-256 of the CSV serialisation, so dtype or value changes alter the hash."""
    return hashlib.sha256(df.to_csv(index=False).encode("utf-8")).hexdigest()


def seasonal_naive_mape(daily: pd.DataFrame, year: int, lag_days: int = SEASONAL_LAG_DAYS) -> float:
    """MAPE of predicting each day in `year` with the value `lag_days` earlier."""
    y = daily.set_index("date")["occupancy_pct"]
    actual = y[y.index.year == year]
    pred = y.reindex(actual.index - pd.Timedelta(days=lag_days)).to_numpy()
    return float(np.mean(np.abs(actual.to_numpy() - pred) / actual.to_numpy()))


def sold_out_share(daily: pd.DataFrame, rooms: int, months: tuple[int, ...]) -> float:
    """Share of days in `months` where every room was sold."""
    in_months = daily[daily["month"].isin(months)]
    return float((in_months["rooms_sold"] == rooms).mean())


def busiest_other_month(daily: pd.DataFrame, exclude: tuple[int, ...]) -> tuple[int, float]:
    """(month, mean occupancy) of the busiest calendar month not in `exclude`."""
    by_month = daily.groupby("month")["occupancy_pct"].mean().drop(list(exclude))
    return int(by_month.idxmax()), float(by_month.max())


def run_checks(daily: pd.DataFrame, cfg: GeneratorConfig, rerun_hash: str) -> list[Check]:
    occ = daily["occupancy_pct"]
    month, dow = daily["month"], daily["day_of_week"]
    h = frame_hash(daily)
    may_jun, feb = occ[month.isin([5, 6])].mean(), occ[month == 2].mean()
    fri_sat, mon_thu = occ[dow.isin([4, 5])].mean(), occ[dow.isin([0, 1, 2, 3])].mean()
    n_nan = int(daily.isna().sum().sum())
    rooms = cfg.property.rooms
    rs = daily["rooms_sold"]
    year3 = int(daily["date"].dt.year.max())
    mape = seasonal_naive_mape(daily, year3)
    lo, hi = MAPE_RANGE
    sold_out = sold_out_share(daily, rooms, PEAK_MONTHS)
    rival_month, rival_mean = busiest_other_month(daily, PEAK_MONTHS)
    return [
        Check("same seed -> identical hash", h == rerun_hash, f"{h[:12]} vs {rerun_hash[:12]}"),
        Check("May-Jun mean occupancy > 0.80", may_jun > 0.80, f"{may_jun:.3f}"),
        Check(f"May-Jun mean occupancy <= {MAX_PEAK_MEAN:.2f}", may_jun <= MAX_PEAK_MEAN,
              f"{may_jun:.3f}"),
        Check("May-Jun is the highest month by mean occupancy", may_jun > rival_mean,
              f"{may_jun:.3f} > month {rival_month} {rival_mean:.3f}"),
        Check(f"sold-out share of May-Jun days < {MAX_PEAK_SOLD_OUT_SHARE:.0%}",
              sold_out < MAX_PEAK_SOLD_OUT_SHARE, f"{sold_out:.1%}"),
        Check("Feb mean occupancy < 0.40", feb < 0.40, f"{feb:.3f}"),
        Check("Fri/Sat mean > Mon-Thu mean", fri_sat > mon_thu, f"{fri_sat:.3f} > {mon_thu:.3f}"),
        Check("no NaN values", n_nan == 0, f"{n_nan} NaN"),
        Check("occupancy_pct in [0, 1]", bool(occ.between(0, 1).all()),
              f"min {occ.min():.3f}, max {occ.max():.3f}"),
        Check(f"rooms_sold in [0, {rooms}]", bool(rs.between(0, rooms).all()),
              f"min {rs.min()}, max {rs.max()}"),
        Check(f"seasonal-naive MAPE {year3} in [{lo:.0%}, {hi:.0%}]", lo <= mape <= hi,
              f"{mape:.2%}"),
    ]


def print_table(checks: list[Check]) -> None:
    width = max(len(c.name) for c in checks)
    print(f"{'RESULT':6}  {'CHECK':{width}}  DETAIL")
    print(f"{'-' * 6}  {'-' * width}  {'-' * 24}")
    for c in checks:
        print(f"{'PASS' if c.passed else 'FAIL':6}  {c.name:{width}}  {c.detail}")


def style_axes(ax: plt.Axes, title: str, ylabel: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", color=INK, fontsize=12)
    ax.set_ylabel(ylabel, color=INK_2)
    ax.tick_params(colors=MUTED, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)


def year_span(dates: pd.Series) -> str:
    """'2023-2029' style label for plot titles."""
    years = pd.to_datetime(dates).dt.year
    return f"{years.min()}-{years.max()}"


def _figure() -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=(10, 4.5), facecolor=SURFACE)
    return fig, ax


def save_plots(daily: pd.DataFrame, out_dir: Path = PLOTS_DIR) -> list[Path]:
    """Monthly boxplot, full time series and weekday bar chart (PNG)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    span = year_span(daily["date"])

    fig, ax = _figure()
    groups = [daily.loc[daily["month"] == m, "occupancy_pct"] for m in range(1, 13)]
    ax.boxplot(groups, tick_labels=[str(m) for m in range(1, 13)], widths=0.5,
               patch_artist=True,
               boxprops={"facecolor": BLUE_LIGHT, "edgecolor": BLUE},
               medianprops={"color": INK, "linewidth": 2},
               whiskerprops={"color": BLUE}, capprops={"color": BLUE},
               flierprops={"marker": "o", "markersize": 3, "markeredgecolor": MUTED})
    style_axes(ax, f"Daily occupancy by month, {span} (SYNTHETIC data)", "Occupancy")
    ax.set_xlabel("Month", color=INK_2)
    paths.append(out_dir / "occupancy_by_month.png")

    fig2, ax2 = _figure()
    series = daily.set_index("date")["occupancy_pct"]
    ax2.plot(series.index, series, color=BLUE_LIGHT, linewidth=0.8, label="Daily")
    ax2.plot(series.index, series.rolling(28, center=True).mean(), color=BLUE, linewidth=2,
             label="28-day rolling mean")
    ax2.legend(frameon=False, labelcolor=INK_2, loc="lower right")
    style_axes(ax2, f"Daily occupancy, {span} (SYNTHETIC data)", "Occupancy")
    paths.append(out_dir / "occupancy_timeseries.png")

    fig3, ax3 = _figure()
    by_dow = daily.groupby("day_of_week")["occupancy_pct"].mean().reindex(range(7))
    bars = ax3.bar(WEEKDAYS, by_dow, color=BLUE, width=0.6)
    ax3.bar_label(bars, fmt="%.2f", color=INK_2, padding=3)
    style_axes(ax3, f"Mean occupancy by weekday, {span} (SYNTHETIC data)", "Mean occupancy")
    paths.append(out_dir / "occupancy_by_weekday.png")

    for f, p in zip((fig, fig2, fig3), paths, strict=True):
        f.tight_layout()
        f.savefig(p, dpi=120, facecolor=SURFACE)
        plt.close(f)
    return paths


def main() -> int:
    cfg = load_config()
    first = generate_daily(cfg)[2]
    second = generate_daily(cfg)[2]
    checks = run_checks(first, cfg, frame_hash(second))
    print("Validation of SYNTHETIC occupancy data\n")
    print_table(checks)
    print()
    for p in save_plots(first):
        print(f"plot saved: {p}")
    return 0 if all(c.passed for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
