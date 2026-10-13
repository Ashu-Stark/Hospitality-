"""Well-known venues used for BestTime foot-traffic forecasts, mapped to our curated destinations.

BestTime (besttime.app) matches a venue by name + address and returns a typical weekly foot-traffic pattern
(0-100 per hour, relative to the venue's own busiest hour). Each successful forecast costs credits, so the list is
short (at most 20) and fetched once by `python -m hoi_portal.scripts.besttime_refresh` (cached 7 days in MongoDB,
`crowd_forecasts`). Order matters: the first venue BestTime found for a destination is the one shown on its page.

Addresses are plain postal-style strings (place, district, state, PIN); BestTime's own match is stored and shown, so a
wrong match is visible and can be fixed here. Kainchi Dham is shown under Nainital and Jageshwar under Almora because
those are the nearest curated destinations.
"""

from __future__ import annotations

from .destinations import BY_ID_DEST

# key (stable id in crowd_forecasts), destination id, venue_name, venue_address
_RAW = [
    ("kedarnath-temple", "kedarnath", "Kedarnath Temple", "Kedarnath, Rudraprayag, Uttarakhand 246445, India"),
    ("badrinath-temple", "badrinath", "Badrinath Temple", "Badrinath, Chamoli, Uttarakhand 246422, India"),
    ("gangotri-temple", "gangotri", "Gangotri Temple", "Gangotri, Uttarkashi, Uttarakhand 249135, India"),
    ("yamunotri-temple", "yamunotri", "Yamunotri Temple", "Yamunotri, Uttarkashi, Uttarakhand 249141, India"),
    ("har-ki-pauri", "haridwar", "Har Ki Pauri", "Har Ki Pauri, Haridwar, Uttarakhand 249401, India"),
    ("parmarth-niketan", "rishikesh", "Parmarth Niketan", "Parmarth Niketan, Swarg Ashram, Rishikesh, Uttarakhand 249304, India"),
    ("mansa-devi-temple", "haridwar", "Mansa Devi Temple", "Mansa Devi Temple, Haridwar, Uttarakhand 249401, India"),
    ("mall-road-mussoorie", "mussoorie", "Mall Road Mussoorie", "Mall Road, Mussoorie, Uttarakhand 248179, India"),
    ("gun-hill-mussoorie", "mussoorie", "Gun Hill Point", "Gun Hill, Mussoorie, Uttarakhand 248179, India"),
    ("naina-devi-temple", "nainital", "Naina Devi Temple", "Naina Devi Temple, Mallital, Nainital, Uttarakhand 263001, India"),
    ("kainchi-dham", "nainital", "Kainchi Dham", "Kainchi Dham, Bhowali, Nainital, Uttarakhand 263132, India"),
    ("auli-ropeway", "auli", "Auli Ropeway", "Auli Ropeway, Joshimath, Chamoli, Uttarakhand 246443, India"),
    ("garjiya-devi-temple", "jim-corbett-ramnagar", "Garjiya Devi Temple", "Garjiya, Ramnagar, Nainital, Uttarakhand 244715, India"),
    (
        "valley-of-flowers-np",
        "valley-of-flowers",
        "Valley of Flowers National Park",
        "Valley of Flowers, Chamoli, Uttarakhand 246443, India",
    ),
    ("tungnath-temple", "chopta", "Tungnath Temple", "Tungnath, Chopta, Rudraprayag, Uttarakhand 246419, India"),
    ("jageshwar-dham", "almora", "Jageshwar Dham", "Jageshwar, Almora, Uttarakhand 263623, India"),
    ("tapkeshwar-temple", "dehradun", "Tapkeshwar Mahadev Temple", "Tapkeshwar Temple, Garhi Cantt, Dehradun, Uttarakhand 248003, India"),
    ("tehri-dam", "new-tehri-tehri-lake", "Tehri Dam", "Tehri Dam, New Tehri, Tehri Garhwal, Uttarakhand 249001, India"),
    ("anasakti-ashram", "kausani", "Anasakti Ashram", "Anasakti Ashram, Kausani, Bageshwar, Uttarakhand 263639, India"),
    ("bhulla-tal", "lansdowne", "Bhulla Tal", "Bhulla Tal, Lansdowne, Pauri Garhwal, Uttarakhand 246155, India"),
]

VENUES: list[dict] = [
    {"key": k, "destination_id": d, "venue_name": n, "venue_address": a, "rank": i} for i, (k, d, n, a) in enumerate(_RAW)
]
BY_KEY = {v["key"]: v for v in VENUES}
MAX_VENUES = 20


def validate() -> None:
    assert len(VENUES) <= MAX_VENUES, "keep the BestTime venue list short (credits)"
    assert len(BY_KEY) == len(VENUES), "duplicate venue key"
    for v in VENUES:
        assert v["destination_id"] in BY_ID_DEST, v
        assert v["venue_name"].strip() and "Uttarakhand" in v["venue_address"], v
