"""GPU evidence: device names, nvidia-smi snapshots (and a sampler during training), timings."""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from collections.abc import Callable

QUERY = "name,memory.used,memory.total,utilization.gpu,temperature.gpu"


def nvidia_smi() -> str | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    out = subprocess.run([exe, f"--query-gpu={QUERY}", "--format=csv,noheader"],
                         capture_output=True, text=True, timeout=30)
    return out.stdout.strip() or None


def torch_info() -> dict:
    try:
        import torch
    except ImportError:
        return {"torch": None, "cuda_available": False}
    info = {"torch": torch.__version__, "cuda_available": torch.cuda.is_available(),
            "torch_cuda_runtime": torch.version.cuda}
    if torch.cuda.is_available():
        info["device_name"] = torch.cuda.get_device_name(0)
        info["device_memory_gb"] = round(
            torch.cuda.get_device_properties(0).total_memory / 2**30, 2)
    return info


def cuda_available() -> bool:
    return bool(torch_info().get("cuda_available"))


class SmiSampler:
    """Samples nvidia-smi every `every` seconds in a thread; keeps the peak memory / util."""

    def __init__(self, every: float = 2.0) -> None:
        self.every, self.samples = every, []
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)

    def _loop(self) -> None:
        while not self._stop.is_set():
            s = nvidia_smi()
            if s:
                self.samples.append(s)
            self._stop.wait(self.every)

    def __enter__(self) -> SmiSampler:
        self._t.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._t.join(timeout=10)

    def peak(self) -> dict:
        mem, util = [], []
        for s in self.samples:
            parts = [p.strip() for p in s.split(",")]
            mem.append(int(parts[1].split()[0]))
            util.append(int(parts[3].split()[0]))
        return {"samples": len(self.samples), "peak_memory_used_mib": max(mem, default=None),
                "peak_utilization_pct": max(util, default=None)}


def timed(fn: Callable[[], object], repeats: int = 1) -> float:
    """Best wall-clock seconds over `repeats` runs."""
    best = float("inf")
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return round(best, 3)
