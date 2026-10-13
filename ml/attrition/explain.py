"""Score employees with risk, rank-based band and top drivers (T8, revised in T12), on SYNTHETIC
data.

score_week() is the shared scoring step (T9's attrition.score wraps it). For ONE week and each
group (permanent -> resignation model, seasonal -> contract_end model) it takes the calibrated
risk of the segment's winner, ranks the active non-hero staff into bands (ml/attrition/bands.py),
PLACES demo heroes (and any re-scored employee) against them, and explains each row with
contributions from the SAME winner model (FoldModel.contributions), grouped into driver
categories with plain-language reasons and the playbook actions of the top driver.

Seasonal staff get a contract-date RULE band (band_basis contract_date_rule, T12b): their exit
is a known date and ~96% of their model risks were tied; permanent staff keep the model rank.

main() scores the last week, prints the demo checks (Sunita's top 3 include overtime overload;
Deepak is not high), a driver report with contributions, every hero's band (and, for permanent
staff, the rejected percentile rule), and the heroes' 12-week trajectory, and writes
artifacts/attrition/v1/drivers.json (also LightGBM TreeSHAP importance as a comparison). Failed
checks are REPORTED, never tuned away. Run from ml/:  python run.py train
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import pandas as pd

from ml.attrition.bands import (
    CONTRACT_DATE_RULE,
    HIGH,
    MODEL_RANK,
    Placement,
    assign_bands,
    percentile_band,
    place,
    rule_band,
)
from ml.attrition.drivers import (
    UNSUPPORTED,
    actions_for,
    category_contributions,
    global_importance,
    load_playbook,
    plain_reason,
    shap_values,
    top_categories,
)
from ml.attrition.features import (
    ARTIFACT_DIR,
    DATA_DIR,
    SEGMENTS,
    build_attrition_features,
    load_tables,
)
from ml.generator.attrition import BEHAVIOUR_COLUMNS
from ml.generator.config import AttritionModelConfig, load_config
from ml.generator.signals import SIGNAL_COLUMNS

SEGMENT_OF = {contract: seg for seg, (contract, _, _) in SEGMENTS.items()}
SUNITA, DEEPAK = "H901", "H905"
SUNITA_EXPECTED = "overtime_overload"
SEASONAL = "seasonal"
REPORT_FEATURES = ("pay_ratio", "months_since_raise", "weeks_without_leave")


def load_bundle(artifact_dir: Path = ARTIFACT_DIR) -> dict:
    return joblib.load(artifact_dir / "model.joblib")


def load_hero_ids(data_dir: Path = DATA_DIR) -> frozenset[str]:
    return frozenset(pd.read_csv(data_dir / "demo" / "hero_employees.csv")["employee_id"])


def tables_with_heroes(data_dir: Path = DATA_DIR) -> dict[str, pd.DataFrame]:
    """Output tables with the demo heroes appended (for SCORING only)."""
    t = load_tables(data_dir)
    hero_emp = pd.read_csv(data_dir / "demo" / "hero_employees.csv", keep_default_na=False)
    hero_week = pd.read_csv(data_dir / "demo" / "hero_weekly.csv")
    t["employees"] = pd.concat([t["employees"], hero_emp], ignore_index=True)
    t["behaviour"] = pd.concat([t["behaviour"], hero_week[BEHAVIOUR_COLUMNS]], ignore_index=True)
    t["signals"] = pd.concat([t["signals"], hero_week[SIGNAL_COLUMNS]], ignore_index=True)
    return t


def feature_frame(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return build_attrition_features(tables["employees"], tables["behaviour"], tables["signals"],
                                    tables["exits"], tables["renewals"], tables["pay_changes"])


@dataclass(frozen=True)
class Scored:
    employee_id: str
    week_start: str
    segment: str
    model: str
    risk: float
    rank: int
    group_size: int
    band: str
    band_basis: str
    rank_is_tied: bool
    is_demo_hero: bool
    drivers: list[str]
    driver_logodds: list[float]
    reasons: list[str]
    actions: list[dict]


def segment_risk(part: pd.DataFrame, bundle: dict) -> pd.Series:
    """Calibrated risk of the segment's winner for rows of ONE contract type."""
    info = bundle["segments"][SEGMENT_OF[part["contract_type"].iloc[0]]]
    return pd.Series(info["model"].calibrated(part)[info["winner"]], index=part.index)


