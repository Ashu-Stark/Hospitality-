"""Single source of configuration. Switching MOCK <-> LIVE = change USE_MOCKS (in .env, or at runtime on the Admin page)."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")  # repo-wide secrets (MONGODB_URI); never overrides the above
except ImportError:  # python-dotenv is optional at runtime
    pass

FRONTEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = FRONTEND_DIR.parent
DEFAULT_API = "https://hospitality-management-9jdk.onrender.com"

# Mock lookup order: dashboard/mocks (captured from the live ML API, the shapes the pages expect), then the ML repo mocks.
MOCK_DIRS = [FRONTEND_DIR / "mocks", REPO_ROOT / "ml" / "data" / "mocks"]
HERO_NAME_FILES = [REPO_ROOT / "ml" / "data" / "demo" / "hero_display_names.json", FRONTEND_DIR / "mocks" / "hero_display_names.json"]
PLAYBOOK_FILES = [REPO_ROOT / "ml" / "attrition" / "playbook.json", FRONTEND_DIR / "mocks" / "playbook.json"]


def _bool(v: str | None, default: bool) -> bool:
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    api_base_url: str
    use_mocks: bool
    timeout_s: float = 30.0
    roster_timeout_s: float = 45.0
    replacement_cost_inr: int = 60000

    @property
    def mode_label(self) -> str:
        return "MOCK DATA" if self.use_mocks else "LIVE"

    def cache_key(self) -> tuple:
        return (self.api_base_url, self.use_mocks)


def env_settings() -> Settings:
    return Settings(
        api_base_url=os.getenv("API_BASE_URL", DEFAULT_API).rstrip("/"),
        use_mocks=_bool(os.getenv("USE_MOCKS"), True),
        timeout_s=float(os.getenv("API_TIMEOUT_S", "30")),
        roster_timeout_s=float(os.getenv("ROSTER_TIMEOUT_S", "45")),
        replacement_cost_inr=int(os.getenv("REPLACEMENT_COST_INR", "60000")),
    )


def current_settings() -> Settings:
    """Env settings, overridden per browser session by the Admin page toggle."""
    s = env_settings()
    try:
        import streamlit as st

        ov = st.session_state.get("settings_override")
        if ov:
            s = Settings(**{**asdict(s), **ov})
    except Exception:  # outside a Streamlit run
        pass
    return s
