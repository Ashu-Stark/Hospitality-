"""Experiences (themes), circuits, sample itineraries, official external services and district tourism office placeholders.

Curated for the concept from docs/PORTAL_SPEC.md section 5 only:
* Theme membership uses well-known characteristics already in the curated set (Char Dham shrines, yoga at Rishikesh,
  national parks, snow and treks, hill towns, curated fairs). No new facts.
* Intros are our own short wording. They state no distances, travel times, prices, altitudes or dates.
* Itineraries are SAMPLE planning suggestions built only from curated destinations. `suggested_days` is a planning
  suggestion, not a fact; routes and timings must be verified.
"""

from __future__ import annotations

from .destinations import BY_ID_DEST, THEMES

EXPERIENCES: list[dict] = [
    {
        "id": "spiritual",
        "name": "Spiritual & Char Dham",
        "short": "Shrines, ghats and the yatra season.",
        "intro": (
            "Uttarakhand is one of India's best-known pilgrimage regions. The four Char Dham shrines open for a season each "
            "year and close for winter, and the river towns of Haridwar and Rishikesh draw visitors all year for prayer and the "
            "evening aarti. Plan around the yatra calendar: opening and closing dates are announced each year, and the crowd "
            "busy level below shows how busy each place is likely to be."
        ),
        "icon": "temple",
        "festival_ids": ["char-dham-opening", "char-dham-closing", "ganga-dussehra", "kanwar-yatra"],
        "term_ids": ["char-dham", "yatra", "dham", "ghat", "aarti", "pilgrimage-tourism", "palki", "pony-and-mule-services"],
    },
    {
        "id": "adventure",
        "name": "Adventure & Treks",
        "short": "Treks, snow and high meadows.",
        "intro": (
            "Treks to shrines and meadows, winter snow at higher places such as Auli, Chopta and Munsiyari, and river activities around Rishikesh (permits apply) make the state a base "
            "for adventure. Conditions change quickly in the mountains: check the weather and road alerts on each destination page, "
            "go with a registered guide or operator, and read the trekking and safety terms below before you set out."
        ),
        "icon": "peak",
        "festival_ids": ["auli-winter-snow"],
        "term_ids": [
            "trek",
            "trail",
            "acclimatisation",
            "altitude-sickness",
            "base-camp",
            "bugyal",
            "guide",
            "layering",
            "snowline",
            "permit",
        ],
    },
    {
        "id": "wildlife",
        "name": "Wildlife & Nature",
        "short": "National parks and flower meadows.",
        "intro": (
            "Protected areas such as Corbett and the Valley of Flowers are open only in certain seasons and need entry permits; "
            "zones and dates change, so verify them with the forest department before you plan. Travel light, keep to marked "
            "trails and leave no trace."
        ),
        "icon": "leaf",
        "festival_ids": ["harela"],
        "term_ids": ["ecotourism", "responsible-tourism", "leave-no-trace", "carrying-capacity", "permit", "monsoon"],
    },
    {
        "id": "wellness",
        "name": "Yoga & Wellness",
        "short": "Yoga, the river and slow days.",
        "intro": (
            "Rishikesh is widely known for yoga, and the riverside towns of Rishikesh and Haridwar suit slow, restful stays. "
            "Choose a registered stay, check how busy it will be before festival weeks, and see the yoga festival in the calendar."
        ),
        "icon": "lotus",
        "festival_ids": ["international-yoga-festival", "ganga-dussehra"],
        "term_ids": ["ghat", "aarti", "dharamshala", "average-length-of-stay-alos", "shoulder-season"],
    },
    {
        "id": "leisure",
        "name": "Hill towns & Leisure",
        "short": "Lakes, ridges and family breaks.",
        "intro": (
            "Hill towns and lake towns are easy breaks from the plains. They get busy on long weekends and over the Christmas-New Year "
            "holidays, so the crowd outlook helps you pick quieter days. In the monsoon, hill roads can be affected by landslides."
        ),
        "icon": "lake",
        "festival_ids": ["christmas-new-year"],
        "term_ids": ["tal", "peak-season", "off-season", "shoulder-season", "homestay", "day-tripper", "landslide"],
    },
    {
        "id": "culture",
        "name": "Culture & Fairs",
        "short": "Fairs, seasonal festivals and local life.",
        "intro": (
            "Seasonal festivals and fairs such as Uttarayani in Bageshwar and the Nanda Devi fair in Almora and Nainital are part of "
            "local life in the hills. Dates follow the lunar calendar, so check the official notice each year. Homestays are a good "
            "way to experience Garhwali and Kumaoni culture."
        ),
        "icon": "drum",
        "festival_ids": ["uttarayani-fair", "nanda-devi-fair", "phool-dei", "harela", "dussehra-diwali"],
        "term_ids": ["mela", "pahadi", "garhwali-and-kumaoni", "homestay", "rural-tourism"],
    },
]
BY_ID_EXP = {e["id"]: e for e in EXPERIENCES}

