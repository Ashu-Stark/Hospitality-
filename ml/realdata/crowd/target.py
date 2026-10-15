"""Daily pilgrim series per shrine and season, built ONLY from sourced figures.

Real figures (ml/data/real/crowd/):
  * sdc_2024_weekly.csv: weekly totals 10 May - 17 Aug 2024 (SEOC daily figures, compiled by SDC);
  * checkpoints.csv: news-quoted official figures, kind = daily | cumulative | season_total |
    nil (an officially reported day with no arrivals); only verified rows are used;
  * utdb_annual.csv: official annual visitors (= the season total for a shrine open Apr-Nov);
  * season_dates.csv: portal opening and closing dates.

Method (documented in DATA_CARD.md). Every real figure becomes an ANCHOR on the cumulative curve:
the day before opening is 0; weekly totals and cumulative checkpoints are cumulative counts at
their date; the season total sits at the closing date. Between two anchors the interval total is
REAL; how it splits across the days inside is not observed. Reported single-day figures and nil
days are fixed, the rest of the interval total is spread evenly over the remaining days. So:

  basis = reported     a single-day official figure (real)
          nil          an officially reported day with no arrivals (real)
          spread       an even share of a real interval total (ESTIMATED day value)

Anchors that break monotonicity (a later cumulative figure below an earlier one) are dropped,
keeping the higher-priority source (season total > weekly SDC > news cumulative), and logged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from ml.realdata.crowd.sources import DATA_DIR

# Who wins when two real figures contradict each other (see _clean). Weekly totals compiled from
# the SEOC daily figures beat everything; a closing-day total quoted from the yatra administration
# beats an in-season figure; the UTDB annual statistic comes last, because for several shrine-years
# it is BELOW figures reported earlier in the same season (e.g. Gangotri 2024: 5,40,190 vs 5,98,723
# by 17 Aug from SEOC), so it is used only where it agrees with the in-season figures.
PRIORITY = {"opening": 9, "weekly": 5, "season_total": 3, "cumulative": 2, "annual": 1}
# News figures are dated to +-1 day ("till yesterday"), so two cumulative figures 1-2 days apart
# give a meaningless 1-2 day interval (false spikes and dips). A cumulative anchor closer than this
# to the previous kept anchor is dropped (rule added after the first results; see RESULTS.md).
MIN_GAP_DAYS = 3
RATE_FACTOR = (
    1.25  # implied pilgrims/day above 1.25 x the highest reported single day = contradiction
)


@dataclass
class Anchor:
    day: date  # cumulative count INCLUDING this day
    cum: float
    kind: str
    source: str


@dataclass
class SeasonSeries:
    dest: str
    year: int
    open: date
    close: date
    daily: dict[date, float] = field(default_factory=dict)
    basis: dict[date, str] = field(default_factory=dict)
    interval: dict[date, tuple[date, date]] = field(default_factory=dict)  # day -> (start, end)
    anchors: list[Anchor] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)

    @property
    def last_day(self) -> date | None:
        return max(self.daily) if self.daily else None


def load_checkpoints(data_dir=DATA_DIR) -> pd.DataFrame:
    c = pd.read_csv(data_dir / "checkpoints.csv", dtype={"count": "float64"})
    c = c[c["verified_raw"].astype(str).str.lower().eq("yes") & c["use"].astype(str).eq("1")]
    c["as_of_date"] = pd.to_datetime(c["as_of_date"], errors="coerce").dt.date
    c = c[c["as_of_date"].notna() | c["kind"].eq("season_total")]  # a season total needs no date
    return c


def _weekly_anchors(dest: str, year: int, op: date, data_dir) -> list[Anchor]:
    if year != 2024:
        return []
    w = pd.read_csv(data_dir / "sdc_2024_weekly.csv")
    out, cum = [], 0.0
    for r in w.itertuples():
        v = getattr(r, dest)
        if pd.isna(v):
            return out
        cum += float(v)
        out.append(Anchor(date.fromisoformat(r.end_date), cum, "weekly", "sdc_2024"))
    return out


def _clean(anchors: list[Anchor], log: list[str], max_rate: float = float("inf")) -> list[Anchor]:
    """Keep a consistent (non-decreasing, one value per day) set of anchors.

    While any two anchors contradict each other (a later cumulative figure below an earlier one,
    two different figures for the same day, or an implied daily rate above `max_rate`), drop
    the anchor with the lowest PRIORITY, and among those the one involved in the most
    contradictions. Every drop is logged.
    """
    kept: list[Anchor] = []
    for a in sorted(anchors, key=lambda a: (a.day, -PRIORITY[a.kind])):
        if any(k.day == a.day and k.cum == a.cum for k in kept):
            continue  # the same figure from two sources
        kept.append(a)

    def clash(a: Anchor, b: Anchor) -> bool:
        if a.day == b.day:
            return a.cum != b.cum
        first, second = (a, b) if a.day < b.day else (b, a)
        rate = (second.cum - first.cum) / (second.day - first.day).days
        return first.cum > second.cum or rate > max_rate

    while True:
        n = {id(a): sum(clash(a, b) for b in kept if b is not a) for a in kept}
        bad = [a for a in kept if n[id(a)]]
        if not bad:
            return _thin(sorted(kept, key=lambda a: a.day), log)
        loser = min(bad, key=lambda a: (PRIORITY[a.kind], -n[id(a)]))
        log.append(
            f"inconsistent anchor {loser.day} {loser.kind} {loser.cum:.0f} ({loser.source}) dropped"
        )
        kept.remove(loser)


def _thin(kept: list[Anchor], log: list[str]) -> list[Anchor]:
    out: list[Anchor] = []
    for i, a in enumerate(kept):
        last = i == len(kept) - 1
        if (
            out
            and a.kind == "cumulative"
            and not last
            and (a.day - out[-1].day).days < MIN_GAP_DAYS
        ):
            log.append(
                f"cumulative {a.day} {a.cum:.0f} within {MIN_GAP_DAYS} days of {out[-1].day}: "
                "dropped (dates are +-1 day)"
            )
            continue
        out.append(a)
    return out


def build_season(
    dest: str,
    year: int,
    op: date,
    cl: date,
    ck: pd.DataFrame,
    annual: pd.DataFrame,
    data_dir=DATA_DIR,
    max_rate: float = float("inf"),
) -> SeasonSeries:
    s = SeasonSeries(dest, year, op, cl)
    mine = ck[(ck["dham"] == dest) & (ck["season"] == year)]
    anchors = [Anchor(op - timedelta(days=1), 0.0, "opening", "opening")]
    anchors += _weekly_anchors(dest, year, op, data_dir)
    for r in mine[mine["kind"] == "cumulative"].itertuples():
        if op <= r.as_of_date <= cl:
            anchors.append(Anchor(r.as_of_date, float(r.count), "cumulative", r.source_url))
    ann = annual[(annual["portal_id"] == dest) & (annual["year"] == year)]
    for v in ann["total"]:
        anchors.append(Anchor(cl, float(v), "annual", f"utdb_{year}"))
    for r in mine[mine["kind"] == "season_total"].itertuples():
        anchors.append(Anchor(cl, float(r.count), "season_total", r.source_url))
    s.anchors = _clean(anchors, s.dropped, max_rate)
    fixed: dict[date, tuple[float, str]] = {}
    for r in mine[mine["kind"].isin(["daily", "nil"])].itertuples():
        if op <= r.as_of_date <= cl:
            fixed[r.as_of_date] = (
                0.0 if r.kind == "nil" else float(r.count),
                "nil" if r.kind == "nil" else "reported",
            )
    for a, b in zip(s.anchors, s.anchors[1:], strict=False):
        days = [a.day + timedelta(days=i) for i in range(1, (b.day - a.day).days + 1)]
        total_iv = b.cum - a.cum
        fx = {d: fixed[d] for d in days if d in fixed}
        rest = total_iv - sum(v for v, _ in fx.values())
        free = [d for d in days if d not in fx]
        if rest < 0 or (rest > 0 and not free):
            s.dropped.append(
                f"daily figures in {days[0]}..{days[-1]} conflict with the interval "
                f"total {total_iv:.0f}: ignored, interval spread evenly"
            )
            fx, rest, free = {}, total_iv, days
        for d in days:
            if d in fx:
                s.daily[d], s.basis[d] = fx[d]
            else:
                s.daily[d], s.basis[d] = rest / len(free), "spread"
            s.interval[d] = (days[0], days[-1])
    return s


def build_all(seasons: dict, data_dir=DATA_DIR) -> dict[tuple[str, int], SeasonSeries]:
    ck = load_checkpoints(data_dir)
    annual = pd.read_csv(data_dir / "utdb_annual.csv")
    out = {}
    for dest, by_year in seasons.items():
        rate = max_daily(ck, dest, data_dir) * RATE_FACTOR
        for year, (op, cl) in by_year.items():
            out[(dest, year)] = build_season(dest, year, op, cl, ck, annual, data_dir, rate)
    return out


def max_daily(ck: pd.DataFrame, dest: str, data_dir=DATA_DIR) -> float:
    """Highest single-day count ever reported for the shrine (inf if none is known)."""
    v = ck.loc[(ck["dham"] == dest) & (ck["kind"] == "daily"), "count"]
    return float(v.max()) if len(v) else float("inf")


def to_frame(series: dict[tuple[str, int], SeasonSeries]) -> pd.DataFrame:
    rows = []
    for (dest, year), s in series.items():
        for d, v in sorted(s.daily.items()):
            a, b = s.interval[d]
            rows.append(
                {
                    "dest": dest,
                    "season": year,
                    "date": d,
                    "pilgrims": v,
                    "basis": s.basis[d],
                    "interval_start": a,
                    "interval_end": b,
                    "interval_days": (b - a).days + 1,
                }
            )
    return pd.DataFrame(rows)
