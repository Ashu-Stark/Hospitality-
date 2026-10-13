"""Onboarding Part C: number normaliser, rule-based and LLM extractors, merge, validators.

All text is SYNTHETIC (written for the tests). The LLM is always a fake adapter: no network.
"""

import io
import json
import urllib.error

import pytest

from backend.onboarding.config import load_config
from backend.onboarding.extract import ExtractionResult, Guess, extract_rules
from backend.onboarding.llm import MISMATCH_NOTE, GroqChat, extract
from backend.onboarding.merge import PLEASE_CONFIRM, edit_field, merge, validate
from backend.onboarding.numbers import load_table, normalise, numbers_in, parse_number
from backend.onboarding.schema import HotelProfile
from backend.onboarding.templates import apply_template

CFG = load_config()

NUMBER_CASES = [
    ("12", 12), ("१२", 12), ("barah", 12), ("baarah", 12), ("twelve", 12), ("बारह", 12),
    ("bees", 20), ("bis", 20), ("बीस", 20), ("paintalis", 45), ("paitalis", 45),
    ("पैंतालीस", 45), ("pachaas", 50), ("pachas", 50), ("पचास", 50), ("sau", 100),
    ("सौ", 100), ("ek sau bees", 120), ("do sau", 200), ("one hundred and five", 105),
    ("twenty-one", 21), ("twenty one", 21), ("forty five", 45), ("ninety nine", 99),
    ("ninyanve", 99), ("निन्यानवे", 99), ("char", 4), ("chaar", 4), ("चार", 4),
    ("paanch", 5), ("पाँच", 5), ("पांच", 5), ("chhah", 6), ("छह", 6), ("das", 10),
    ("dus", 10), ("assi", 80), ("अस्सी", 80), ("zero", 0), ("shunya", 0), ("dedh", 1.5),
    ("डेढ़", 1.5), ("dhai", 2.5), ("5 hazaar", 5000), ("do lakh pachaas hazaar", 250000),
    ("a dozen", 12), ("1.5", 1.5), ("०", 0),
]


@pytest.mark.parametrize(("text", "value"), NUMBER_CASES)
def test_number_normaliser_table(text: str, value: float) -> None:
    assert parse_number(text) == value


def test_number_normaliser_rewrites_text_and_keeps_context() -> None:
    assert len(NUMBER_CASES) >= 30
    assert normalise("hamare paas barah kamre hain").text == "hamare paas 12 kamre hain"
    assert normalise("double rate").text == "2 guna rate"
    assert normalise("dedh guna").numbers == (1.5,)
    assert normalise("12 15").numbers == (12, 15)
    assert normalise("100, 20 staff").numbers == (100, 20)    # punctuation splits numbers
    assert normalise("what do you mean").numbers == ()        # English "do" is not 2
    assert normalise("hum ke saath kaam karte").numbers == ()  # "ke saath" = "with", not 60
    assert numbers_in("subah 7:30 se 3 baje") >= {7, 30, 3}
    table = load_table()
    assert table.review["needs_hm_review"] is True
    for words in (table.hindi_roman, table.hindi_devanagari):
        assert set(range(0, 101)) <= set(words)  # every number 0-100 in both scripts


