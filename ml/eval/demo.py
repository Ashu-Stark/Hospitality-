"""Demo outputs from the packaged models (Task T12): the smoke test and the frontend mocks.

demo_outputs() calls the public interfaces only (they load ml/artifacts and the SYNTHETIC data
tables; nothing is trained): forecast.predict for the last week of data, attrition.score for the
latest scoring week, attrition.rescore for Sunita with two protected weekends off, and the hero
list.

python run.py smoke  -> ml.eval.demo smoke  (fresh process; prints outputs, exit 1 on any error)
python run.py mocks  -> ml.eval.demo mocks  (writes data/mocks/*.json from the same outputs)
"""

from __future__ import annotations

import json
import sys
import traceback
from datetime import timedelta
from pathlib import Path

from pydantic import BaseModel

ML_ROOT = Path(__file__).resolve().parents[1]
MOCKS_DIR = ML_ROOT / "data" / "mocks"
SUNITA = "H901"
PROTECTED_WEEKENDS = 2
DAYS_PER_WEEK = 7


def demo_outputs() -> dict[str, BaseModel | list[BaseModel]]:
    from ml import attrition, forecast

    week = attrition.api.latest_week()
    end = week + timedelta(days=DAYS_PER_WEEK - 1)
    return {
        "forecast_week": forecast.predict(week, end),
        "attrition_scores": attrition.score(week),
        "rescore_sunita": attrition.rescore(
            SUNITA, attrition.protected_weekends_off(SUNITA, PROTECTED_WEEKENDS), week),
        "heroes": attrition.heroes(),
    }


def to_json(value: BaseModel | list[BaseModel]) -> object:
    """Pydantic dump with the result types' own field names (dates as ISO strings)."""
    if isinstance(value, list):
        return [v.model_dump(mode="json") for v in value]
    return value.model_dump(mode="json")


def write_mocks(outputs: dict, out_dir: Path = MOCKS_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, value in outputs.items():
        path = out_dir / f"{name}.json"
        path.write_text(json.dumps(to_json(value), indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        paths.append(path)
    return paths


def print_smoke(outputs: dict) -> None:
    f = outputs["forecast_week"]
    print(f"forecast.predict as of {f.as_of} ({f.band}, SYNTHETIC):")
    for d in f.days:
        alert = (" HIGH-DEMAND" if d.high_demand_alert
                 else " LOW-DEMAND" if d.low_demand_alert else "")
        print(f"  {d.date} h={d.horizon_days:>2} {d.mean:.3f} [{d.low:.3f}, {d.high:.3f}]{alert}")
    scores = outputs["attrition_scores"]
    print(f"attrition.score week {scores[0].week_start}: {len(scores)} employees; top 5 + heroes:")
    shown = sorted(scores, key=lambda s: -s.risk)[:5] + [s for s in scores if s.is_demo_hero]
    for s in {x.employee_id: x for x in shown}.values():
        tie = " (tied)" if s.rank_is_tied else ""
        print(f"  {s.employee_id} {s.segment:12s} risk {s.risk:.4f} rank {s.rank}/{s.group_size}"
              f"{tie} {s.band:5s} drivers {[d.category for d in s.drivers]}")
    r = outputs["rescore_sunita"]
    print(f"attrition.rescore {r.employee_id} ({r.note})")
    print(f"  features {r.features_before} -> {r.features_after}")
    print(f"  risk {r.before.risk} ({r.before.band}, rank {r.before.rank}) -> {r.after.risk} "
          f"({r.after.band}, rank {r.after.rank}); change {r.risk_change:+.4f}")
    print(f"heroes: {[h.display_name for h in outputs['heroes']]}")


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else "smoke"
    try:
        outputs = demo_outputs()
        if mode == "mocks":
            for p in write_mocks(outputs):
                print(f"wrote {p.relative_to(ML_ROOT)}")
        else:
            print_smoke(outputs)
            print("SMOKE OK")
    except Exception:  # noqa: BLE001 - fail loudly with the full traceback
        traceback.print_exc()
        print("SMOKE FAILED" if mode != "mocks" else "MOCKS FAILED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
