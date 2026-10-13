"""Daily event calendar for the SYNTHETIC dataset: weekends, festivals, holidays, seasons."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict

from ml.generator.config import GeneratorConfig

DEFAULT_FESTIVALS_PATH = Path(__file__).with_name("festivals.yaml")

# A day is in a festival window if it falls 3 days before to 1 day after a festival day.
WINDOW_DAYS_BEFORE = 3
WINDOW_DAYS_AFTER = 1


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RecurringRange(_Strict):
    name: str
    start: str
    end: str


class PublicHoliday(_Strict):
    name: str
    month_day: str


class FestivalCalendar(_Strict):
    festivals: dict[str, list[date]]
    recurring_festivals: list[RecurringRange]
    public_holidays: list[PublicHoliday]
    school_holidays: list[RecurringRange]


def load_festivals(path: str | Path | None = None) -> FestivalCalendar:
    """Load and validate festivals.yaml."""
    p = Path(path) if path is not None else DEFAULT_FESTIVALS_PATH
    with p.open(encoding="utf-8") as f:
        return FestivalCalendar.model_validate(yaml.safe_load(f))


def month_day(dates: pd.Series) -> pd.Series:
    """Format dates as 'MM-DD' strings."""
    return dates.dt.strftime("%m-%d")


def in_month_day_range(md: pd.Series, start: str, end: str) -> pd.Series:
    """True where 'MM-DD' falls in [start, end]; handles ranges that wrap past the new year."""
    if start <= end:
        return (md >= start) & (md <= end)
    return (md >= start) | (md <= end)


def festival_days(fc: FestivalCalendar, first_year: int, last_year: int) -> dict[date, list[str]]:
    """Map each festival date to its festival names, expanding recurring ranges per year."""
    days: dict[date, list[str]] = defaultdict(list)
    for name, dates in fc.festivals.items():
        for d in dates:
            days[d].append(name)
    for r in fc.recurring_festivals:
        for year in range(first_year, last_year + 1):
            start = date.fromisoformat(f"{year}-{r.start}")
            end_year = year + 1 if r.end < r.start else year
            end = date.fromisoformat(f"{end_year}-{r.end}")
            for i in range((end - start).days + 1):
                days[start + timedelta(days=i)].append(r.name)
    return dict(days)


def festival_window(dates: pd.Series, fest_days: set[date]) -> pd.Series:
    """True if a festival day lies within [d - AFTER, d + BEFORE], i.e. d is in its window."""
    offsets = range(-WINDOW_DAYS_AFTER, WINDOW_DAYS_BEFORE + 1)
    return dates.dt.date.map(
        lambda d: any(d + timedelta(days=k) in fest_days for k in offsets)
    ).astype(bool)


def build_calendar(cfg: GeneratorConfig, fc: FestivalCalendar | None = None) -> pd.DataFrame:
    """One row per day from property.start to property.end (inclusive)."""
    fc = fc if fc is not None else load_festivals()
    dates = pd.Series(pd.date_range(cfg.property.start, cfg.property.end, freq="D"), name="date")
    md = month_day(dates)

    # Expand one year either side so windows crossing the range edges are complete.
    fest = festival_days(fc, cfg.property.start.year - 1, cfg.property.end.year + 1)
    names = dates.dt.date.map(lambda d: "; ".join(fest.get(d, [])))

    holiday_mds = {h.month_day for h in fc.public_holidays}
    school = pd.Series(False, index=dates.index)
    for r in fc.school_holidays:
        school |= in_month_day_range(md, r.start, r.end)

    cds = cfg.char_dham_season
    return pd.DataFrame(
        {
            "date": dates,
            "day_of_week": dates.dt.dayofweek,
            "month": dates.dt.month,
            "is_weekend": dates.dt.dayofweek.isin(cfg.occupancy.weekend_days),
            "is_public_holiday": md.isin(holiday_mds),
            "festival_name": names,
            "is_festival": names != "",
            "is_festival_window": festival_window(dates, set(fest)),
            "is_char_dham": in_month_day_range(md, cds.start_month_day, cds.end_month_day),
            "is_school_holiday": school,
        }
    )
