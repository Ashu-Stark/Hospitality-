"""Guest issue understanding v2 (hoi_platform/guest_issues.yaml + services/issues.py): table-driven utterances in English,
Devanagari Hindi and Hinglish (typos included, every live failure of 13 Oct included), the rule-based concierge replies, the
LLM consistency fixes (fake model), the urgent safety/medical flow and the worker's voice report. SYNTHETIC text only.
"""

import pytest
from conftest import auth
from test_concierge import FakeChat, room

from hoi_platform import mongo, ratelimit
from hoi_platform.services import ai, concierge, issues, voice

# (utterance, expected type or None, department, urgency)
CASES = [
    # live failures (13 Oct)
    ("there is a rat in the room", "pest_control", "housekeeping", "high"),
    ("cockroach in the bathroom", "pest_control", "housekeeping", "high"),
    ("चूहा है कमरे में", "pest_control", "housekeeping", "high"),
    ("room mein chuha hai", "pest_control", "housekeeping", "high"),
    ("too much noise from next door", "noise_complaint", "front_office", "medium"),
    ("smoke smell in corridor", "safety_alert", "front_office", "urgent"),
    ("water leaking from ceiling", "water_leak", "maintenance", "high"),
    ("door lock is broken", "lock_or_door", "maintenance", "high"),
    ("bedsheet dirty and smells", "cleanliness", "housekeeping", "high"),
    ("I feel unwell, need a doctor", "medical_help", "front_office", "urgent"),
    # pests (EN / HI / Hinglish / typos)
    ("there are bedbugs on the bed", "pest_control", "housekeeping", "high"),
    ("khatmal hai bistar mein", "pest_control", "housekeeping", "high"),
    ("छिपकली दीवार पर है", "pest_control", "housekeeping", "high"),
    ("machhar bahut hain", "pest_control", "housekeeping", "high"),
    ("ants on the table", "pest_control", "housekeeping", "high"),
    ("kakroach dikha", "pest_control", "housekeeping", "high"),
    ("cockroch in my room", "pest_control", "housekeeping", "high"),
    ("there's a lizzard", "pest_control", "housekeeping", "high"),
    ("mosquitos everywhere", "pest_control", "housekeeping", "high"),
    ("kamre mein keede hain", "pest_control", "housekeeping", "high"),
    ("मच्छर बहुत हैं", "pest_control", "housekeeping", "high"),
    # medical
    ("mujhe doctor chahiye", "medical_help", "front_office", "urgent"),
    ("तबीयत ख़राब है, डॉक्टर चाहिए", "medical_help", "front_office", "urgent"),
    ("seene mein dard ho raha hai", "medical_help", "front_office", "urgent"),
    ("someone fainted in the room", "medical_help", "front_office", "urgent"),
    ("I am not feeling well", "medical_help", "front_office", "urgent"),
    ("tabiyat kharab hai", "medical_help", "front_office", "urgent"),
    # safety
    ("there is a fire!", "safety_alert", "front_office", "urgent"),
    ("aag lagi hai", "safety_alert", "front_office", "urgent"),
    ("धुआँ आ रहा है", "safety_alert", "front_office", "urgent"),
    ("gas ki smell aa rahi hai", "safety_alert", "front_office", "urgent"),
    ("sparks from the socket", "safety_alert", "front_office", "urgent"),
    # leaks
    ("paani tapak raha hai chhat se", "water_leak", "maintenance", "high"),
    ("नल से पानी टपक रहा है", "water_leak", "maintenance", "high"),
    ("bathroom floor flooded", "water_leak", "maintenance", "high"),
    # doors and locks
    ("darwaza band nahi ho raha", "lock_or_door", "maintenance", "high"),
    ("ताला ख़राब है", "lock_or_door", "maintenance", "high"),
    ("key card not working", "lock_or_door", "maintenance", "high"),
    ("locked out of my room", "lock_or_door", "maintenance", "high"),
    # cleanliness
    ("toilet is dirty", "cleanliness", "housekeeping", "high"),
    ("badbu aa rahi hai", "cleanliness", "housekeeping", "high"),
    ("चादर गंदी है", "cleanliness", "housekeeping", "high"),
    # noise, lost items, wifi
    ("loud music upstairs", "noise_complaint", "front_office", "medium"),
    ("shor bahut hai", "noise_complaint", "front_office", "medium"),
    ("I lost my phone", "lost_item", "front_office", "medium"),
    ("mera charger kho gaya", "lost_item", "front_office", "medium"),
    ("wifi not working", "wifi_problem", "front_office", "medium"),
    # nothing to report: generic words, negations, questions, false friends
    ("room", None, None, None),
    ("kamra", None, None, None),
    ("कमरा", None, None, None),
    ("the room is nice", None, None, None),
    ("no rat now", None, None, None),
    ("chuha nahi hai ab", None, None, None),
    ("wifi password?", None, None, None),
    ("what is the wifi password", None, None, None),
    ("is breakfast included?", None, None, None),
    ("bonfire tonight?", None, None, None),
    ("is the fire place working", None, None, None),
    ("no smoke, just checking the heater", None, None, None),
]


