"""Weekly SYNTHETIC department workload: required vs available staff hours.

Weeks start on Monday. Only complete weeks inside the property date range are kept, so
every week has 7 days of occupancy (partial first / last weeks are dropped).
"""

from __future__ import annotations

import pandas as pd

from ml.generator.config import GeneratorConfig

LOAD_COLUMNS = [
    "week_start",
    "department",
    "occupied_room_nights",
    "required_hours",
    "headcount",
    "available_hours",
    "load_ratio",
]


def weekly_room_nights(occupancy_daily: pd.DataFrame) -> pd.DataFrame:
    """week_start (Monday) and occupied_room_nights = sum of rooms_sold, complete weeks only."""
    daily = occupancy_daily.assign(date=pd.to_datetime(occupancy_daily["date"]))
    week_start = daily["date"] - pd.to_timedelta(daily["date"].dt.dayofweek, unit="D")
    weekly = daily.groupby(week_start)["rooms_sold"].agg(["sum", "size"])
    weekly = weekly[weekly["size"] == 7]
    return pd.DataFrame(
        {"week_start": weekly.index, "occupied_room_nights": weekly["sum"].to_numpy()}
    )


def build_dept_week_load(
    occupancy_daily: pd.DataFrame, employees: pd.DataFrame, cfg: GeneratorConfig
) -> pd.DataFrame:
    """One row per (week, department). Headcount is static (initial staff) until Task 4."""
    weeks = weekly_room_nights(occupancy_daily)
    headcount = employees.groupby("department").size()
    frames = []
    for dept, std in cfg.workload.items():
        hc = int(headcount.get(dept, 0))
        room_nights = weeks["occupied_room_nights"]
        required = std.base_hours + std.per_occupied_room_night_hours * room_nights
        available = hc * cfg.staff.standard_weekly_hours
        frames.append(
            weeks.assign(
                department=dept,
                required_hours=required.round(2),
                headcount=hc,
                available_hours=float(available),
                load_ratio=(required / available).round(4) if available else float("inf"),
            )
        )
    return pd.concat(frames, ignore_index=True)[LOAD_COLUMNS]
