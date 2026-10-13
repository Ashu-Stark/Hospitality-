"""Destinations, seasonality hints and road/route facts, exactly as curated in docs/PORTAL_SPEC.md section 5.

Everything here is "approximate, verify". Altitudes are NOT part of the curated set, so they are left empty
(`altitude_m: None`) rather than guessed. `profile` only selects the synthetic occupancy curve used by the seed
(see seed/generator.py); it is not a factual claim.
"""

from __future__ import annotations

from .districts import BY_ID, GARHWAL

APPROX = "Approximate, verify with official sources before travel."

# (id, name, lat, lon, district id, synthetic profile, tags, seed weight = how many synthetic businesses)
_RAW = [
    ("kedarnath", "Kedarnath", 30.735, 79.067, "rudraprayag", "char_dham", ["Char Dham", "pilgrimage", "trek"], 12),
    ("badrinath", "Badrinath", 30.744, 79.493, "chamoli", "char_dham", ["Char Dham", "pilgrimage"], 12),
    ("gangotri", "Gangotri", 30.994, 78.940, "uttarkashi", "char_dham", ["Char Dham", "pilgrimage"], 8),
    ("yamunotri", "Yamunotri", 31.014, 78.460, "uttarkashi", "char_dham", ["Char Dham", "pilgrimage", "trek"], 8),
    ("rishikesh", "Rishikesh", 30.087, 78.268, "dehradun", "spiritual", ["pilgrimage", "yoga"], 32),
    ("haridwar", "Haridwar", 29.945, 78.164, "haridwar", "spiritual", ["pilgrimage"], 28),
    ("mussoorie", "Mussoorie", 30.459, 78.064, "dehradun", "hill_station", ["hill town"], 25),
    ("dehradun", "Dehradun", 30.316, 78.032, "dehradun", "town", ["city"], 22),
    ("nainital", "Nainital", 29.380, 79.463, "nainital", "hill_station", ["hill town", "lake"], 25),
    ("jim-corbett-ramnagar", "Jim Corbett / Ramnagar", 29.394, 79.126, "nainital", "wildlife", ["wildlife", "national park"], 19),
    ("auli", "Auli", 30.528, 79.566, "chamoli", "snow", ["snow"], 10),
    ("valley-of-flowers", "Valley of Flowers", 30.728, 79.605, "chamoli", "vof", ["trek", "national park"], 5),
    ("chopta", "Chopta", 30.486, 79.211, "rudraprayag", "snow", ["snow", "trek"], 8),
    ("almora", "Almora", 29.597, 79.659, "almora", "town", ["hill town"], 12),
    ("kausani", "Kausani", 29.840, 79.600, "bageshwar", "hill_station", ["hill town"], 9),
    ("munsiyari", "Munsiyari", 30.067, 80.238, "pithoragarh", "snow", ["snow"], 9),
    ("lansdowne", "Lansdowne", 29.840, 78.680, "pauri-garhwal", "hill_station", ["hill town"], 9),
    ("dhanaulti", "Dhanaulti", 30.430, 78.240, "tehri-garhwal", "hill_station", ["hill town"], 7),
    ("new-tehri-tehri-lake", "New Tehri / Tehri Lake", 30.380, 78.430, "tehri-garhwal", "town", ["lake"], 8),
    ("lohaghat", "Lohaghat", 29.405, 80.090, "champawat", "town", ["hill town"], 7),
    ("bageshwar", "Bageshwar", 29.838, 79.771, "bageshwar", "town", ["town"], 6),
    ("pithoragarh", "Pithoragarh", 29.583, 80.218, "pithoragarh", "town", ["town"], 8),
    ("kashipur", "Kashipur", 29.210, 78.960, "udham-singh-nagar", "town", ["town"], 8),
    ("pauri", "Pauri", 30.150, 78.780, "pauri-garhwal", "town", ["hill town"], 7),
]

CHAR_DHAM_SEASON = "Char Dham shrines usually open around late April-May and close around October-November; dates are announced each year."
MONSOON = "Monsoon (July-September) brings landslide risk on hill roads."
SNOW = "Snow is usual here in winter."
CORBETT = "Corbett core zones close in the monsoon (verify current zone dates)."
VOF = "Valley of Flowers is usually open roughly June-October."

# Months (1-12) suggested only where the curated hints support it; None = no curated guidance.
_SEASON = {
    "char_dham": ([5, 6, 9, 10], [CHAR_DHAM_SEASON, MONSOON]),
    "vof": ([6, 7, 8, 9, 10], [VOF, MONSOON]),
    "snow": (None, [SNOW, MONSOON]),
    "wildlife": (None, [CORBETT, MONSOON]),
}

# Route facts per destination, verbatim in substance from section 5. No distances or times beyond these.
_ROUTES = {
    "badrinath": ["Reached along the Rishikesh-Badrinath corridor via NH-7."],
    "gangotri": ["Reached along the Rishikesh-Gangotri route via NH-34."],
    "kedarnath": ["Road to Gaurikund, then a trek of roughly 16-18 km.", "Helicopter services also operate from the valley."],
    "yamunotri": ["Road to Janki Chatti, then a trek of about 5-6 km."],
    "valley-of-flowers": ["Reached via Govindghat and Ghangaria (trek)."],
}
AIRPORT = {
    GARHWAL: "Jolly Grant (Dehradun) is the nearest major airport for Garhwal.",
    "Kumaon": "Pantnagar is the nearest major airport for Kumaon.",
}
RAILHEADS = {
    GARHWAL: "Major railheads in Garhwal: Dehradun, Haridwar, Rishikesh (Yog Nagari Rishikesh).",
    "Kumaon": "Major railheads in Kumaon: Kathgodam, Ramnagar, Tanakpur.",
}

