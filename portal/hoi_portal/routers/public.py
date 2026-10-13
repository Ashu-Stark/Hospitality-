"""Public endpoints (no sign-in): search, registry, destinations, events, dictionary, rules, helplines, advisories,
grievance filing and tracking."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response

from .. import catalog, config, mongo, ratelimit
from ..schemas import GrievanceIn, TrackIn
from ..seed.destinations import BY_ID_DEST, DESTINATIONS
from ..seed.dictionary import CATEGORIES
from ..seed.districts import DISTRICTS
from ..services import (
    advisories,
    crowd,
    destinations,
    dictionary,
    events,
    grievances,
    locationiq,
    plan,
    registry,
    rules,
    search,
    traffic,
    weather,
)

router = APIRouter(prefix="/api/v1", tags=["public"])
SEARCH_RATE_PER_MINUTE = 60


@router.get("/meta")
def meta() -> dict:
    """Vocabularies for forms and filters."""
    return {
        "service": "Uttarakhand Tourism & Hospitality Portal (concept)",
        "banner": "Concept prototype for the AI-Tourism Hackathon 2026, not an official Government of Uttarakhand website. "
        "Data is sample/synthetic unless marked otherwise.",
        "districts": [dict(d) for d in DISTRICTS],
        "destinations": [{"id": d["id"], "name": d["name"], "district": d["district"]} for d in DESTINATIONS],
        "business_types": [{"key": k, "label": v[0], "code": v[1], "capacity_unit": v[2]} for k, v in catalog.BUSINESS_TYPES.items()],
        "business_statuses": list(catalog.BUSINESS_STATUSES),
        "documents_checklist": [{"key": k, "label": v} for k, v in catalog.CHECKLIST.items()],
        "required_documents": catalog.REQUIRED_DOCS,
        "grievance_categories": [{"key": k, "label": v} for k, v in catalog.GRIEVANCE_CATEGORIES.items()],
        "grievance_statuses": list(catalog.GRIEVANCE_STATUSES),
        "grievance_sla_days": catalog.GRIEVANCE_SLA_DAYS,
        "application_statuses": list(catalog.APPLICATION_STATUSES),
        "advisory_kinds": list(catalog.ADVISORY_KINDS),
        "road_statuses": list(catalog.ROAD_STATUSES),
        "crowd_bands": crowd.BANDS,
        "dictionary_categories": CATEGORIES,
        "languages": list(catalog.LANGUAGES),
        "reg_no_format": "UK-<TYPE CODE>-<DISTRICT CODE>-<NNNNN> (prototype codes, not official)",
        "demo_login": config.settings.demo_login,
        "experiences": [{"id": e["id"], "name": e["name"]} for e in plan.EXPERIENCES],
        "local_experience_types": [{"key": k, "label": v} for k, v in catalog.LOCAL_EXPERIENCE_TYPES.items()],
        "local_experience_host_types": list(catalog.LOCAL_EXPERIENCE_HOST_TYPES),
        "official_services": plan.official_services(),
    }


@router.get("/districts")
def districts() -> dict:
    return {"items": [dict(d) for d in DISTRICTS], "total": len(DISTRICTS)}


@router.get("/search")
def search_all(request: Request, q: str = Query(..., min_length=2, max_length=200), limit: int = Query(8, ge=1, le=25)) -> dict:
    ratelimit.hit(f"search:{ratelimit.client_ip(request)}", SEARCH_RATE_PER_MINUTE)
    return search.search(q, limit)


# ------------------------------------------------------------------ registry
@router.get("/registry")
def registry_list(
    type: str | None = None,
    district: str | None = None,
    destination: str | None = None,
    status: str | None = None,
    letter: str | None = Query(None, max_length=1),
    q: str | None = Query(None, max_length=200),
    verified: bool | None = None,
    page: int = Query(1, ge=1, le=1000),
    page_size: int = Query(24, ge=1, le=100),
    sort: str = Query("name", pattern="^(name|rating)$"),
) -> dict:
    """`type` accepts a comma list (stays = "hotel,homestay"); `sort=rating` lists the best rated first."""
    return registry.list_businesses(
        sort=sort,
        type=type,
        district=district,
        destination=destination,
        status=status,
        letter=letter,
        q=q,
        verified=verified,
        page=page,
        page_size=page_size,
    )


@router.get("/registry/verify")
def registry_verify(request: Request, reg_no: str = Query(..., min_length=1, max_length=40)) -> dict:
    ratelimit.hit(f"verify:{ratelimit.client_ip(request)}", config.settings.verify_rate_per_minute)
    return registry.verify(reg_no)


@router.get("/registry/{business}")
def registry_detail(business: str) -> dict:
    return registry.public(registry.get(business))


# ------------------------------------------------------------------ destinations
@router.get("/destinations")
def destination_list(district: str | None = None, tag: str | None = None, q: str | None = Query(None, max_length=200)) -> dict:
    return destinations.list_destinations(district, tag, q)


@router.get("/destinations/{dest_id}")
def destination_detail(dest_id: str) -> dict:
    return destinations.detail(dest_id)


@router.get("/destinations/{dest_id}/weather")
def destination_weather(dest_id: str) -> dict:
    return weather.for_destination(dest_id)


@router.get("/destinations/{dest_id}/crowd")
def destination_crowd(dest_id: str) -> dict:
    return crowd.for_destination(dest_id)


@router.get("/traffic/{dest_id}")
def traffic_prediction(dest_id: str, hours: int = Query(72, ge=1, le=72)) -> dict:
    """Predicted road congestion (index 0-100 + band) per hour for the next `hours`, the best time to drive and the
    factors behind it. Predicted, not measured; for planning. Live incidents are added when a provider answers."""
    if dest_id in BY_ID_DEST:
        weather.for_destination(dest_id)  # warm the forecast cache the model reads (cached 30 minutes)
    return traffic.predict(dest_id, hours)


@router.get("/destinations/{dest_id}/places")
def destination_places(dest_id: str, category: str | None = Query(None, max_length=30)) -> dict:
    """Useful places around a destination (hospital, pharmacy, ATM, fuel, police, viewpoints, places of worship) from
    LocationIQ / OpenStreetMap, cached 7 days. `available: false` when the server has no key or nothing was found."""
    return locationiq.places(dest_id, category)


@router.get("/destinations/{dest_id}/nearby")
def destination_nearby(dest_id: str, limit: int = Query(6, ge=1, le=23)) -> dict:
    """Other destinations by straight-line distance from approximate coordinates (not road distance)."""
    return plan.nearby(dest_id, limit)


# ------------------------------------------------------------------ plan: experiences, circuits, itineraries, map, links
@router.get("/experiences")
def experiences_list() -> dict:
    return plan.list_experiences()


@router.get("/experiences/{exp_id}")
def experience_detail(exp_id: str) -> dict:
    return plan.get_experience(exp_id)


@router.get("/circuits")
def circuits_list() -> dict:
    return plan.list_circuits()


@router.get("/itineraries")
def itineraries_list(theme: str | None = Query(None, max_length=30)) -> dict:
    return plan.list_itineraries(theme)


@router.get("/itineraries/{itin_id}")
def itinerary_detail(itin_id: str) -> dict:
    return plan.get_itinerary(itin_id)


@router.get("/map")
def map_points() -> dict:
    return plan.map_points()


@router.get("/map/static", response_class=Response, responses={200: {"content": {"image/png": {}}}})
def map_static(
    circuit: str | None = Query(None, max_length=40),
    theme: str | None = Query(None, max_length=30),
    district: str | None = Query(None, max_length=40),
) -> Response:
    """PNG map (LocationIQ, OpenStreetMap) with markers for the filtered destinations, served from our origin and cached
    7 days. 503 when the server has no LocationIQ key or the upstream fails (the web app then shows the schematic map)."""
    png = locationiq.static_map(circuit or None, theme or None, district or None)
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/official-services")
def official_services() -> dict:
    return plan.official_services()


@router.get("/district-offices")
def district_offices() -> dict:
    return plan.district_offices()


# ------------------------------------------------------------------ calendar, dictionary, rules, helplines, advisories
@router.get("/events")
def events_list(
    month: int | None = Query(None, ge=1, le=12),
    district: str | None = None,
    destination: str | None = None,
    q: str | None = Query(None, max_length=200),
) -> dict:
    return events.list_events(month, district, destination, q)


@router.get("/dictionary")
def dictionary_list(
    letter: str | None = Query(None, max_length=1), category: str | None = None, q: str | None = Query(None, max_length=200)
) -> dict:
    return dictionary.list_terms(letter, category, q)


@router.get("/dictionary/{term_id}")
def dictionary_term(term_id: str) -> dict:
    return dictionary.get(term_id)


@router.get("/rules")
def rules_list(business_type: str | None = None, q: str | None = Query(None, max_length=200)) -> dict:
    return rules.list_rules(business_type, q)


@router.get("/rules/{rule_id}")
def rules_card(rule_id: str) -> dict:
    return rules.get(rule_id)


@router.get("/helplines")
def helplines() -> dict:
    return rules.helplines()


@router.get("/advisories")
def advisories_list(district: str | None = None, destination: str | None = None, kind: str | None = None) -> dict:
    return advisories.list_public(district, destination, kind)


# ------------------------------------------------------------------ grievances
@router.post("/grievances", status_code=201)
def grievance_file(body: GrievanceIn, request: Request) -> dict:
    ratelimit.hit(f"grievance:{ratelimit.client_ip(request)}", config.settings.grievance_rate_per_hour, window_s=3600)
    return grievances.file(body.model_dump())


@router.post("/grievances/track")
def grievance_track(body: TrackIn, request: Request) -> dict:
    """POST so the tracking code never appears in URLs or access logs."""
    ratelimit.hit(f"track:{ratelimit.client_ip(request)}", config.settings.track_rate_per_minute)
    return grievances.track(body.ticket_id, body.tracking_code)


@router.get("/stats/public")
def public_stats() -> dict:
    """Small counters for the home page."""
    d = mongo.db()
    return {
        "businesses_listed": d.businesses.count_documents({}),
        "destinations": d.destinations.count_documents({}),
        "dictionary_terms": d.dictionary.count_documents({}),
        "active_advisories": d.advisories.count_documents(advisories.active_filter()),
        "synthetic": True,
    }
