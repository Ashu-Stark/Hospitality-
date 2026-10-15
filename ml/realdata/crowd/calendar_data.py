"""Calendar inputs from the committed, sourced CSVs: holidays, festivals, school vacations, seasons.

Files (ml/data/real/crowd/, each row with its source URL):
  holidays_in.csv       date,name,list(gazetted|restricted),year,source_url,notes
  school_vacations.csv  state,year,start_date,end_date,source_url,source_type,notes
  season_dates.csv      dest,year,open_date,close_date,open_source,close_source,notes
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ml.realdata.crowd.sources import DATA_DIR

# Restricted holidays that are pilgrimage-relevant festivals (the rest of the restricted list is
# not used). Matched case-insensitively on the start of the holiday name.
FESTIVAL_PREFIXES = (
    "maha shivratri",
    "mahashivratri",
    "holi",
    "raksha bandhan",
    "janmashtami",
    "ganesh chaturthi",
    "dussehra",
    "vijaya dashami",
    "diwali",
    "deepavali",
    "bhai duj",
    "bhai dooj",
    "guru nanak",
    "makar sankranti",
    "basant panchami",
    "vasant panchami",
    "buddha purnima",
    "govardhan",
)


def _dates(x) -> list[date]:
    return [date.fromisoformat(str(v)[:10]) for v in x]


def holidays(data_dir=DATA_DIR) -> tuple[set[date], set[date]]:
    """(gazetted holidays, festival days). Gazetted festivals count as both."""
    h = pd.read_csv(data_dir / "holidays_in.csv")
    # A later office memorandum moved some holidays; keep only the revised row.
    h = h[~h["notes"].fillna("").str.contains("Shifted to")]
    gaz = set(_dates(h.loc[h["list"] == "gazetted", "date"]))
    name = h["name"].str.lower().str.strip()
    fest_mask = name.apply(lambda n: any(n.startswith(p) for p in FESTIVAL_PREFIXES))
    fest = set(_dates(h.loc[fest_mask, "date"]))
    return gaz, fest


SOURCE_STATES = ("Delhi", "Uttar Pradesh", "Haryana")  # the nearest large source states
TYPICAL_VACATION = ((5, 15), (6, 30))  # ASSUMED fallback window when a state-year has no source
SCHOOL_YEARS = range(2021, 2028)


def school_windows(data_dir=DATA_DIR) -> list[tuple[str, int, date, date, bool]]:
    """(state, year, start, end, estimated) for every source state and year.

    Sourced windows come from school_vacations.csv (the longest window if a state has several
    rows, e.g. plain and hill schools); a missing state-year uses TYPICAL_VACATION, estimated=True.
    """
    v = pd.read_csv(data_dir / "school_vacations.csv").dropna(subset=["start_date", "end_date"])
    out = []
    for state in SOURCE_STATES:
        for year in SCHOOL_YEARS:
            g = v[(v["state"] == state) & (v["year"] == year)]
            if len(g):
                spans = [
                    (date.fromisoformat(a), date.fromisoformat(b))
                    for a, b in zip(g["start_date"], g["end_date"], strict=True)
                ]
                a, b = max(spans, key=lambda x: (x[1] - x[0]).days)
                out.append((state, year, a, b, False))
            else:
                (m1, d1), (m2, d2) = TYPICAL_VACATION
                out.append((state, year, date(year, m1, d1), date(year, m2, d2), True))
    return out


def school_share(data_dir=DATA_DIR) -> dict[date, float]:
    """Share of SOURCE_STATES (Delhi, UP, Haryana) whose schools are on summer vacation, per day."""
    count: dict[date, int] = {}
    for _state, _year, a, b, _est in school_windows(data_dir):
        d = a
        while d <= b:
            count[d] = count.get(d, 0) + 1
            d += timedelta(days=1)
    return {d: n / len(SOURCE_STATES) for d, n in count.items()}


def seasons(data_dir=DATA_DIR) -> dict[str, dict[int, tuple[date, date]]]:
    s = pd.read_csv(data_dir / "season_dates.csv").dropna(subset=["open_date", "close_date"])
    out: dict[str, dict[int, tuple[date, date]]] = {}
    for r in s.itertuples():
        out.setdefault(r.dest, {})[int(r.year)] = (
            date.fromisoformat(r.open_date),
            date.fromisoformat(r.close_date),
        )
    return out
