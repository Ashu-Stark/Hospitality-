"""Registry of the PUBLIC datasets used by ml/realdata, with download + SHA-256 verification.

Every dataset is downloaded from a direct public URL (no Kaggle API key). Raw files go to
ml/data/realdata/raw/ (gitignored: re-downloaded by `python run.py realdata`). A file whose
SHA-256 differs from the recorded value is rejected, so results always come from the exact
bytes described in ml/realdata/README.md.
"""

from __future__ import annotations

import hashlib
import io
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ML_ROOT / "data" / "realdata" / "raw"


@dataclass(frozen=True)
class Dataset:
    name: str
    filename: str
    url: str
    sha256: str
    licence: str
    provenance: str  # "real" | "fictional" | "real (unverified provenance)"
    citation: str
    zip_member: str | None = None  # file inside a zip download


HOTELS = Dataset(
    name="hotel_booking_demand",
    filename="hotels.csv",
    url="https://raw.githubusercontent.com/rfordatascience/tidytuesday/master/data/2020/"
        "2020-02-11/hotels.csv",
    sha256="7c2ae42a7353905ea136e5c2287f17c92c5435826598bfbb8491c6f0c7b1fc06",
    licence="CC BY 4.0",
    provenance="real",
    citation="Antonio, Almeida & Nunes (2019), Hotel booking demand datasets, Data in Brief 22, "
             "41-49, doi:10.1016/j.dib.2018.11.126 (TidyTuesday 2020-02-11 mirror)",
)

IBM_HR = Dataset(
    name="ibm_hr_attrition",
    filename="ibm_hr_attrition.csv",
    url="https://raw.githubusercontent.com/IBM/employee-attrition-aif360/master/data/"
        "emp_attrition.csv",
    sha256="a5c31e38bd7fafc9bc333884eb181b06b41b8e5e488e8f7ccb27199fb3be7659",
    licence="ODbL 1.0 (database) / DbCL 1.0 (contents), as stated in the IBM repo README",
    provenance="fictional",
    citation="IBM HR Analytics Employee Attrition & Performance: a FICTIONAL dataset created by "
             "IBM data scientists (mirror: github.com/IBM/employee-attrition-aif360)",
)

TURNOVER = Dataset(
    name="employee_turnover_babushkin",
    filename="turnover.csv",
    url="https://www.kaggle.com/api/v1/datasets/download/davinwijaya/employee-turnover",
    sha256="5098600655806f73c151b30432cf6697437928a30283e88c5c0a1cffeac65ceb",
    licence="CC BY-NC-SA 4.0 (Kaggle listing; NON-COMMERCIAL, evaluation only)",
    provenance="real (unverified provenance)",
    citation="Edward Babushkin (2017), 'Employee turnover: how to predict individual risks of "
             "quitting', edwvb.blogspot.com; Kaggle copy by Davin Wijaya",
    zip_member="turnover.csv",
)

ALL = (HOTELS, IBM_HR, TURNOVER)


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def path_of(ds: Dataset, raw_dir: Path = RAW_DIR) -> Path:
    return raw_dir / ds.filename


def fetch(ds: Dataset, raw_dir: Path = RAW_DIR, timeout: int = 120) -> Path:
    """Return the local file, downloading it first if missing. Raises on a hash mismatch."""
    path = path_of(ds, raw_dir)
    if not path.exists():
        raw_dir.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(ds.url, headers={"User-Agent": "hoi-realdata/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed URLs
            data = resp.read()
        if ds.zip_member:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                data = zf.read(ds.zip_member)
        if sha256_of(data) != ds.sha256:
            raise ValueError(f"{ds.name}: SHA-256 mismatch for {ds.url}")
        path.write_bytes(data)
    got = sha256_of(path.read_bytes())
    if got != ds.sha256:
        raise ValueError(f"{ds.name}: {path} has SHA-256 {got}, expected {ds.sha256}")
    return path