# One-line "why go", in our own words, built only from the curated facts above and in section 5 (tags, festivals,
# route facts, seasonality hints). No superlatives, distances, altitudes or other new facts.
WHY_GO: dict[str, str] = {
    "kedarnath": "One of the four Char Dham shrines, reached by road to Gaurikund and then a trek.",
    "badrinath": "Char Dham shrine on the Rishikesh-Badrinath corridor (NH-7).",
    "gangotri": "Char Dham shrine on the Rishikesh-Gangotri route (NH-34).",
    "yamunotri": "Char Dham shrine reached by road to Janki Chatti, then a short trek.",
    "rishikesh": "River town known for yoga; the International Yoga Festival is held here in March.",
    "haridwar": "River town for pilgrimage; Ganga Dussehra and the Kanwar Yatra bring big crowds.",
    "mussoorie": "Hill town above Dehradun; busy over the Christmas-New Year holidays.",
    "dehradun": "Gateway city for Garhwal, with Jolly Grant airport and a major railhead.",
    "nainital": "Lake town in Kumaon; the Nanda Devi fair and year-end holidays bring crowds.",
    "jim-corbett-ramnagar": "National park on the foothills; core zones close in the monsoon (verify zone dates).",
    "auli": "Snow destination with a winter snow season, usually December-February.",
    "valley-of-flowers": "Flower meadows, usually open roughly June-October; trek via Govindghat and Ghangaria.",
    "chopta": "Base for treks, with snow in winter.",
    "almora": "Hill town in Kumaon where the Nanda Devi fair is held.",
    "kausani": "Hill town on the Kumaon hills circuit.",
    "munsiyari": "Kumaon hill town in Pithoragarh district, with snow in winter.",
    "lansdowne": "Small hill town in Pauri Garhwal on the Garhwal hill stations circuit.",
    "dhanaulti": "Hill town in Tehri Garhwal, on the same circuit as Mussoorie.",
    "new-tehri-tehri-lake": "Lake town in Tehri Garhwal on the Garhwal hill stations circuit.",
    "lohaghat": "Hill town in Champawat district on the Kumaon hills circuit.",
    "bageshwar": "Temple town where the Uttarayani fair is held around Makar Sankranti.",
    "pithoragarh": "Town in Pithoragarh district on the Kumaon hills circuit.",
    "kashipur": "Foothill town in Udham Singh Nagar, on the Corbett & foothills circuit.",
    "pauri": "Hill town in Pauri Garhwal on the Garhwal hill stations circuit.",
}
WHY_GO_NOTE = "Our short wording from the curated reference facts; verify before travel."

# destination id -> theme ids. Every curated destination is listed (an empty list means no curated theme fits).
THEMES: dict[str, list[str]] = {
    "kedarnath": ["spiritual", "adventure"],
    "badrinath": ["spiritual"],
    "gangotri": ["spiritual"],
    "yamunotri": ["spiritual", "adventure"],
    "rishikesh": ["spiritual", "wellness", "adventure"],
    "haridwar": ["spiritual", "wellness"],
    "mussoorie": ["leisure"],
    "dehradun": ["leisure"],
    "nainital": ["leisure", "culture"],
    "jim-corbett-ramnagar": ["wildlife"],
    "auli": ["adventure"],
    "valley-of-flowers": ["wildlife", "adventure"],
    "chopta": ["adventure"],
    "almora": ["leisure", "culture"],
    "kausani": ["leisure"],
    "munsiyari": ["adventure"],
    "lansdowne": ["leisure"],
    "dhanaulti": ["leisure"],
    "new-tehri-tehri-lake": ["leisure"],
    "lohaghat": ["leisure"],
    "bageshwar": ["culture"],
    "pithoragarh": [],
    "kashipur": [],
    "pauri": ["leisure"],
}


def build() -> list[dict]:
    out = []
    for did, name, lat, lon, district, profile, tags, weight in _RAW:
        division = BY_ID[district]["division"]
        best, notes = _SEASON.get(profile, (None, [MONSOON]))
        routes = list(_ROUTES.get(did, []))
        routes += [AIRPORT[division], RAILHEADS[division]]
        out.append(
            {
                "id": did,
                "name": name,
                "district": district,
                "division": division,
                "lat": lat,
                "lon": lon,
                "altitude_m": None,
                "altitude_note": "Altitude not in the curated reference set yet; to be added from an official source.",
                "tags": tags,
                "themes": list(THEMES.get(did, [])),
                "best_months": best,
                "season_notes": notes,
                "route_facts": routes,
                "facts_note": APPROX,
                "why_go": WHY_GO[did],
                "profile": profile,
                "seed_weight": weight,
            }
        )
    return out


DESTINATIONS = build()
BY_ID_DEST = {d["id"]: d for d in DESTINATIONS}
