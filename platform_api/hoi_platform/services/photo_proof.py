"""Photo proof: which jobs need a before / after photo. A per-hotel setting with ASSUMED defaults.

Photos cost the worker time, so they are asked for only where they prove something: a cleaned room (before and after),
a repair, pest treatment or damage (after), a lost-and-found hand-over (after). A towel run, a tea order, a Wi-Fi check,
an express checkout or a safety / medical alert never waits for a photo.

Every job maps to one proof kind:
  - room-board jobs by their dispatch kind ("cleaning", "maintenance" -> repair, "guest_checkout" -> checkout)
  - guest requests (dispatch kind "guest") by their menu key (rooms.GUEST_MENU: the request menu plus the
    guest_issues.yaml taxonomy), stored on the job as `request`
  - worker voice reports ("general", source "voice") by their guest_issues type, else "damage"
  - other manager-created "general" jobs: maintenance department -> repair, anything else -> general
The defaults below are ASSUMED (to be reviewed with the hospitality-management student); each hotel's owner can change them.
"""

from __future__ import annotations

from . import tenants
from .errors import Invalid

SETTING = "photo_proof"

# kind -> (plain-words label, before, after). Order = order on the settings page.
DEFAULTS: dict[str, tuple[str, bool, bool]] = {
    "cleaning": ("Room cleaning (checkout clean, 'clean my room', dirty-room complaint)", True, True),
    "repair": ("Repairs and maintenance (AC, heater, hot water, lights, leaks, locks)", False, True),
    "pest_control": ("Pest control (rats, cockroaches, bedbugs)", False, True),
    "damage": ("Damage or a problem reported by staff", False, True),
    "lost_found": ("Lost and found items", False, True),
    "delivery": ("Deliveries (towels, drinking water, toiletries, tea, food)", False, False),
    "guest_help": ("Other guest requests (noise, Wi-Fi, front desk call-back)", False, False),
    "alert": ("Safety and medical alerts", False, False),
    "checkout": ("Express checkout", False, False),
    "general": ("Other jobs added by a manager", False, False),
}

# guest request menu key / guest_issues type -> proof kind
REQUEST_KIND = {
    "cleaning": "cleaning",
    "cleanliness": "cleaning",
    "ac": "repair",
    "hot_water": "repair",
    "electrical": "repair",
    "water_leak": "repair",
    "lock_or_door": "repair",
    "pest_control": "pest_control",
    "lost_item": "lost_found",
    "towels": "delivery",
    "water": "delivery",
    "amenities": "delivery",
    "tea": "delivery",
    "food": "delivery",
    "safety_alert": "alert",
    "medical_help": "alert",
    "noise_complaint": "guest_help",
    "wifi_problem": "guest_help",
    "other": "guest_help",
}


def proof_kind(job: dict) -> str:
    kind, req = job.get("kind") or "general", job.get("request")
    if kind == "cleaning":
        return "cleaning"
    if kind == "maintenance":
        return "repair"
    if kind == "guest_checkout":
        return "checkout"
    if kind == "guest":
        return REQUEST_KIND.get(req or "", "guest_help")
    if req in REQUEST_KIND:  # a worker's voice report classified by the guest-issue taxonomy
        return REQUEST_KIND[req]
    if job.get("source") == "voice":
        return "damage"
    return "repair" if job.get("department") == "maintenance" else "general"


def _rows(rules: dict[str, dict]) -> list[dict]:
    return [{"kind": k, "label": DEFAULTS[k][0], "before": rules[k]["before"], "after": rules[k]["after"]} for k in DEFAULTS]


def default_rules() -> dict[str, dict]:
    return {k: {"before": b, "after": a} for k, (_, b, a) in DEFAULTS.items()}


def rules_from_settings(settings: dict) -> dict[str, dict]:
    """The hotel's rules: saved values over the defaults (kinds added later fall back to their default)."""
    out = default_rules()
    saved = settings.get(SETTING) or {}
    if isinstance(saved, dict):
        for k, v in saved.items():
            if k in out and isinstance(v, dict):
                out[k] = {"before": bool(v.get("before")), "after": bool(v.get("after"))}
    return out


def rules(tid: str) -> dict[str, dict]:
    return rules_from_settings(tenants.get_tenant(tid)["settings"])


def required(job: dict, hotel_rules: dict[str, dict]) -> dict:
    """{"kind", "before", "after"}: the photos this job needs before Start / Done."""
    k = proof_kind(job)
    r = hotel_rules.get(k) or {"before": False, "after": False}
    return {"kind": k, "before": bool(r["before"]), "after": bool(r["after"])}


def get(tid: str) -> dict:
    return {"kinds": _rows(rules(tid)), "defaults": _rows(default_rules())}


def put(tid: str, rows: list[dict], actor: str) -> dict:
    unknown = sorted({str(r.get("kind")) for r in rows} - set(DEFAULTS))
    if unknown:
        raise Invalid(f"Unknown job kind {unknown[0]!r}. Known kinds: {', '.join(DEFAULTS)}.")
    settings = tenants.get_tenant(tid)["settings"]
    cur = rules_from_settings(settings)
    for r in rows:
        cur[r["kind"]] = {"before": bool(r["before"]), "after": bool(r["after"])}
    settings[SETTING] = cur
    tenants.update_tenant(tid, settings=settings)
    tenants.audit(tid, actor, "settings.photo_proof", ",".join(f"{k}:{int(v['before'])}{int(v['after'])}" for k, v in cur.items()))
    return get(tid)
