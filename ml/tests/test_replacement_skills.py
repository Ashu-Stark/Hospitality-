"""Bug fix after T12b: replacement hires get skills (own stream), coverage among active staff."""

import numpy as np
import pandas as pd

from ml.generator.rng import STREAMS, stream_rngs
from ml.generator.skills import active_coverage, extend_skills_to_replacements


def _toy(cfg):
    fo = cfg.skills["front_office"]
    employees = pd.DataFrame({
        "employee_id": ["A", "B", "C", "D"],
        "department": ["front_office"] * 4,
        "role": ["receptionist"] * 4,
        "hire_date": ["2020-01-01", "2020-01-01", "2020-01-01", "2024-03-01"],
        "is_department_head": [False] * 4,
    })
    initial = pd.DataFrame({"employee_id": ["A", "B", "C"], "skill": [fo[0], fo[0], fo[1]],
                            "level": [2, 2, 2]})
    exits = pd.DataFrame({"employee_id": ["A"], "exit_date": ["2024-02-20"]})
    return employees, initial, exits, fo


def test_stream_is_appended_last() -> None:
    assert STREAMS[-1] == "replacement_skills"
    assert STREAMS[:7] == ("weather", "occupancy", "staff", "skills", "attrition", "signals",
                           "heroes")


def test_replacement_gets_skills_and_fills_the_gap(cfg) -> None:
    employees, initial, exits, fo = _toy(cfg)
    out = extend_skills_to_replacements(employees, initial, exits, cfg, np.random.default_rng(0))
    assert out.iloc[:3].equals(initial)  # original rows untouched
    d = set(out.loc[out["employee_id"] == "D", "skill"])
    assert d and d <= set(fo)
    assert fo[0] in d  # A (a holder) left, so coverage of fo[0] needed the new hire


def test_extension_is_reproducible(cfg) -> None:
    employees, initial, exits, _ = _toy(cfg)
    a = extend_skills_to_replacements(employees, initial, exits, cfg,
                                      stream_rngs(cfg.seed, "replacement_skills")[0])
    b = extend_skills_to_replacements(employees, initial, exits, cfg,
                                      stream_rngs(cfg.seed, "replacement_skills")[0])
    pd.testing.assert_frame_equal(a, b)


def test_written_data_covers_the_demo_week(cfg) -> None:
    from pathlib import Path

    data = Path(__file__).resolve().parents[1] / "data"
    emp = pd.read_csv(data / "employee_v2.csv", keep_default_na=False)
    sk = pd.read_csv(data / "employee_skill.csv")
    cov = active_coverage(emp, sk, pd.read_csv(data / "exits.csv"), cfg,
                          pd.Timestamp("2029-12-24"))
    assert (cov["active"] == cov["with_any_skill"]).all()
    assert cov.loc[cov["department"] == "front_office", "fo_system_holders"].iloc[0] >= 1
    assert (cov["skills_below_minimum"] == "").all()