@pytest.mark.parametrize("text,typ,dept,urgency", CASES)
def test_classify(text, typ, dept, urgency):
    hit = issues.top(text)
    if typ is None:
        assert hit is None, (text, hit)
        return
    assert hit and hit["type"] == typ, (text, hit)
    assert hit["department"] == dept and hit["urgency"] == urgency


def test_priority_and_multi_issue():
    assert [h["type"] for h in issues.classify("a mouse and smoke in the room")] == ["safety_alert", "pest_control"]
    assert [h["type"] for h in issues.classify("rat and leak in bathroom")] == ["pest_control", "water_leak"]
    assert [h["type"] for h in issues.classify("gas leak!")] == ["safety_alert"]  # "leak" inside "gas leak" is not a second issue


@pytest.fixture(autouse=True)
def _fresh():
    ratelimit.reset()
    ai.use(chat=FakeChat("not json"))  # deterministic: the rules answer unless a test sets a fake model
    yield
    ai.use()
    ratelimit.reset()


def _ctx(client, owner):
    return concierge.context(room(client, owner)["guest_token"])


@pytest.mark.parametrize(
    "text,typ,check",
    [
        ("there is a rat in the room", "pest_control", "Sorry about the rat"),
        ("room mein chuha hai", "pest_control", "chuha ke liye sorry"),
        ("चूहा है कमरे में", "pest_control", "चूहे के लिए माफ़ी"),
        ("water leaking from ceiling", "water_leak", "the maintenance team"),
        ("door lock is broken", "lock_or_door", "the maintenance team and security"),
        ("bedsheet dirty and smells", "cleanliness", "housekeeping"),
        ("too much noise from next door", "noise_complaint", "the front desk"),
    ],
)
def test_rules_reply_is_empathetic_and_names_the_team(client, owner, text, typ, check):
    c = _ctx(client, owner)
    out = concierge.rules(text, concierge.detect_lang(text), c)
    assert out["proposed_action"]["params"]["type"] == typ, out
    assert check in out["reply"], out["reply"]
    assert "minute" in out["reply"] or "मिनट" in out["reply"]
    assert "Room service" not in out["reply"] and "07:00-23:00" not in out["reply"]


def test_room_alone_never_triggers_room_service(client, owner):
    c = _ctx(client, owner)
    for text in ("room", "kamra", "कमरा", "room please"):
        out = concierge.rules(text, concierge.detect_lang(text), c)
        assert out["proposed_action"] is None and "Room service" not in out["reply"], (text, out)


def test_urgent_reply_numbers_and_single_button(client, owner):
    c = _ctx(client, owner)
    out = concierge.rules("I feel unwell, need a doctor", "en", c)
    pa = out["proposed_action"]
    assert pa["urgent"] and pa["label"] == "Alert front desk now" and {n["tel"] for n in pa["emergency"]} == {"108", "112"}
    assert "108" in out["reply"] and "duty manager" in out["reply"]
    assert not any(w in out["reply"].lower() for w in ("take ", "tablet", "paracetamol"))  # never medical advice
    s = concierge.rules("smoke smell in corridor", "en", c)
    assert s["proposed_action"]["urgent"] and "112" in s["reply"] and "right now" in s["reply"]


def test_room_change_offered_only_when_the_profile_allows(client, owner):
    c = _ctx(client, owner)
    assert "another room" not in concierge.rules("rat in my room", "en", c)["reply"]
    c["profile"] = {**c["profile"], "faq": [*c["profile"]["faq"], {"q": "Can I change my room?", "a": "If another room is free, yes."}]}
    assert "another room is free" in concierge.rules("rat in my room", "en", c)["reply"]


