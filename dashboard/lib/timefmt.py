"""Show API timestamps in hotel local time (India, +05:30 by default), like the Work log page does.

The platform API returns most stored times as ISO strings WITHOUT an offset, in the API server's own clock
(mongo.iso). On Render that clock is UTC, so cutting "HH:MM" out of the string showed UTC on the Jobs list, Guest
requests and Stock requests. Here a string with an offset is converted directly; a string without one is read as the
API server's local time (by default the same as this process: embedded API, or both on Render in UTC, or both on one
laptop) and then converted. Set HOI_API_UTC_OFFSET_MINUTES when the API server runs in a different time zone.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone


def local_tz() -> timezone:
    """Hotel local time; same setting and default as the platform API (HOI_HOTEL_UTC_OFFSET_MINUTES, 330 = IST)."""
    return timezone(timedelta(minutes=int(os.getenv("HOI_HOTEL_UTC_OFFSET_MINUTES", "330"))))


def _server_tz() -> timezone | None:
    v = os.getenv("HOI_API_UTC_OFFSET_MINUTES", "").strip()
    return timezone(timedelta(minutes=int(v))) if v.lstrip("-").isdigit() else None


def to_local(value) -> datetime | None:
    """An API timestamp (ISO string or datetime) as an aware datetime in hotel local time; None when it is not one."""
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value or "").strip()
        if "T" not in s and " " not in s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        server = _server_tz()
        dt = dt.replace(tzinfo=server) if server else dt.astimezone()  # naive = the API server's local clock
    return dt.astimezone(local_tz())


def hhmm(value, seconds: bool = False) -> str:
    """'HH:MM' (or 'HH:MM:SS') in hotel local time. A plain wall-clock value such as '10:45' is returned unchanged."""
    dt = to_local(value)
    if dt is None:
        s = str(value or "")
        return s[:8] if seconds else s[:5]
    return dt.strftime("%H:%M:%S" if seconds else "%H:%M")


def stamp(value) -> str:
    """'YYYY-MM-DD HH:MM' in hotel local time ('' when empty)."""
    dt = to_local(value)
    return dt.strftime("%Y-%m-%d %H:%M") if dt else str(value or "")[:16].replace("T", " ")