def placements(part: pd.DataFrame, risk: pd.Series, outsiders: frozenset[str],
               cfg: AttritionModelConfig) -> dict[int, Placement]:
    """Rank / band per row: population = everyone but the outsiders, who are placed against it."""
    is_pop = ~part["employee_id"].isin(outsiders)
    pop = assign_bands(risk[is_pop], cfg)
    n = int(is_pop.sum())
    out = {i: Placement(int(r["rank"]), n, r["band"], bool(r["rank_is_tied"]))
           for i, r in pop.iterrows()}
    out.update({i: place(float(risk[i]), risk[is_pop], cfg) for i in part.index[~is_pop]})
    return out


def score_week(rows: pd.DataFrame, bundle: dict, cfg: AttritionModelConfig, playbook: dict,
               hero_ids: frozenset[str], extra_outsiders: frozenset[str] = frozenset(),
               ) -> list[Scored]:
    """Score every row of ONE week (bands need the whole week's population).

    The population is the active non-hero staff; heroes and `extra_outsiders` (an employee being
    re-scored) are placed against it without taking a slot.
    """
    if rows["week_start"].nunique() != 1:
        raise ValueError("score_week needs the rows of exactly one week")
    outsiders = hero_ids | extra_outsiders
    out: dict[int, Scored] = {}
    for contract, part in rows.groupby("contract_type"):
        seg = SEGMENT_OF[contract]
        info = bundle["segments"][seg]
        model, winner = info["model"], info["winner"]
        risk = segment_risk(part, bundle)
        where = placements(part, risk, outsiders, cfg)
        contrib = category_contributions(model.contributions(part, winner))
        seasonal = contract == SEASONAL  # known exit date: rule band, model rank kept for info
        for i, row in part.iterrows():
            cats = top_categories(contrib.loc[i], cfg.driver_min_logodds)
            p = where[i]
            band = rule_band(row["days_until_contract_end"], cfg) if seasonal else p.band
            out[i] = Scored(row["employee_id"], str(pd.Timestamp(row["week_start"]).date()), seg,
                            winner, round(float(risk[i]), 4), p.rank, p.group_size, band,
                            CONTRACT_DATE_RULE if seasonal else MODEL_RANK, p.rank_is_tied,
                            row["employee_id"] in hero_ids, cats,
                            [round(float(contrib.loc[i, c]), 4) for c in cats],
                            [plain_reason(c, row) for c in cats], actions_for(cats[:1], playbook))
    return [out[i] for i in rows.index]


def demo_checks(scored: dict[str, Scored]) -> list[tuple[str, bool, str]]:
    """T12b checks. The T8 check 'Sunita has overtime overload AND clustered-leave burnout' was
    REMOVED: it came from the hero script, written before we knew the generator never plants a
    pre-festival leave driver (clustered-leave burnout is only weakly supported)."""
    s, d = scored[SUNITA], scored[DEEPAK]
    return [
        ("Sunita's top 3 drivers include overtime overload", SUNITA_EXPECTED in s.drivers,
         f"{s.drivers} (risk {s.risk}, rank {s.rank}/{s.group_size}, {s.band})"),
        ("Deepak is not high risk", d.band != HIGH,
         f"risk {d.risk}, rank {d.rank}/{d.group_size}, band {d.band}"),
    ]


def hero_trajectory(features: pd.DataFrame, bundle: dict, cfg: AttritionModelConfig,
                    playbook: dict, hero_ids: frozenset[str]) -> list[dict]:
    """Every hero's risk, rank and band in each week they have rows (the scripted weeks)."""
    weeks = sorted(features.loc[features["employee_id"].isin(hero_ids), "week_start"].unique())
    rows = []
    for week in weeks:
        for s in score_week(features[features["week_start"] == week], bundle, cfg, playbook,
                            hero_ids):
            if s.is_demo_hero:
                rows.append({"employee_id": s.employee_id, "week_start": s.week_start,
                             "risk": s.risk, "rank": s.rank, "group_size": s.group_size,
                             "band": s.band})
    return rows