def test_llm_other_is_reclassified_and_team_mismatch_fixed(client, owner):
    tok = room(client, owner)["guest_token"]
    # the live failure: reply says maintenance, action "other" -> server re-classifies with the rules
    ai.use(
        chat=FakeChat(
            {
                "reply": "Sorry! I'll ask maintenance to check the leak. Tap Confirm.",
                "lang": "en",
                "action": {"type": "request", "request_type": "other", "note": "water leaking from ceiling"},
            }
        )
    )
    out = client.post(f"/public/guest/{tok}/chat", json={"message": "water leaking from ceiling"}).json()
    assert out["source"] == "llm" and out["proposed_action"]["params"]["type"] == "water_leak"
    assert "maintenance" in out["reply"]
    # team mismatch: reply names maintenance, action is towels (housekeeping) -> reply regenerated for housekeeping
    ai.use(
        chat=FakeChat(
            {
                "reply": "I'll send maintenance with towels. Tap Confirm.",
                "lang": "en",
                "action": {"type": "request", "request_type": "towels"},
            }
        )
    )
    out = client.post(f"/public/guest/{tok}/chat", json={"message": "towels please"}).json()
    assert out["proposed_action"]["params"]["type"] == "towels" and "housekeeping" in out["reply"] and "maintenance" not in out["reply"]
    # no action for a described problem -> the problem's action is added
    ai.use(chat=FakeChat({"reply": "Extra linen may be charged.", "lang": "en", "action": None}))
    out = client.post(f"/public/guest/{tok}/chat", json={"message": "bedsheet dirty and smells"}).json()
    assert out["proposed_action"]["params"]["type"] == "cleanliness"
    # urgent wins over whatever the model chose
    ai.use(chat=FakeChat({"reply": "I don't have that information.", "lang": "en", "action": None}))
    out = client.post(f"/public/guest/{tok}/chat", json={"message": "smoke smell in corridor"}).json()
    assert out["proposed_action"]["params"]["type"] == "safety_alert" and out["proposed_action"]["urgent"]
    # the prompt lists the taxonomy ids and their teams
    fake = FakeChat({"reply": "Of course.", "lang": "en", "action": None})
    ai.use(chat=fake)
    client.post(f"/public/guest/{tok}/chat", json={"message": "hello"})
    system = fake.calls[0][0]
    assert "pest_control (" in system and "safety_alert (" in system and "front desk + security" in system


def test_urgent_safety_flow_creates_urgent_jobs_for_front_office_and_security(client, owner):
    client.put(
        "/dispatch/context",
        json={"working": {"HS09": "front_office", "HS19": "security", "HS05": "housekeeping"}, "bands": {}},
        headers=owner,
    )
    tok = room(client, owner)["guest_token"]
    for _ in range(6):  # urgent alerts are never rate-limited by the per-room request limit
        client.post(f"/public/guest/{tok}/requests", json={"key": "towels"})
    r = client.post(f"/public/guest/{tok}/actions", json={"action": "request", "params": {"type": "safety_alert", "note": "smoke"}})
    assert r.status_code == 200, r.text
    jobs = [j for j in mongo.col("jobs").find({"title": {"$regex": "^Safety concern"}}) if j.get("room_id")]
    depts = {j["department"]: j for j in jobs[-2:]}
    assert set(depts) == {"front_office", "security"}
    assert all(j["urgency"] == "urgent" and j["offer_seconds"] == 15 and j["target_minutes"] == 5 for j in depts.values())
    assert depts["security"]["offer_to"] == "HS19" and depts["front_office"]["offer_to"] == "HS09"
    alerts = client.get("/guest-services/summary", headers=owner).json()["urgent_alerts"]
    assert any(a["title"].startswith("Safety concern") for a in alerts)
    m = client.post(f"/public/guest/{tok}/actions", json={"action": "request", "params": {"type": "medical_help", "note": "unwell"}})
    assert m.status_code == 200
    assert mongo.col("audit_log").find_one({"action": "guest.urgent_alert", "detail": {"$regex": "^medical_help"}})


def test_guest_menu_groups_problems():
    from hoi_platform.services import rooms

    keys = list(rooms.GUEST_MENU)
    assert keys[-1] == "other" and {"pest_control", "water_leak", "safety_alert", "medical_help", "noise_complaint"} <= set(keys)
    assert rooms.GUEST_MENU["safety_alert"]["group"] == "problem" and rooms.GUEST_MENU["towels"]["group"] == "request"


def test_worker_voice_report_uses_the_taxonomy(client):
    tid = "org_demo"
    p = voice.parse_issue("report room 204 rat in the bathroom")
    assert p["department"] == "housekeeping" and p["urgency"] == "high" and p["issue_type"] == "pest_control"
    p = voice.parse_issue("room 105 dhuan aa raha hai")
    assert p["department"] == "front_office" and p["urgency"] == "urgent"
    out = voice.command(tid, "HS05", "room 204 mein chuha hai", "hi")
    assert out["intent"] == "report_issue" and out["proposed_action"]["params"]["issue_type"] == "pest_control"
    assert auth(client, "HS05")
