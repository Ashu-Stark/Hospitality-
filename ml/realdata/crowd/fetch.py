"""Download the raw files for the crowd model into ml/data/real/crowd/raw/ (gitignored).

    python -m ml.realdata.crowd.fetch          # from the repo root

Re-fetching is only needed to re-check the extracted tables; training reads the committed CSVs
plus the weather archive (raw/openmeteo_archive_daily.csv), which this command rebuilds.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.parse
import urllib.request

import pandas as pd

from ml.realdata.crowd.sources import COORDS, RAW_DIR, SOURCES, WEATHER_END, WEATHER_START

UA = {"User-Agent": "Mozilla/5.0 (HOI crowd research; non-commercial)"}
DAILY = "temperature_2m_max,temperature_2m_min,precipitation_sum,rain_sum,snowfall_sum"


def _get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return r.read()


def fetch_weather() -> pd.DataFrame:
    import json

    frames = []
    for dest, (lat, lon) in COORDS.items():
        q = urllib.parse.urlencode(
            {
                "latitude": lat,
                "longitude": lon,
                "start_date": WEATHER_START,
                "end_date": WEATHER_END,
                "daily": DAILY,
                "timezone": "Asia/Kolkata",
            }
        )
        j = json.loads(_get("https://archive-api.open-meteo.com/v1/archive?" + q))
        d = pd.DataFrame(j["daily"])
        d.insert(0, "destination", dest)
        d["grid_elevation_m"] = j.get("elevation")
        frames.append(d)
    return pd.concat(frames, ignore_index=True)


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for s in SOURCES:
        if not s.raw_file or not s.url.startswith("https://") or s.key == "open_meteo":
            continue
        data = _get(s.url)
        (RAW_DIR / s.raw_file).write_bytes(data)
        print(f"{s.key}: {len(data):,} bytes sha256 {hashlib.sha256(data).hexdigest()}")
    w = fetch_weather()
    w.to_csv(RAW_DIR / "openmeteo_archive_daily.csv", index=False)
    print(f"open_meteo: {len(w):,} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
