from functools import lru_cache

import pandas as pd
import pytest

from ml.generator.attrition import AttritionResult
from ml.generator.calibrate import DEFAULT_CALIBRATION_PATH, calibrate_intercept, load_prior
from ml.generator.config import GeneratorConfig, load_config
from ml.generator.run_occupancy import generate_daily
from ml.generator.run_staff import StaffFrames, generate_staff


@pytest.fixture(scope="session")
def cfg() -> GeneratorConfig:
    return load_config()


@pytest.fixture(scope="session")
def generated(cfg: GeneratorConfig) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(calendar, weather, daily) for the default config. Do not mutate."""
    return generate_daily(cfg)


@pytest.fixture(scope="session")
def staff_frames(cfg: GeneratorConfig, generated) -> StaffFrames:
    """Staff, latent, skills and weekly load for the default config. Do not mutate."""
    return generate_staff(cfg, generated[2])


@pytest.fixture(scope="session")
def attrition_result(cfg: GeneratorConfig, staff_frames: StaffFrames) -> AttritionResult:
    """Full default attrition simulation, calibrated as run_attrition does. Do not mutate."""
    s = staff_frames
    prior = load_prior(DEFAULT_CALIBRATION_PATH)
    return calibrate_intercept(cfg, s.employee, s.employee_latent, s.dept_week_load,
                               prior=prior).result


# ---- GPU-only training ------------------------------------------------------------------
# Model training (and evaluation inside the trainers) runs on CUDA only (ml/gpu.py). Tests that
# train a model are marked `gpu` (or use the require_gpu fixture) and are SKIPPED, never run on
# the CPU, on machines without a usable GPU (e.g. CI). Inference tests run everywhere.


@lru_cache(maxsize=1)
def gpu_available() -> bool:
    from ml import gpu

    try:
        gpu.require_cuda()
        return True
    except gpu.GPURequiredError:
        return False


GPU_SKIP = "needs the GPU: model training is GPU-only (ml/gpu.py)"


@pytest.fixture(scope="session")
def require_gpu() -> None:
    if not gpu_available():
        pytest.skip(GPU_SKIP)


def pytest_collection_modifyitems(config, items) -> None:  # noqa: ARG001
    if gpu_available():
        return
    for item in items:
        if "gpu" in item.keywords:
            item.add_marker(pytest.mark.skip(reason=GPU_SKIP))