RULE_CASES = [
    ("hamare paas barah kamre hain, Mussoorie mein homestay hai", None,
     {"rooms": 12, "location": "Mussoorie", "hotel_type": "homestay"}),
    ("12", "rooms", {"rooms": 12}),
    ("हमारे होटल में पैंतालीस कमरे हैं, ऋषिकेश में", None, {"rooms": 45, "location": "Rishikesh"}),
    ("35 rooms ka guest house hai Dehradun mein", None,
     {"rooms": 35, "hotel_type": "small_hotel", "location": "Dehradun"}),
    ("hamara hotel Bhowali ke paas hai", "location", {"location": "Bhowali"}),
    ("housekeeping mein char log, kitchen mein do, front desk pe ek", "departments",
     {"departments": {"housekeeping": 4, "kitchen": 2, "front_office": 1}}),
    ("we have 4 housekeeping, 2 cooks and 1 receptionist", "departments",
     {"departments": {"housekeeping": 4, "kitchen": 2, "front_office": 1}}),
    ("हाउसकीपिंग में छह लोग, किचन में चार", "departments",
     {"departments": {"housekeeping": 6, "kitchen": 4}}),
    ("may se june aur december", "peak_months", {"peak_months": [5, 6, 12]}),
    ("peak season is October to November", None, {"peak_months": [10, 11]}),
    ("मई से जून", "peak_months", {"peak_months": [5, 6]}),
    ("subah 7 se 3, shaam 3 se 11", "shifts",
     {"shifts": [{"name": "morning", "start": "07:00", "end": "15:00"},
                 {"name": "evening", "start": "15:00", "end": "23:00"}]}),
    ("morning 6am to 2pm and night 10pm-6am", None,
     {"shifts": [{"name": "morning", "start": "06:00", "end": "14:00"},
                 {"name": "night", "start": "22:00", "end": "06:00"}]}),
    ("double", "overtime_rate_multiplier", {"overtime_rate_multiplier": 2}),
    ("dedh guna milta hai", "overtime_rate_multiplier", {"overtime_rate_multiplier": 1.5}),
    ("kam se kam das ghante aaram", "min_rest_hours", {"min_rest_hours": 10}),
    ("48 hours a week, hafte mein ek din chhutti, lagatar 6 din se zyada nahi", None,
     {"standard_weekly_hours": 48, "weekly_off_days": 1, "max_consecutive_days": 6}),
    ("incentive budget 5 hazaar rupaye", None, {"incentive_monthly_budget_cap": 5000}),
    ("hotel ka naam Pine View hai", None, {"hotel_name": "Pine View"}),
]


@pytest.mark.parametrize(("text", "current", "expected"), RULE_CASES)
def test_rule_based_extractor(text: str, current: str | None, expected: dict) -> None:
    out = extract_rules(text, current)
    assert out.method == "rules"
    assert {k: v.value for k, v in out.fields.items()} == expected


def test_rule_based_extractor_confidence_and_no_false_months() -> None:
    assert extract_rules("12 rooms").fields["rooms"].confidence == CFG.confidence.rules_pattern
    assert extract_rules("12", "rooms").fields["rooms"].confidence == CFG.confidence.rules_context
    # "may" as a verb is not a month unless the question is about peak months
    assert "peak_months" not in extract_rules("it may be 12 rooms").fields
    assert extract_rules("skip", "rooms").fields == {}


class FakeLLM:
    name = "fake"

    def __init__(self, reply: str | Exception, ok: bool = True) -> None:
        self.reply, self.ok, self.calls = reply, ok, []

    def available(self) -> tuple[bool, str]:
        return self.ok, "ok" if self.ok else "no key"

    def complete_json(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_llm_valid_json_is_used_and_cross_checked() -> None:
    fake = FakeLLM(json.dumps({"rooms": 12, "location": "Mussoorie",
                               "departments": {"housekeeping": 4}}))
    out = extract("barah kamre, Mussoorie, housekeeping mein char", "rooms", fake, CFG)
    assert out.method == "llm" and out.mismatches == []
    assert out.fields["rooms"].confidence == CFG.confidence.llm_checked
    assert out.fields["location"].confidence == CFG.confidence.llm_unchecked
    system, user = fake.calls[0]
    assert "json schema" in system.lower() and "housekeeping" in system and "rooms" in user


def test_llm_mismatched_number_is_flagged_please_confirm() -> None:
    fake = FakeLLM(json.dumps({"rooms": 21, "departments": {"kitchen": 3}}))
    out = extract("barah kamre, kitchen mein do", "rooms", fake, CFG)
    assert set(out.mismatches) == {"rooms", "departments"}
    assert out.fields["rooms"].confidence == CFG.confidence.mismatch == 0.3
    assert out.fields["rooms"].note == MISMATCH_NOTE
    profile, filled, _ = merge(apply_template(HotelProfile(), "homestay"), out, "voice", CFG)
    assert not profile.rooms.confirmed and profile.rooms.value == 21  # never silently accepted


@pytest.mark.parametrize("reply", ["not json at all", '{"rooms": "many"}',
                                   '{"departments": {"spa": 2}}', '{"peak_months": [13]}',
                                   '{"salary": 5000}'])
def test_llm_invalid_json_is_rejected_and_rules_take_over(reply: str) -> None:
    out = extract("barah kamre", "rooms", FakeLLM(reply), CFG)
    assert out.method == "rules" and "rejected" in out.fallback_reason
    assert out.fields["rooms"].value == 12


def test_llm_failure_or_no_key_falls_back_to_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    down = extract("barah kamre", "rooms", FakeLLM(urllib.error.URLError("down")), CFG)
    assert down.method == "rules" and "failed" in down.fallback_reason
    nokey = extract("barah kamre", "rooms", FakeLLM("{}", ok=False), CFG)
    assert nokey.method == "rules" and "unavailable" in nokey.fallback_reason
    assert extract("barah kamre", "rooms", None, CFG).fields["rooms"].value == 12
    monkeypatch.delenv(CFG.llm.api_key_env, raising=False)
    assert GroqChat(CFG.llm).available()[0] is False


def test_groq_adapter_request_shape_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def fake_urlopen(req, timeout):  # noqa: ANN001, ANN202
        seen["body"], seen["timeout"] = json.loads(req.data), timeout
        seen["auth"] = req.headers["Authorization"]
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode())

    monkeypatch.setenv(CFG.llm.api_key_env, "test-not-a-real-key")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert GroqChat(CFG.llm).complete_json("s", "u") == "{}"
    assert seen["body"]["temperature"] == 0 and seen["body"]["model"] == CFG.llm.model
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["timeout"] == CFG.llm.timeout_seconds and seen["auth"].startswith("Bearer ")


