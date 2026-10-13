"""Production entrypoint (Render / Docker): python -m backend.serve

Binds to HOST (default 0.0.0.0) and PORT (default 8000). Render injects PORT, so the port is
never hard-coded. Startup creates the MongoDB indexes and seeds the employee snapshot from the
SYNTHETIC ml data when it is empty (backend.main lifespan), so a fresh database self-seeds.
"""

from __future__ import annotations

import os

import uvicorn

DEFAULT_HOST, DEFAULT_PORT = "0.0.0.0", 8000  # noqa: S104 - a container must listen externally


def main() -> None:
    uvicorn.run("backend.main:create_app", factory=True,
                host=os.environ.get("HOST", DEFAULT_HOST),
                port=int(os.environ.get("PORT", DEFAULT_PORT)))


if __name__ == "__main__":
    main()
