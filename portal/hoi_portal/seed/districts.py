"""The 13 districts and their divisions (docs/PORTAL_SPEC.md section 5).

`code` is a three-letter code invented for this prototype's registration-number format
(UK-<TYPE>-<DISTRICT CODE>-<NNNNN>); it is not an official code.
"""

from __future__ import annotations

GARHWAL, KUMAON = "Garhwal", "Kumaon"

DISTRICTS: list[dict] = [
    {"id": "almora", "name": "Almora", "code": "ALM", "division": KUMAON},
    {"id": "bageshwar", "name": "Bageshwar", "code": "BAG", "division": KUMAON},
    {"id": "chamoli", "name": "Chamoli", "code": "CHM", "division": GARHWAL},
    {"id": "champawat", "name": "Champawat", "code": "CPT", "division": KUMAON},
    {"id": "dehradun", "name": "Dehradun", "code": "DDN", "division": GARHWAL},
    {"id": "haridwar", "name": "Haridwar", "code": "HDW", "division": GARHWAL},
    {"id": "nainital", "name": "Nainital", "code": "NTL", "division": KUMAON},
    {"id": "pauri-garhwal", "name": "Pauri Garhwal", "code": "PAU", "division": GARHWAL},
    {"id": "pithoragarh", "name": "Pithoragarh", "code": "PTH", "division": KUMAON},
    {"id": "rudraprayag", "name": "Rudraprayag", "code": "RUD", "division": GARHWAL},
    {"id": "tehri-garhwal", "name": "Tehri Garhwal", "code": "TEH", "division": GARHWAL},
    {"id": "udham-singh-nagar", "name": "Udham Singh Nagar", "code": "USN", "division": KUMAON},
    {"id": "uttarkashi", "name": "Uttarkashi", "code": "UKI", "division": GARHWAL},
]

BY_ID = {d["id"]: d for d in DISTRICTS}
IDS = tuple(BY_ID)