def _answer(**fields: object) -> ExtractionResult:
    return ExtractionResult(method="rules", fields={k: Guess(value=v, confidence=0.8)
                                                    for k, v in fields.items()})


def test_merge_answers_overwrite_templates_and_edits_always_win() -> None:
    p = apply_template(HotelProfile(), "homestay")
    p, filled, _ = merge(p, _answer(rooms=12, min_rest_hours=11), "typed", CFG)
    assert filled == ["rooms", "min_rest_hours"]
    assert p.rooms.source == "typed" and p.rooms.confirmed
    assert p.min_rest_hours.needs_verification and not p.min_rest_hours.confirmed  # legal
    p = edit_field(p, "rooms", 14, CFG)
    p, filled, issues = merge(p, _answer(rooms=20), "voice", CFG)
    assert p.rooms.value == 14 and p.rooms.method == "edit" and "rooms" not in filled
    assert "kept your edit" in issues.warnings["rooms"][0]
    low = ExtractionResult(method="rules", fields={"location": Guess(value="X", confidence=0.4)})
    p, _, _ = merge(p, low, "voice", CFG)
    assert p.location.value == "X" and not p.location.confirmed
    assert p.location.note == PLEASE_CONFIRM


def test_merge_departments_keep_unmentioned_template_departments_with_a_warning() -> None:
    p = apply_template(HotelProfile(), "homestay")
    p, _, issues = merge(p, _answer(departments={"housekeeping": 4}), "typed", CFG)
    assert p.departments.value["housekeeping"] == 4 and "kitchen" in p.departments.value
    assert "kept from the template" in issues.warnings["departments"][0]


def test_validators() -> None:
    p = apply_template(HotelProfile(), "homestay")
    assert validate(p, CFG).errors == {}
    bad = (p.with_field("rooms", {"value": 900})
           .with_field("peak_months", {"value": [5, 13]})
           .with_field("shifts", {"value": [{"name": "x", "start": "06:00", "end": "08:00"}]})
           .with_field("overtime_rate_multiplier", {"value": 5.0})
           .with_field("departments", {"value": {"housekeeping": 300, "spa": 1}}))
    issues = validate(bad, CFG)
    assert {"rooms", "peak_months", "shifts", "overtime_rate_multiplier",
            "departments"} <= set(issues.errors)
    assert any("spa" in m for m in issues.errors["departments"])
    lopsided = p.with_field("rooms", {"value": 12}).with_field(
        "departments", {"value": {"housekeeping": 60}})
    v = validate(lopsided, CFG)
    assert "per room" in v.warnings["departments"][0]          # ratio warns, never blocks
    assert "departments" not in v.errors
    wrong_type = p.with_field("rooms", {"value": 40})
    assert "small_hotel" in validate(wrong_type, CFG).warnings["hotel_type"][0]