CIRCUITS: list[dict] = [
    {
        "id": "char-dham",
        "name": "Char Dham",
        "theme": "spiritual",
        "description": "The four shrines, usually visited west to east: Yamunotri, Gangotri, Kedarnath, Badrinath.",
        "destination_ids": ["yamunotri", "gangotri", "kedarnath", "badrinath"],
    },
    {
        "id": "rishikesh-haridwar",
        "name": "Rishikesh-Haridwar: spiritual & wellness",
        "theme": "wellness",
        "description": "The two river towns at the foot of the hills.",
        "destination_ids": ["haridwar", "rishikesh"],
    },
    {
        "id": "garhwal-hill-stations",
        "name": "Garhwal hill stations",
        "theme": "leisure",
        "description": "Hill towns of Dehradun, Tehri Garhwal and Pauri Garhwal districts.",
        "destination_ids": ["dehradun", "mussoorie", "dhanaulti", "new-tehri-tehri-lake", "pauri", "lansdowne"],
    },
    {
        "id": "kumaon-hills",
        "name": "Kumaon hills",
        "theme": "leisure",
        "description": "Lakes and ridges of Kumaon.",
        "destination_ids": ["nainital", "almora", "kausani", "bageshwar", "munsiyari", "pithoragarh", "lohaghat"],
    },
    {
        "id": "corbett-foothills",
        "name": "Corbett & foothills",
        "theme": "wildlife",
        "description": "The national park and the foothill towns around it.",
        "destination_ids": ["jim-corbett-ramnagar", "kashipur", "nainital"],
    },
]
BY_ID_CIRCUIT = {c["id"]: c for c in CIRCUITS}

ITINERARY_NOTE = (
    "Sample plan for orientation. Suggested days are a planning suggestion, not a schedule. Verify routes, road status, "
    "shrine and park dates, and timings with official sources before you travel."
)

ITINERARIES: list[dict] = [
    {
        "id": "char-dham-yatra",
        "name": "Char Dham yatra",
        "theme": "spiritual",
        "circuit_id": "char-dham",
        "summary": "All four shrines, starting and ending at the river towns.",
        "stops": [("haridwar", 1), ("yamunotri", 2), ("gangotri", 2), ("kedarnath", 2), ("badrinath", 2), ("rishikesh", 1)],
    },
    {
        "id": "do-dham",
        "name": "Do Dham: Kedarnath and Badrinath",
        "theme": "spiritual",
        "circuit_id": "char-dham",
        "summary": "The two eastern shrines from Rishikesh.",
        "stops": [("rishikesh", 1), ("kedarnath", 2), ("badrinath", 2)],
    },
    {
        "id": "rishikesh-haridwar-wellness",
        "name": "Rishikesh and Haridwar: yoga and the river",
        "theme": "wellness",
        "circuit_id": "rishikesh-haridwar",
        "summary": "A slow stay by the river.",
        "stops": [("haridwar", 1), ("rishikesh", 3)],
    },
    {
        "id": "mussoorie-weekend",
        "name": "Mussoorie and Dhanaulti weekend",
        "theme": "leisure",
        "circuit_id": "garhwal-hill-stations",
        "summary": "A short hill break from Dehradun.",
        "stops": [("dehradun", 1), ("mussoorie", 2), ("dhanaulti", 1)],
    },
    {
        "id": "kumaon-lakes-ridges",
        "name": "Kumaon lakes and ridges",
        "theme": "leisure",
        "circuit_id": "kumaon-hills",
        "summary": "Lake town, old hill town and a ridge.",
        "stops": [("nainital", 2), ("almora", 1), ("kausani", 2)],
    },
    {
        "id": "corbett-nainital",
        "name": "Corbett and Nainital",
        "theme": "wildlife",
        "circuit_id": "corbett-foothills",
        "summary": "The national park, then the lake town.",
        "stops": [("jim-corbett-ramnagar", 2), ("nainital", 2)],
    },
    {
        "id": "valley-of-flowers-badrinath",
        "name": "Valley of Flowers and Badrinath",
        "theme": "wildlife",
        "circuit_id": None,
        "summary": "Flower meadows in season, then the shrine.",
        "stops": [("valley-of-flowers", 3), ("badrinath", 1)],
    },
    {
        "id": "snow-and-meadows",
        "name": "Chopta and Auli: snow and meadows",
        "theme": "adventure",
        "circuit_id": None,
        "summary": "Two high places for treks and winter snow.",
        "stops": [("chopta", 2), ("auli", 2)],
    },
]
BY_ID_ITIN = {i["id"]: i for i in ITINERARIES}

OFFICIAL_SERVICES: list[dict] = [
    {
        "id": "char-dham-registration",
        "name": "Char Dham yatra registration",
        "url": "https://registrationandtouristcare.uk.gov.in/",
        "description": "Official registration for Char Dham pilgrims.",
    },
    {
        "id": "homestay-booking",
        "name": "Homestay booking",
        "url": "https://uttarastays.com/",
        "description": "Official homestay booking site.",
    },
]
OFFICIAL_SERVICES_NOTE = "Official site, opens in a new tab; not part of this concept."


def validate() -> None:
    """Fail fast if curated content references unknown destinations (run at import and in tests)."""
    missing = set(BY_ID_DEST) - set(THEMES)
    assert not missing, f"themes missing for {missing}"
    for t in THEMES.values():
        assert set(t) <= set(BY_ID_EXP), t
    for c in CIRCUITS:
        assert all(d in BY_ID_DEST for d in c["destination_ids"]), c["id"]
    for i in ITINERARIES:
        assert all(d in BY_ID_DEST for d, _ in i["stops"]), i["id"]


validate()
