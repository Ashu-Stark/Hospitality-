"""Onboarding Part B: deterministic question flow, bilingual questions, session storage."""

import random
import re

import mongomock
import pytest

from backend.db import ONBOARDING_SESSIONS, ensure_indexes
from backend.onboarding.config import load_config
from backend.onboarding.flow import (
    FlowState,
    advance,
    is_skip,
    load_questions,
    next_field,
    record_answer,
    render,
)
from backend.onboarding.schema import HotelProfile
from backend.onboarding.store import (
    NotFound,
    create_session,
    draft_of,
    flow_of,
    get_session,
    save_session,
)

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
SEED = 7


def test_every_question_exists_in_english_and_hindi_with_an_example() -> None:
    cfg, qs = load_config(), load_questions()
    assert qs.review["needs_hm_review"] is True
    for f in cfg.required_order:
        q = qs.questions[f]
        assert q.en and q.example_en and not DEVANAGARI.search(q.en)
        assert DEVANAGARI.search(q.hi) and DEVANAGARI.search(q.example_hi)
    for key in qs.messages:
        assert set(qs.messages[key]) == {"en", "hi"}
    hi = render("rooms", "hi", FlowState(asked=["rooms"]), cfg)
    assert hi.language == "hi" and DEVANAGARI.search(hi.text) and hi.needs_hm_review
    assert render("rooms", "fr", FlowState(asked=["rooms"]), cfg).language == "en"


def test_flow_asks_in_order_and_never_re_asks_an_answered_field() -> None:
    cfg = load_config()
    s = advance(FlowState(), cfg)
    assert s.current == "rooms" and s.asked == ["rooms"]
    # one answer fills rooms AND location ("12 rooms in Mussoorie"): location is skipped over
    s = advance(record_answer(s, ["rooms", "location"], skipped=False), cfg)
    assert s.current == "departments"
    s = advance(record_answer(s, [], skipped=True), cfg)  # "skip" keeps the template value
    assert s.current == "peak_months" and "departments" in s.skipped
    assert s.asked == ["rooms", "departments", "peak_months"]


def test_unanswered_field_is_asked_at_most_twice_and_flow_always_ends() -> None:
    cfg = load_config()
    s = advance(FlowState(), cfg)
    while s.current is not None:
        s = advance(record_answer(s, [], skipped=False), cfg)  # never a usable answer
    assert len(s.asked) == cfg.max_questions
    assert max(s.asked.count(f) for f in s.asked) <= cfg.max_asks_per_field
    assert next_field(s, cfg) is None


def test_random_answer_sequences_respect_the_invariants() -> None:
    cfg = load_config()
    rng = random.Random(SEED)
    for _ in range(300):
        s = advance(FlowState(), cfg)
        while s.current is not None:
            filled = rng.sample(cfg.required_order, rng.randint(0, 2))
            if rng.random() < 0.5:
                filled.append(s.current)
            answered_before = set(s.answered)
            s = advance(record_answer(s, filled, skipped=rng.random() < 0.1), cfg)
            assert s.current not in answered_before  # a filled field is never asked again
        assert len(s.asked) <= cfg.max_questions


def test_skip_words() -> None:
    qs = load_questions()
    assert is_skip("Skip", qs) and is_skip("पता नहीं", qs) and is_skip(" aage. ", qs)
    assert not is_skip("12 rooms", qs)


def test_session_is_stored_and_filtered_by_session_and_property() -> None:
    db = mongomock.MongoClient(tz_aware=True)["onb_b"]
    ensure_indexes(db)
    a = create_session(db, "hi", HotelProfile(), FlowState(), "test", False)
    b = create_session(db, "en", HotelProfile(), FlowState(), "test", False)
    assert a["property_id"] != b["property_id"] and a["session_id"] != b["session_id"]
    assert {"id", "created_at", "source", "property_id"} <= set(get_session(db, a["session_id"]))
    flow = advance(flow_of(a), load_config())
    saved = save_session(db, a, flow=flow.model_dump(), status="in_progress")
    assert flow_of(saved).current == "rooms" and draft_of(saved) == HotelProfile()
    assert flow_of(get_session(db, b["session_id"])).current is None  # b untouched
    with pytest.raises(NotFound):
        get_session(db, "nope")
    with pytest.raises(NotFound):
        save_session(db, {**a, "property_id": b["property_id"]}, status="x")  # wrong property
    assert db[ONBOARDING_SESSIONS].count_documents({}) == 2
