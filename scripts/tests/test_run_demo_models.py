"""scripts/run_demo_models.py on mongomock (never the real cluster): all Himsagar staff through the models, outputs stored,
and a second run adds no duplicate tasks or staff (re-runnable). SYNTHETIC data."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_demo_models as rdm  # noqa: E402


def test_run_twice_is_idempotent_and_complete(capsys) -> None:
    saved = dict(os.environ)
    tag = uuid.uuid4().hex[:6]
    try:
        first = rdm.run("mongomock://", f"hoi_ops_t_{tag}", f"hoi_platform_t_{tag}")
        second = rdm.run("mongomock://", f"hoi_ops_t_{tag}", f"hoi_platform_t_{tag}")
        out = capsys.readouterr().out
        from hoi_platform import mongo
        from hoi_platform.services import dispatch

        staff = list(mongo.col("staff").find({"tenant_id": "org_demo", "employee_id": {"$regex": "^HS"}}))
        ctx = dispatch.get_context("org_demo")
        shifts = dispatch.shifts_for("org_demo", "HS05")
    finally:
        os.environ.clear()
        os.environ.update(saved)
        from hoi_platform import config

        config.reload()
    assert first and second
    assert first["staff_scored"] == 19 and sum(first["levels"].values()) == 19
    assert first["loop_tasks_new"] == 2 * len(first["high"]) and second["loop_tasks_new"] == 0
    assert first["levels"] == second["levels"] and first["today"] == second["today"]
    assert len(first["forecast"]) == 7 and first["synthetic"]
    assert 0 < first["today"]["coverage"] <= 1 and 0 < first["week_coverage"] <= 1
    assert sorted(s["employee_id"] for s in staff) == [f"HS{n:02d}" for n in range(1, 21)]
    assert all(set(s) <= {"_id", "tenant_id", "employee_id", "department", "skills", "contract_type", "role_title", "avatar", "property_id"}
               for s in staff)  # ids and roles only
    assert len(ctx["bands"]) == 19 and ctx["working"] and shifts["shifts"]
    assert "MISMATCH" not in out and "mongodb+srv" not in out
