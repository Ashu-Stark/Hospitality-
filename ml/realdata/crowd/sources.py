"""Registry of the REAL public sources behind the crowd model, and the raw-file fetcher.

`python -m ml.realdata.crowd.fetch` downloads every raw file into ml/data/real/crowd/raw/
(gitignored) and prints its SHA-256. Only small tables of figures extracted from these files are
committed (ml/data/real/crowd/*.csv), each row naming its source. See DATA_CARD.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ML_ROOT / "data" / "real" / "crowd"
RAW_DIR = DATA_DIR / "raw"
ARTIFACT_DIR = ML_ROOT / "artifacts" / "crowd_forecast" / "real_v1"
REPO_ROOT = ML_ROOT.parent
PORTAL_MODEL = REPO_ROOT / "portal" / "hoi_portal" / "models" / "crowd_real_v1.json"
PORTAL_CODE = REPO_ROOT / "portal" / "hoi_portal" / "services" / "crowd_model.py"

# Shrine coordinates: the same values as portal/hoi_portal/seed/destinations.py.
COORDS = {
    "kedarnath": (30.735, 79.067),
    "badrinath": (30.744, 79.493),
    "gangotri": (30.994, 78.940),
    "yamunotri": (31.014, 78.460),
}
WEATHER_START, WEATHER_END = "2021-01-01", "2026-10-12"


@dataclass(frozen=True)
class Source:
    key: str
    title: str
    url: str
    accessed: str
    licence: str
    kind: str  # what we take from it
    raw_file: str | None = None


SOURCES = (
    Source(
        "utdb_2021_2023",
        "Uttarakhand Tourism Development Board: Tourists Statistics of Major "
        "Tourist Destinations, Year 2021-2023",
        "https://uttarakhandtourism.gov.in/assets/pdf/Statistic21-23.pdf",
        "2026-10-15",
        "Government of Uttarakhand publication; no open licence stated. Facts (annual counts) "
        "extracted with attribution; the PDF is not redistributed.",
        "annual visitors per destination",
        "utdb_statistic_2021_23.pdf",
    ),
    Source(
        "utdb_2024",
        "Uttarakhand Tourism Development Board: Tourist Statistics Of Major Tourist "
        "Destinations Year 2024",
        "https://uttarakhandtourism.gov.in/assets/media/"
        "UTDB_media_1743665047Yearly_Report_Statistics_2024.pdf",
        "2026-10-15",
        "As above.",
        "annual visitors per destination",
        "utdb_UTDB_media_1743665047Yearly_Report_Statistics_2024.pdf",
    ),
    Source(
        "utdb_2025",
        "Uttarakhand Tourism Development Board: Tourist Footfall at Major Tourist "
        "Destinations, Uttarakhand - 2025",
        "https://uttarakhandtourism.gov.in/assets/media/"
        "UTDB_media_1785820386Uttarakhand_Tourist_Footfall-2025.pdf",
        "2026-10-15",
        "As above.",
        "annual visitors per destination",
        "utdb_footfall_2025.pdf",
    ),
    Source(
        "sdc_2024",
        "SDC Foundation (Dehradun): Data Analysis of 100 Days of Uttarakhand Char "
        "Dham Yatra 2024, Mid Term Report v1.0 (weekly totals compiled from the daily figures of "
        "the State Emergency Operation Centre / USDMA and district authorities)",
        "https://www.sdcuk.in/wp-content/uploads/2024/08/"
        "DataAnalysisOf100DaysOfUttarakhandCharDhamYatra2024MidTermReport_SDC-Foundation.pdf",
        "2026-10-15",
        "Public NGO report, no licence stated. Weekly figures (facts) extracted with attribution; "
        "the PDF is not redistributed. SDC states it does not vouch for the government figures.",
        "weekly pilgrims per shrine 10 May - 17 Aug 2024, peak days, opening dates, nil days",
        "sdc_2024_midterm.pdf",
    ),
    Source(
        "open_meteo",
        "Open-Meteo Historical Weather API (ERA5 / ERA5-Land reanalysis)",
        "https://archive-api.open-meteo.com/v1/archive",
        "2026-10-15",
        "CC BY 4.0 (data); the free API is for non-commercial use (open-meteo.com/en/terms). "
        "Attribution: Weather data by Open-Meteo.com.",
        "daily precipitation, snowfall, max/min temperature per shrine",
        "openmeteo_archive_daily.csv",
    ),
    Source(
        "news_checkpoints",
        "News reports quoting official daily / season-to-date pilgrim figures "
        "(each row of checkpoints.csv names its own URL and publisher)",
        "see ml/data/real/crowd/checkpoints.csv",
        "2026-10-15",
        "Facts quoted with attribution (URL per row); articles are not copied.",
        "daily and cumulative pilgrims per shrine, opening / closing dates, suspension days",
    ),
)
BY_KEY = {s.key: s for s in SOURCES}