def main(data_dir: Path = DATA_DIR, artifact_dir: Path = ARTIFACT_DIR) -> int:
    cfg = load_config().attrition_model
    bundle, playbook, hero_ids = load_bundle(artifact_dir), load_playbook(), load_hero_ids(data_dir)
    features = feature_frame(tables_with_heroes(data_dir))
    last = features[features["week_start"] == features["week_start"].max()]
    scored = {s.employee_id: s for s in score_week(last, bundle, cfg, playbook, hero_ids)}
    names = json.loads((data_dir / "demo" / "hero_display_names.json").read_text("utf-8"))
    print(f"Attrition drivers (SYNTHETIC data), week {last['week_start'].max().date()}; rank "
          f"bands: high = top {cfg.band_high_share:.0%}, watch = next {cfg.band_watch_share:.0%} "
          "(ceil-count, ties never split)")
    hero_bands = {}
    for hid, name in names.items():
        s = scored[hid]
        # the rejected percentile rule only applies to model-rank bands (permanent staff)
        alt = percentile_band(s.rank, s.group_size, cfg) if s.band_basis == MODEL_RANK else None
        hero_bands[hid] = {"name": name, "segment": s.segment, "risk": s.risk, "rank": s.rank,
                           "group_size": s.group_size, "band_used": s.band,
                           "band_basis": s.band_basis,
                           "band_percentile_rule": alt, "rank_is_tied": s.rank_is_tied,
                           "drivers": dict(zip(s.drivers, s.driver_logodds, strict=True))}
        print(f"  {name} ({hid}, {s.segment}/{s.model}): risk {s.risk:.4f}, rank {s.rank}/"
              f"{s.group_size}{' (tied)' if s.rank_is_tied else ''} -> {s.band} ({s.band_basis})"
              + (f" [percentile rule: {alt}]" if alt else ""))
        for r in s.reasons:
            print(f"      - {r}")
    print("  driver report (top 3, contribution in calibrated log-odds, scoring model):")
    for hid, name in names.items():
        s = scored[hid]
        cells = ", ".join(f"{c} {v:+.3f}" for c, v in zip(s.drivers, s.driver_logodds,
                                                         strict=True)) or "none above threshold"
        print(f"    {name:7s} [{s.band}, {s.band_basis}]: {cells}")
    sunita_row = last[last["employee_id"] == SUNITA].iloc[0]
    sunita_numbers = {f: round(float(sunita_row[f]), 4) for f in REPORT_FEATURES}
    print(f"  Sunita's inputs: {sunita_numbers}")
    staff = [s for s in scored.values() if not s.is_demo_hero]
    for seg in SEGMENTS:
        counts = pd.Series([s.band for s in staff if s.segment == seg]).value_counts().to_dict()
        print(f"  staff bands this week ({seg}): {counts}")
    checks = demo_checks(scored)
    for label, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL (reported, not tuned)'}: {label}: {detail}")
    print(f"  {UNSUPPORTED}: UNSUPPORTED (no manager signal in the data)")
    trajectory = hero_trajectory(features, bundle, cfg, playbook, hero_ids)
    table = pd.DataFrame(trajectory)
    table["name"] = table["employee_id"].map(names)
    table["cell"] = (table["risk"].map("{:.3f}".format) + " #" + table["rank"].astype(str) + " "
                     + table["band"])
    print("  hero trajectory (risk #rank band per scripted week):")
    print(table.pivot(index="week_start", columns="name", values="cell").to_string())
    importance, comparison = {}, {}
    for seg, info in bundle["segments"].items():
        rows = features[(features["contract_type"] == info["contract_type"])
                        & ~features["employee_id"].isin(hero_ids)]
        model = info["model"]
        importance[seg] = global_importance(model.contributions(rows, info["winner"])).to_dict()
        comparison[seg] = global_importance(shap_values(model.scorers.lightgbm, rows)).to_dict()
        print(f"  mean |contribution| by driver ({seg}, {info['winner']}): {importance[seg]}")
    path = artifact_dir / "drivers.json"
    path.write_text(json.dumps({
        "explanation": "contributions of the scoring (winner) model in calibrated log-odds",
        "mean_abs_contribution_by_driver": importance,
        "comparison_lightgbm_treeshap_by_driver": comparison,
        "unsupported": [UNSUPPORTED],
        "demo_checks": [{"check": c, "passed": ok, "detail": d} for c, ok, d in checks],
        "hero_bands_last_week": hero_bands,
        "sunita_inputs_last_week": sunita_numbers,
        "hero_trajectory": trajectory,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"  saved {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
