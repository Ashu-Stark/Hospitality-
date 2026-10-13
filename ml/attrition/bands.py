"""Rank-based risk bands (Task T12), on SYNTHETIC data.

Within one scoring week and one group (permanent or seasonal), the active non-hero staff are
ranked by calibrated risk (rounded to RISK_DECIMALS, the precision the product shows):
  high  = the first ceil(band_high_share * n) slots
  watch = the next ceil(band_watch_share * n) slots
  low   = the rest
Staff with identical (rounded) risk form a TIE GROUP that is never split: the group takes a band
only if it fits wholly in that band's remaining slots, otherwise the whole group moves to the
next lower band; once a group misses a band, no lower-risk group can take that band.
rank = 1 + the number of staff with strictly higher risk (tied staff share a rank).

Ceil-count was chosen over a percentile rule (rank / n <= share) because the seasonal group has
about 7 people, where a percentile rule can never create a high band (rank 1 of 7 is 14%). It
was chosen AFTER the demo hero Sunita's rank was seen (she sits on the boundary), so her band is
a ranking result, not a confident prediction; the model card reports her band under both rules.

Demo heroes and re-scored rows are PLACED against the population (they never take a slot or move
anyone else): their band is the one a tie group at their position would receive.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ml.generator.config import AttritionModelConfig

HIGH, WATCH, LOW = "high", "watch", "low"
RISK_DECIMALS = 4
SHARE_DECIMALS = 9  # round share * n before ceil, so 0.1 * 30 = 3.0000000000000004 -> 3


@dataclass(frozen=True)
class Placement:
    rank: int
    group_size: int  # population size of the employee's group that week
    band: str
    rank_is_tied: bool


def slots(n: int, cfg: AttritionModelConfig) -> tuple[int, int]:
    """(high slots, watch slots) for a group of n."""
    high = math.ceil(round(cfg.band_high_share * n, SHARE_DECIMALS))
    watch = math.ceil(round(cfg.band_watch_share * n, SHARE_DECIMALS))
    return high, watch


def _assign_groups(sizes: list[int], n: int, cfg: AttritionModelConfig) -> list[str]:
    """Bands for tie groups given in descending-risk order."""
    free = dict(zip((HIGH, WATCH), slots(n, cfg), strict=True))
    open_bands = [HIGH, WATCH]
    out = []
    for size in sizes:
        while open_bands and size > free[open_bands[0]]:
            open_bands.pop(0)  # the group does not fit: this band is closed for everyone below
        band = open_bands[0] if open_bands else LOW
        if band != LOW:
            free[band] -= size
        out.append(band)
    return out


def _rounded(risk: pd.Series | np.ndarray) -> np.ndarray:
    return np.round(np.asarray(risk, dtype=float), RISK_DECIMALS)


def assign_bands(risk: pd.Series, cfg: AttritionModelConfig) -> pd.DataFrame:
    """rank, band, rank_is_tied for every member of one population (index preserved)."""
    r = pd.Series(_rounded(risk), index=risk.index)
    counts = r.value_counts().sort_index(ascending=False)
    bands = dict(zip(counts.index, _assign_groups(list(counts.to_numpy()), len(r), cfg),
                     strict=True))
    rank = r.rank(method="min", ascending=False).astype(int)
    return pd.DataFrame({"rank": rank, "band": r.map(bands),
                         "rank_is_tied": r.map(counts) > 1}, index=risk.index)


def place(risk: float, population: pd.Series, cfg: AttritionModelConfig) -> Placement:
    """Rank and band of an outsider (hero / re-score) against a population, not changing it."""
    pop = pd.Series(_rounded(population))
    value = float(_rounded(np.array([risk]))[0])
    counts = pop.value_counts().sort_index(ascending=False)
    above = counts[counts.index > value]
    tied = value in counts.index
    sizes = [*above.to_numpy(), int(counts.get(value, 0)) if tied else 1]
    band = _assign_groups(sizes, len(pop), cfg)[-1]
    return Placement(int(above.sum()) + 1, len(pop), band, tied)


def percentile_band(rank: int, n: int, cfg: AttritionModelConfig) -> str:
    """The rejected percentile rule (rank / n <= share), kept only for the model-card comparison."""
    share = rank / n
    if share <= cfg.band_high_share:
        return HIGH
    return WATCH if share <= cfg.band_high_share + cfg.band_watch_share else LOW


def band_metrics(preds: pd.DataFrame, score: str, cfg: AttritionModelConfig) -> dict:
    """Backtest: bands per week, lift of high over the base rate, leavers caught in high+watch.

    preds needs columns week, label and `score` (one row per employee-week, one group).
    """
    b = preds.groupby("week", group_keys=False)[score].apply(lambda s: assign_bands(s, cfg))
    df = preds.join(b)
    base = float(df["label"].mean())
    high = df[df["band"] == HIGH]
    precision = float(high["label"].mean()) if len(high) else 0.0
    caught = float(df.loc[df["band"].isin([HIGH, WATCH]), "label"].sum() / df["label"].sum())
    return {
        "rule": "ceil-count slots, tie groups never split",
        "base_rate": round(base, 4),
        "high_precision": round(precision, 4),
        "high_lift": round(precision / base, 2) if base else None,
        "leaver_weeks_in_high_or_watch": round(caught, 4),
        "band_share": {k: round(float(v), 4) for k, v in
                       df["band"].value_counts(normalize=True).items()},
        "tied_share_per_week_mean": round(float(df.groupby("week")["rank_is_tied"].mean().mean()),
                                          4),
    }


# --- seasonal staff: contract-date rule band (T12b) ----------------------------------------
MODEL_RANK, CONTRACT_DATE_RULE = "model_rank", "contract_date_rule"


def rule_band(days_to_contract_end: float, cfg: AttritionModelConfig) -> str:
    """Seasonal band from the KNOWN contract end: <= high days -> high, <= watch days -> watch.

    A seasonal exit is a known date, not a prediction, and ~96% of seasonal model risks were
    tied, so ranking them carried no information. Chosen after seeing the ties, not to place any
    hero.
    """
    if days_to_contract_end <= cfg.seasonal_high_max_days:
        return HIGH
    return WATCH if days_to_contract_end <= cfg.seasonal_watch_max_days else LOW


def rule_band_metrics(preds: pd.DataFrame, cfg: AttritionModelConfig) -> dict:
    """Backtest of the seasonal rule band; preds needs label and days_until_contract_end."""
    band = preds["days_until_contract_end"].map(lambda d: rule_band(d, cfg))
    base = float(preds["label"].mean())
    high = preds.loc[band == HIGH, "label"]
    precision = float(high.mean()) if len(high) else 0.0
    caught = float(preds.loc[band.isin([HIGH, WATCH]), "label"].sum() / preds["label"].sum())
    return {
        "rule": f"days to contract end <= {cfg.seasonal_high_max_days} high, "
                f"<= {cfg.seasonal_watch_max_days} watch",
        "base_rate": round(base, 4),
        "high_precision": round(precision, 4),
        "high_lift": round(precision / base, 2) if base else None,
        "leaver_weeks_in_high_or_watch": round(caught, 4),
        "band_share": {k: round(float(v), 4) for k, v in band.value_counts(normalize=True).items()},
    }
