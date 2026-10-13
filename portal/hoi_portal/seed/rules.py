"""Rules, licences & schemes cards and helplines (docs/PORTAL_SPEC.md section 5).

Orientation only. No section numbers, fees, thresholds or act names are given beyond the curated list; every card
carries VERIFY. Typical documents are generic examples, not an official checklist.
"""

from __future__ import annotations

VERIFY = "Summary for orientation, verify with the issuing authority."
GENERIC_DOCS = ["Identity proof of the owner or operator", "Address proof of the premises", "Ownership or lease papers for the premises"]

# id, title, who, covers, documents, where to apply, applies to business types, tags
_RAW = [
    (
        "state-tourism-trade-registration",
        "State tourism trade registration",
        "Tourism businesses such as hotels, homestays, travel agents, tour operators and guides that want to operate and be listed.",
        "Registration of the business with the state tourism authority.",
        GENERIC_DOCS + ["Basic details of the business (type, capacity, location)"],
        "Check with the state tourism department/board.",
        ["hotel", "homestay", "guide", "travel_agent", "tour_operator", "transport", "adventure_operator", "restaurant"],
        ["registration", "tourism"],
    ),
    (
        "homestay-registration",
        "Homestay registration (state homestay scheme)",
        "Residents who host paying guests in their own home.",
        "Registration under the state homestay scheme; the scheme's name and terms should be verified.",
        GENERIC_DOCS + ["Photographs of the rooms offered to guests"],
        "Check with the state tourism department/board (scheme name and terms to verify).",
        ["homestay"],
        ["homestay", "scheme"],
    ),
    (
        "fssai",
        "FSSAI registration / licence",
        "Businesses that prepare, serve or sell food, including restaurants and stays that serve meals.",
        "Food safety registration or licence; which one applies depends on the business.",
        GENERIC_DOCS + ["Details of the food served and the kitchen"],
        "Food Safety and Standards Authority of India (FSSAI).",
        ["hotel", "homestay", "restaurant"],
        ["food", "licence"],
    ),
    (
        "gst",
        "GST registration",
        "Businesses whose turnover or activity requires registration; the threshold depends on turnover and state.",
        "Registration under the Goods and Services Tax.",
        ["PAN of the business or owner", "Address proof of the place of business", "Bank account details"],
        "Ask a GST practitioner whether and how you must register.",
        ["hotel", "homestay", "travel_agent", "tour_operator", "transport", "adventure_operator", "restaurant"],
        ["tax"],
    ),
    (
        "fire-safety-noc",
        "Fire safety NOC",
        "Larger premises, such as bigger hotels and restaurants.",
        "Clearance that the building meets fire safety requirements.",
        ["Building plan", "Details of fire safety equipment"],
        "The fire service for your area.",
        ["hotel", "restaurant"],
        ["safety", "noc"],
    ),
    (
        "pollution-consent",
        "Pollution control board consent",
        "Premises whose activities need consent, where applicable.",
        "Consent from the pollution control board related to waste water, emissions or waste.",
        GENERIC_DOCS + ["Details of water use and waste handling"],
        "The state pollution control board.",
        ["hotel", "restaurant"],
        ["environment"],
    ),
    (
        "trade-licence",
        "Trade licence",
        "Businesses operating within a local body's area.",
        "Permission from the local body to run the business at the premises.",
        GENERIC_DOCS,
        "The local body (municipality, nagar panchayat or gram panchayat).",
        ["hotel", "homestay", "travel_agent", "tour_operator", "transport", "adventure_operator", "restaurant"],
        ["local body", "licence"],
    ),
    (
        "form-c",
        "Form C reporting of foreign guests",
        "Accommodation providers who host foreign guests.",
        "Reporting each foreign guest's stay to the FRRO.",
        ["Guest's passport and visa details", "Stay dates"],
        "Foreigners Regional Registration Office (FRRO).",
        ["hotel", "homestay"],
        ["foreign guests", "reporting"],
    ),
    (
        "guide-licensing",
        "Guide licensing / training",
        "People who work as tourist or trekking guides.",
        "Licensing or training requirements for guides (verify which apply).",
        ["Identity proof", "Training or experience certificates, if any"],
        "Check with the state tourism department/board.",
        ["guide"],
        ["guide", "training"],
    ),
    (
        "adventure-permits",
        "Adventure activity permits and safety rules",
        "Operators of rafting, trekking, paragliding and similar activities.",
        "Permits and safety rules for adventure activities (verify which apply).",
        GENERIC_DOCS + ["Equipment and safety details", "Staff training details"],
        "Check with the district administration and the forest department.",
        ["adventure_operator", "tour_operator"],
        ["adventure", "safety"],
    ),
    (
        "inner-line-permit",
        "Inner line permits",
        "Visitors to certain border areas.",
        "Permission to enter notified border areas.",
        ["Identity proof", "Travel details"],
        "The district administration.",
        [],
        ["permit", "border areas"],
    ),
    (
        "forest-entry-permit",
        "Forest / protected-area entry permits",
        "Visitors to national parks, sanctuaries and other protected areas.",
        "Entry permission for protected areas.",
        ["Identity proof", "Visit details"],
        "The forest department / park administration.",
        ["guide", "tour_operator", "adventure_operator"],
        ["permit", "forest"],
    ),
]

RULES: list[dict] = [
    {
        "id": rid,
        "title": title,
        "who_needs_it": who,
        "what_it_covers": covers,
        "typical_documents": docs,
        "where_to_apply": where,
        "business_types": types,
        "tags": tags,
        "verify_note": VERIFY,
    }
    for rid, title, who, covers, docs, where, types, tags in _RAW
]

PLACEHOLDER = "To be filled by the department."
HELPLINES: list[dict] = [
    {"id": "emergency-112", "name": "All-India emergency", "number": "112", "scope": "national", "note": "Police, fire and ambulance."},
    {"id": "ambulance-108", "name": "Ambulance", "number": "108", "scope": "national", "note": None},
    {
        "id": "tourist-helpline-1363",
        "name": "Ministry of Tourism tourist helpline",
        "number": "1363 / 1800-11-1363",
        "scope": "national",
        "note": None,
    },
    {
        "id": "disaster-1077",
        "name": "District disaster control room",
        "number": "1077",
        "scope": "district",
        "note": "Verify per district.",
    },
    {"id": "state-tourism-helpline", "name": "State tourism helpline", "number": None, "scope": "state", "note": PLACEHOLDER},
    {"id": "police-tourist-help", "name": "Police tourist help", "number": None, "scope": "state", "note": PLACEHOLDER},
]
