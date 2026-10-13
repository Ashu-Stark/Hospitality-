"""Task runner (Windows-friendly replacement for a Makefile). Run it from inside ml/.

Usage:
    python run.py test      # fast tests (skips tests marked slow)
    python run.py test --all  # every test, including the slow calibration / full-pipeline ones
    python run.py lint      # ruff check .
    python run.py generate  # write SYNTHETIC occupancy, staff, then attrition CSVs to data/
    python run.py validate  # PASS/FAIL checks + plots in docs/plots/
    python run.py validate-seeds [seed ...]  # pooled difficulty probes over seeds (42 43 44)
    python run.py train     # attrition: rules vs logistic vs LightGBM, calibration, drivers
    python run.py train-forecast  # occupancy forecast: seasonal-naive vs LightGBM, bands, alerts
    python run.py train-pulse  # pulse features, naive baseline, LightGBM regressor, comparison
    python run.py train-workload  # dept load_ratio features, naive, LightGBM, comparison
    python run.py eval      # retrain all models, rewrite metrics + plots, package, check
    python run.py check-artifacts  # load every artifact + run the interfaces, no retraining
    python run.py eval-voice  # voice: WER + extraction accuracy per provider, demo cache
    python run.py smoke     # fresh process: forecast week, scores, Sunita rescore (exit 1 on error)
    python run.py mocks     # write data/mocks/*.json for the frontend from the real model outputs

Commands run with .venv's Python when it exists (ml/.venv or the repo-root .venv), so
activating the venv is optional. The Python package is ml/ itself (imported as `ml.*`), so
every command runs with ml/ as working directory and the repo root on PYTHONPATH.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent
REPO_ROOT = ML_ROOT.parent
VENV_CANDIDATES = [d / ".venv" / "Scripts" / "python.exe" for d in (ML_ROOT, REPO_ROOT)]


def _python() -> str:
    return next((str(p) for p in VENV_CANDIDATES if p.exists()), sys.executable)


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO_ROOT), env.get("PYTHONPATH")]))
    return env


def _run(args: list[str]) -> int:
    return subprocess.call([_python(), "-m", *args], cwd=ML_ROOT, env=_env())


def cmd_test(*args: str) -> int:
    if args not in ((), ("--all",)):
        print("usage: python run.py test [--all]")
        return 2
    return _run(["pytest", "-q"] + ([] if args else ["-m", "not slow"]))


def cmd_lint() -> int:
    return _run(["ruff", "check", "."])


def cmd_validate_seeds(*seeds: str) -> int:
    if not all(s.isdigit() for s in seeds):
        print("usage: python run.py validate-seeds [seed ...]")
        return 2
    return _run(["ml.generator.validate_seeds", *seeds])


def _run_all(modules: list[str]) -> int:
    """Run modules in order; stop at the first failure and return its exit code."""
    for module in modules:
        code = _run([module])
        if code != 0:
            return code
    return 0


def cmd_generate() -> int:
    return _run_all(
        ["ml.generator.run_occupancy", "ml.generator.run_staff", "ml.generator.run_attrition",
         "ml.generator.run_skills", "ml.generator.run_signals"]
    )


VALIDATORS = (
    "ml.generator.validate_occupancy",
    "ml.generator.validate_staff",
    "ml.generator.validate_attrition",
    "ml.generator.validate_skills",
    "ml.generator.validate_heroes",
)


def cmd_validate() -> int:
    # Run every validator even if one fails, so all tables are shown.
    return max(_run([m]) for m in VALIDATORS)


def cmd_train() -> int:
    return _run_all(["ml.attrition.train", "ml.attrition.explain"])


def _run_steps(steps: list[list[str]]) -> int:
    """Run module + args steps in order; stop at the first failure."""
    for step in steps:
        code = _run(step)
        if code != 0:
            return code
    return 0


def cmd_train_forecast() -> int:
    return _run(["ml.forecast.train"])


def cmd_train_pulse() -> int:
    return _run_steps([
        ["ml.features.build_pulse_features"],
        ["ml.features.split", "pulse"],
        ["ml.models.train_pulse_baseline"],
        ["ml.models.train_pulse_model"],
        ["ml.models.evaluate_pulse"],  # exits 1 if the model does not beat naive on test MAE
    ])


def cmd_train_workload() -> int:
    return _run_steps([
        ["ml.features.build_workload_features"],
        ["ml.features.split", "workload"],
        ["ml.models.train_workload_baseline"],
        ["ml.models.train_workload_model"],
        ["ml.models.evaluate_workload"],  # exits 1 if the model does not beat naive on test MAE
    ])


def cmd_eval() -> int:
    """Retrain every model from the data on disk, rewrite all metrics / plots, then package
    (metrics.json, feature_list.json, dataset_hash.json, model_card.md) and check loading."""
    for step in (cmd_train_forecast, cmd_train, cmd_train_pulse, cmd_train_workload):
        code = step()
        if code != 0:
            return code
    return _run_all(["ml.eval.package", "ml.eval.check_artifacts", "ml.voice.evaluate"]) or (
        cmd_mocks())


def cmd_eval_voice() -> int:
    return _run(["ml.voice.evaluate"])


def cmd_smoke() -> int:
    return _run(["ml.eval.demo", "smoke"])


def cmd_mocks() -> int:
    return _run(["ml.eval.demo", "mocks"])


def cmd_check_artifacts() -> int:
    return _run(["ml.eval.check_artifacts"])


COMMANDS = {
    "test": cmd_test,
    "lint": cmd_lint,
    "generate": cmd_generate,
    "validate": cmd_validate,
    "validate-seeds": cmd_validate_seeds,
    "train": cmd_train,
    "train-forecast": cmd_train_forecast,
    "train-pulse": cmd_train_pulse,
    "train-workload": cmd_train_workload,
    "eval": cmd_eval,
    "check-artifacts": cmd_check_artifacts,
    "eval-voice": cmd_eval_voice,
    "smoke": cmd_smoke,
    "mocks": cmd_mocks,
}


TAKES_ARGS = {"test", "validate-seeds"}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in COMMANDS or (len(argv) > 1 and argv[0] not in TAKES_ARGS):
        print(f"usage: python run.py [{'|'.join(COMMANDS)}]")
        return 2
    return COMMANDS[argv[0]](*argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
