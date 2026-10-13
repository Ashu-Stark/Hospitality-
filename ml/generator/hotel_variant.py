"""Hotel variants of the SYNTHETIC dataset (e.g. the fictional "Himsagar Ridge Resort").

A variant is ml/generator/hotels/<key>.yaml: a `hotel` block (positions, id prefix, display
name) plus overrides merged over config.yaml. The generator stages of `python run.py generate`
run on the merged config and write the same file set into ml/data/hotels/<key>/ (the default
ml/data/ dataset is never touched):

  event_calendar, weather_daily, occupancy_daily, employee, employee_skill, dept_week_load,
  employee_v2, weekly_behaviour, weekly_signals, exits, contract_renewals, pay_changes,
  dept_week_load_dynamic, leave_records, pulse_responses, attrition_calibration.json,
  demo/ (EMPTY hero files: a variant has no demo heroes), internal/employee_latent.csv
  (generator-only), hotel.json (staff positions with role titles).

After generation the demo-week staff are renamed to the hotel's ids in position order (HS02,
HS03, ...) and everyone who left earlier gets a former-staff id (HSX001, ...). Ids only: no
names or personal attributes anywhere. The seed is searched upward from the variant's seed
until the demo week has every position filled (no vacancy gap) and enough seasonal staff; the
seed used is recorded in hotel.json.

Run from ml/:  python run.py generate-hotel himsagar
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field

from ml.generator import run_attrition, run_occupancy, run_skills, run_staff
from ml.generator.calibrate import CALIBRATION_FILE, save_calibration
from ml.generator.config import DEFAULT_CONFIG_PATH, GeneratorConfig
from ml.generator.heroes import HERO_WEEKLY_COLUMNS
from ml.generator.rng import stream_rngs
from ml.generator.signals import compute_weekly_signals, leave_records, pulse_responses
from ml.generator.staff import EMPLOYEE_COLUMNS

HOTELS_DIR = Path(__file__).with_name("hotels")
HOTEL_DATA_ROOT = Path(__file__).resolve().parents[1] / "data" / "hotels"
# Top-level config blocks a variant REPLACES as a whole (merging would keep the default
# hotel's extra roles etc.).
REPLACE_KEYS = frozenset(
    {"departments", "roles", "skills", "workload", "month_base_occupancy", "staff"}
)
# Files whose id columns are renamed after generation (paths relative to the data folder).
ID_FILES = (
    "employee.csv",
    "employee_v2.csv",
    "employee_skill.csv",
    "weekly_behaviour.csv",
    "weekly_signals.csv",
    "exits.csv",
    "contract_renewals.csv",
    "pay_changes.csv",
    "leave_records.csv",
    "pulse_responses.csv",
    "internal/employee_latent.csv",
)
ID_COLUMNS = ("employee_id", "manager_id", "replacement_employee_id")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Position(_Strict):
    department: str
    role: str
    title: str


class Manager(_Strict):
    employee_id: str
    department: str
    title: str
    contract_type: str


class HotelSpec(_Strict):
    key: str
    display_name: str
    floors: int = Field(gt=0)
    id_prefix: str
    former_id_prefix: str
    positions: list[Position]
    manager: Manager
    min_seasonal: int = Field(ge=0)
    max_seed_tries: int = Field(gt=0)


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k not in REPLACE_KEYS:
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def variant_path(key: str) -> Path:
    path = HOTELS_DIR / f"{key}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no hotel variant {key!r} ({path})")
    return path


def load_hotel(key: str) -> tuple[GeneratorConfig, HotelSpec]:
    """(merged, validated generator config, the hotel block) for a variant."""
    base = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    over = yaml.safe_load(variant_path(key).read_text(encoding="utf-8"))
    spec = HotelSpec.model_validate(over.pop("hotel"))
    cfg = GeneratorConfig.model_validate(_merge(base, over))
    counts: dict[tuple[str, str], int] = {}
    for p in spec.positions:
        counts[(p.department, p.role)] = counts.get((p.department, p.role), 0) + 1
    want = {(d, r): s.count for d, roles in cfg.roles.items() for r, s in roles.items()}
    if counts != want:
        raise ValueError(f"hotel positions {counts} do not match the roles block {want}")
    return cfg, spec


def data_dir(key: str) -> Path:
    return HOTEL_DATA_ROOT / key


# --- generation ---------------------------------------------------------------------------


def _signals(cfg: GeneratorConfig, out: Path) -> None:
    behaviour = pd.read_csv(out / "weekly_behaviour.csv")
    latent = pd.read_csv(out / "internal" / "employee_latent.csv")
    calendar = pd.read_csv(out / "event_calendar.csv")
    (rng,) = stream_rngs(cfg.seed, "signals")
    signals = compute_weekly_signals(behaviour, latent, calendar, cfg, rng)
    for name, frame in (
        ("weekly_signals.csv", signals),
        ("leave_records.csv", leave_records(behaviour, signals)),
        ("pulse_responses.csv", pulse_responses(behaviour)),
    ):
        frame.to_csv(out / name, index=False, date_format="%Y-%m-%d")
    demo = out / "demo"  # a variant has NO demo heroes: header-only files keep every reader working
    demo.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=EMPLOYEE_COLUMNS).to_csv(demo / "hero_employees.csv", index=False)
    pd.DataFrame(columns=HERO_WEEKLY_COLUMNS).to_csv(demo / "hero_weekly.csv", index=False)
    (demo / "hero_display_names.json").write_text("{}\n", encoding="utf-8")


def build(cfg: GeneratorConfig, out: Path) -> None:
    """Run every generator stage for `cfg` into `out` (same order as python run.py generate)."""
    out.mkdir(parents=True, exist_ok=True)
    run_occupancy.write_outputs(*run_occupancy.generate_daily(cfg), out)
    run_staff.write_outputs(
        run_staff.generate_staff(cfg, pd.read_csv(out / "occupancy_daily.csv")), out
    )
    cal = run_attrition.run(cfg, out)
    run_attrition.write_outputs(cal.result, out)
    save_calibration(cal, out / CALIBRATION_FILE)
    run_skills.build(out, cfg).to_csv(out / "employee_skill.csv", index=False)
    _signals(cfg, out)


def demo_week_staff(out: Path) -> tuple[str, pd.DataFrame]:
    """(last week, employee_v2 rows of everyone active in it)."""
    beh = pd.read_csv(out / "weekly_behaviour.csv")
    week = beh["week_start"].max()
    active = set(beh[(beh["week_start"] == week) & beh["is_active"].astype(bool)]["employee_id"])
    emp = pd.read_csv(out / "employee_v2.csv", keep_default_na=False)
    return week, emp[emp["employee_id"].isin(active)].reset_index(drop=True)


def check_demo_week(spec: HotelSpec, out: Path) -> list[str]:
    """Why this generated dataset cannot be the hotel (empty = usable)."""
    _, staff = demo_week_staff(out)
    problems = []
    have = staff.groupby(["department", "role"]).size().to_dict()
    for p in {(p.department, p.role) for p in spec.positions}:
        need = sum(1 for q in spec.positions if (q.department, q.role) == p)
        if have.get(p, 0) != need:
            problems.append(f"{p}: {have.get(p, 0)} active, need {need}")
    seasonal = int((staff["contract_type"] == "seasonal").sum())
    if seasonal < spec.min_seasonal:
        problems.append(f"only {seasonal} seasonal staff, need {spec.min_seasonal}")
    skills = pd.read_csv(out / "employee_skill.csv")
    fo = staff[staff["department"] == "front_office"]["employee_id"]
    holders = skills[(skills["skill"] == "fo_system") & skills["employee_id"].isin(fo)][
        "employee_id"
    ].nunique()
    if holders < 3:  # 2 front-office shifts a day x 7 days need 3 holders (6 days each max)
        problems.append(f"only {holders} fo_system holders in front office")
    return problems


def id_map(spec: HotelSpec, out: Path) -> dict[str, str]:
    """Old generator id -> hotel id: demo-week staff in position order, then former staff in
    hire order."""
    _, staff = demo_week_staff(out)
    pool = staff.sort_values("employee_id")
    used: set[str] = set()
    mapping: dict[str, str] = {}
    for n, p in enumerate(spec.positions, start=2):  # 01 is the hotel manager (not in the ml data)
        old = next(
            e
            for e, d, r in zip(pool["employee_id"], pool["department"], pool["role"], strict=True)
            if d == p.department and r == p.role and e not in used
        )
        used.add(old)
        mapping[old] = f"{spec.id_prefix}{n:02d}"
    every = pd.read_csv(out / "employee_v2.csv", keep_default_na=False)["employee_id"]
    former = [e for e in every if e not in used]
    mapping.update({e: f"{spec.former_id_prefix}{k:03d}" for k, e in enumerate(former, start=1)})
    return mapping


def rename_ids(out: Path, mapping: dict[str, str]) -> None:
    """Rewrite the id columns of every table (read as text, so other values stay byte-identical)."""
    for rel in ID_FILES:
        path = out / rel
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        for col in ID_COLUMNS:
            if col in df:
                df[col] = df[col].map(lambda v: mapping.get(v, v))
        df.to_csv(path, index=False)


def hotel_record(cfg: GeneratorConfig, spec: HotelSpec, out: Path, seed: int) -> dict:
    week, staff = demo_week_staff(out)
    by_id = staff.set_index("employee_id")
    skills = pd.read_csv(out / "employee_skill.csv").groupby("employee_id")["skill"].agg(sorted)
    rows = [
        {
            "employee_id": spec.manager.employee_id,
            "department": spec.manager.department,
            "role": "manager",
            "role_title": spec.manager.title,
            "contract_type": spec.manager.contract_type,
            "is_department_head": False,
            "skills": [],
            "rostered": False,
        }
    ]
    for n, p in enumerate(spec.positions, start=2):
        emp = f"{spec.id_prefix}{n:02d}"
        rows.append(
            {
                "employee_id": emp,
                "department": p.department,
                "role": p.role,
                "role_title": p.title,
                "contract_type": str(by_id.loc[emp, "contract_type"]),
                "is_department_head": str(by_id.loc[emp, "is_department_head"]).lower() == "true",
                "skills": list(skills.get(emp, [])),
                "rostered": True,
            }
        )
    return {
        "key": spec.key,
        "display_name": spec.display_name,
        "rooms": cfg.property.rooms,
        "floors": spec.floors,
        "demo_week": week,
        "seed": seed,
        "staff": rows,
        "synthetic": True,
        "note": "FICTIONAL hotel; SYNTHETIC data from ml/generator (ASSUMED parameters). Ids only.",
    }


def generate(key: str, root: Path = HOTEL_DATA_ROOT) -> dict:
    """Generate the variant into root/<key>/ (replacing it); returns the hotel record."""
    cfg, spec = load_hotel(key)
    target = root / key
    build_dir = root / f"_{key}_build"
    tried = []
    for seed in range(cfg.seed, cfg.seed + spec.max_seed_tries):
        if build_dir.exists():
            shutil.rmtree(build_dir)
        run_cfg = cfg.model_copy(update={"seed": seed})
        build(run_cfg, build_dir)
        problems = check_demo_week(spec, build_dir)
        if problems:
            tried.append(f"seed {seed}: " + "; ".join(problems))
            continue
        rename_ids(build_dir, id_map(spec, build_dir))
        record = hotel_record(run_cfg, spec, build_dir, seed)
        (build_dir / "hotel.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        if target.exists():
            shutil.rmtree(target)
        build_dir.rename(target)
        record["seeds_rejected"] = tried
        return record
    shutil.rmtree(build_dir, ignore_errors=True)
    raise RuntimeError(
        f"no seed in {spec.max_seed_tries} tries fills every position:\n" + "\n".join(tried)
    )


def main(argv: list[str]) -> int:
    key = argv[0] if argv else "himsagar"
    record = generate(key)
    print(
        f"SYNTHETIC data for {record['display_name']} -> {data_dir(key)} (seed {record['seed']}, "
        f"demo week {record['demo_week']}, {record['rooms']} rooms, "
        f"{len(record['staff'])} staff incl. manager)"
    )
    for r in record["seeds_rejected"]:
        print(f"  rejected {r}")
    for s in record["staff"]:
        print(f"  {s['employee_id']}  {s['department']:<13} {s['role_title']:<24} "
              f"{s['contract_type']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
