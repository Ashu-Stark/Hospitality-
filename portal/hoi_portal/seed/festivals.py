"""Festivals and seasonal events, usual timing only (docs/PORTAL_SPEC.md section 5).

Lunar-calendar dates vary and are announced annually. `crowd_impact` is an ASSUMED rating used by the crowd
estimate; it is not an official figure.
"""

from __future__ import annotations

from .districts import IDS

LUNAR = "Dates follow the lunar calendar and are announced annually; check the official notice."
ANNUAL = "Usual timing only; check the official notice for this year's dates."
CHAR_DHAM = ["kedarnath", "badrinath", "gangotri", "yamunotri"]

# id, name, months, window text, districts, destination ids, impact, description, date note
_RAW = [
    (
        "uttarayani-fair",
        "Uttarayani fair",
        [1],
        "January (Makar Sankranti)",
        ["bageshwar"],
        ["bageshwar"],
        "medium",
        "Traditional fair at Bageshwar around Makar Sankranti.",
        LUNAR,
    ),
    ("phool-dei", "Phool Dei", [3], "March (Chaitra)", list(IDS), [], "low", "Spring festival observed across the state.", LUNAR),
    (
        "international-yoga-festival",
        "International Yoga Festival, Rishikesh",
        [3],
        "March",
        ["dehradun"],
        ["rishikesh"],
        "medium",
        "Yoga festival held in Rishikesh.",
        ANNUAL,
    ),
    (
        "char-dham-opening",
        "Char Dham yatra opening",
        [4, 5],
        "April-May",
        ["rudraprayag", "chamoli", "uttarkashi"],
        CHAR_DHAM,
        "high",
        "The four Char Dham shrines open for the season; opening dates are announced each year.",
        LUNAR,
    ),
    (
        "ganga-dussehra",
        "Ganga Dussehra",
        [5, 6],
        "May-June",
        ["haridwar", "dehradun"],
        ["haridwar", "rishikesh"],
        "high",
        "Observed at Haridwar and Rishikesh.",
        LUNAR,
    ),
    ("harela", "Harela", [7], "July", list(IDS), [], "low", "Seasonal festival observed across the state.", LUNAR),
    (
        "kanwar-yatra",
        "Kanwar Yatra, Haridwar",
        [7, 8],
        "July-August (Shravan)",
        ["haridwar"],
        ["haridwar"],
        "high",
        "Pilgrimage centred on Haridwar during Shravan.",
        LUNAR,
    ),
    (
        "nanda-devi-fair",
        "Nanda Devi fair",
        [8, 9],
        "August-September",
        ["almora", "nainital"],
        ["almora", "nainital"],
        "medium",
        "Fair held in Almora and Nainital.",
        LUNAR,
    ),
    (
        "dussehra-diwali",
        "Dussehra and Diwali",
        [10, 11],
        "October-November",
        list(IDS),
        [],
        "medium",
        "Festive season across the state; holiday travel rises.",
        LUNAR,
    ),
    (
        "char-dham-closing",
        "Char Dham closing",
        [10, 11],
        "October-November",
        ["rudraprayag", "chamoli", "uttarkashi"],
        CHAR_DHAM,
        "high",
        "The shrines close for winter; closing dates are announced each year.",
        LUNAR,
    ),
    (
        "christmas-new-year",
        "Christmas-New Year rush",
        [12, 1],
        "December-January",
        ["dehradun", "nainital"],
        ["mussoorie", "nainital"],
        "high",
        "Holiday rush in Mussoorie and Nainital.",
        ANNUAL,
    ),
    (
        "auli-winter-snow",
        "Winter snow season at Auli",
        [12, 1, 2],
        "December-February",
        ["chamoli"],
        ["auli"],
        "medium",
        "Snow season at Auli.",
        "Depends on snowfall each year; verify locally.",
    ),
]

FESTIVALS: list[dict] = [
    {
        "id": fid,
        "name": name,
        "kind": "festival",
        "months": months,
        "window": window,
        "districts": districts,
        "destination_ids": dests,
        "crowd_impact": impact,
        "description": desc,
        "date_note": note,
        "start_date": None,
        "end_date": None,
        "curated": True,
        "sample": False,
    }
    for fid, name, months, window, districts, dests, impact, desc, note in _RAW
]
