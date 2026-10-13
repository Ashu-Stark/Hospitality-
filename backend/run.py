"""Backend task runner (Windows-friendly). Run it from inside backend/.

Usage:
    python run.py test          # fast backend tests (skips tests marked slow)
    python run.py test --all    # every backend test
    python run.py lint          # ruff check .
    python run.py seed          # rebuild hoi_ops (MongoDB, MONGODB_URI) from the SYNTHETIC ml data
    python run.py roster-cache  # solve the demo week and save the cached demo roster
    python run.py roster-stress [n]  # n random scenarios (default 100): hard violations, times
    python run.py backend       # start the API on http://127.0.0.1:8000 (MOCK=1 for mock mode)
    python run.py backend-smoke # fresh process: health, forecast, score, roster, loop, task

Uses the repo-root .venv when present and puts the repo root on PYTHONPATH (packages `backend`
and `ml`).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_ROOT.parent
VENV_PY = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
HOST, PORT = "127.0.0.1", "8000"


def _python() -> str:
    return str(VENV_PY) if VENV_PY.exists() else sys.executable


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO_ROOT), env.get("PYTHONPATH")]))
    return env


def _run(args: list[str]) -> int:
    return subprocess.call([_python(), "-m", *args], cwd=BACKEND_ROOT, env=_env())


def cmd_test(*args: str) -> int:
    if args not in ((), ("--all",)):
        print("usage: python run.py test [--all]")
        return 2
    return _run(["pytest", "-q"] + ([] if args else ["-m", "not slow"]))


def cmd_lint() -> int:
    return _run(["ruff", "check", "."])


def cmd_seed() -> int:
    return _run(["backend.seed"])


def cmd_roster_cache() -> int:
    return _run(["backend.roster.build_cache"])


def cmd_roster_stress(*args: str) -> int:
    return _run(["backend.roster.stress", *args])


def cmd_backend_smoke() -> int:
    return _run(["backend.smoke"])


def cmd_backend() -> int:
    """Local dev server on 127.0.0.1; honours PORT like the container (python -m backend.serve)."""
    return _run(["uvicorn", "--factory", "backend.main:create_app", "--host", HOST,
                 "--port", os.environ.get("PORT", PORT)])


COMMANDS = {"test": cmd_test, "lint": cmd_lint, "seed": cmd_seed, "backend": cmd_backend,
            "roster-cache": cmd_roster_cache, "roster-stress": cmd_roster_stress,
            "backend-smoke": cmd_backend_smoke}
TAKES_ARGS = {"test", "roster-stress"}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in COMMANDS or (len(argv) > 1 and argv[0] not in TAKES_ARGS):
        print(f"usage: python run.py [{'|'.join(COMMANDS)}]")
        return 2
    return COMMANDS[argv[0]](*argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
