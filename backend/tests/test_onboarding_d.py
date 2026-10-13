"""Onboarding Part D: endpoints (httpx TestClient), storage, confirm rules, isolation, audio.

mongomock only; the LLM and speech-to-text are fakes; all text is SYNTHETIC.
"""

import json
from pathlib import Path

import pytest

from backend.db import AUDIT, ONBOARDING_COLLECTIONS, PROPERTIES, PROPERTY_SETTINGS
from backend.onboarding.schema import LEGAL_FIELDS

TYPED_ANSWERS = {
    "rooms": "We have 12 rooms",
    "location": "Mussoorie",
    "departments": "housekeeping 3, kitchen 2, front desk 2",
    "peak_months": "May to June and December",
    "shifts": "morning 7 to 3, evening 3 to 11",
    "overtime_rate_multiplier": "double",
    "min_rest_hours": "10 hours",
}


def start(client, **body) -> dict:  # noqa: ANN001
    r = client.post("/onboarding/start", json={"language": "en", **body})
    assert r.status_code == 200, r.text
    return r.json()


def run_typed_flow(client, answers: dict = TYPED_ANSWERS, **start_body) -> dict:  # noqa: ANN001
    s = start(client, **start_body)
    sid, out = s["session_id"], s
    for _ in range(10):
        q = out["question"]
        if q is None:
            break
        r = client.post("/onboarding/answer", json={"session_id": sid, "text": answers[q["field"]]})
        assert r.status_code == 200, r.text
        out = r.json()
    return out


def configure(client, **sections) -> None:  # noqa: ANN001
    """Override onboarding.yaml sections for this app only (e.g. audio flags)."""
    cfg = client.app.state.onboarding_cfg
    update = {k: getattr(cfg, k).model_copy(update=v) for k, v in sections.items()}
    client.app.state.onboarding_cfg = cfg.model_copy(update=update)


def test_full_typed_flow_with_no_keys_and_no_audio(client, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    s = start(client)
    assert s["question"]["field"] == "rooms" and "Confirm" in s["banner"]
    out = run_typed_flow(client)
    assert out["status"] == "ready_for_summary" and out["question"] is None
    assert out["extractor"] == "rules" and out["fallback_reason"]
    f = out["fields"]
    assert f["rooms"]["value"] == 12 and f["rooms"]["source"] == "typed"
    assert f["location"]["value"] == "Mussoorie"
    assert f["hotel_type"]["value"] == "homestay"            # from the 12-room size band
    assert f["departments"]["value"] == {"housekeeping": 3, "kitchen": 2, "front_office": 2}
    assert f["peak_months"]["value"] == [5, 6, 12]
    assert f["shifts"]["value"][1] == {"name": "evening", "start": "15:00", "end": "23:00"}
    assert f["overtime_rate_multiplier"]["value"] == 2 and f["min_rest_hours"]["value"] == 10
    assert f["standard_weekly_hours"]["source"] == "template"  # shown, not asked
    assert out["ready_to_confirm"] and out["answers"] == 7


def test_nothing_is_saved_before_confirm_and_legal_fields_need_acknowledgement(client) -> None:  # noqa: ANN001
    db = client.app.state.db
    before = db[PROPERTIES].count_documents({})
    out = run_typed_flow(client)
    sid, pid = out["session_id"], out["property_id"]
    assert db[PROPERTIES].count_documents({}) == before
    r = client.post("/onboarding/confirm", json={"session": sid,
                                                 "acknowledged_legal_fields": ["min_rest_hours"]})
    assert r.status_code == 422
    assert set(r.json()["detail"]["unacknowledged_legal_fields"]) == {
        "overtime_rate_multiplier", "weekly_off_days"}
    assert db[PROPERTIES].count_documents({}) == before
    assert db[PROPERTY_SETTINGS].find_one({"property_id": pid}) is None
    ok = client.post("/onboarding/confirm", json={"session": sid,
                                                  "acknowledged_legal_fields": list(LEGAL_FIELDS)})
    assert ok.status_code == 200 and ok.json() == {
        "property_id": pid, "created": True, "status": "confirmed",
        "acknowledged_legal_fields": sorted(LEGAL_FIELDS)}
    settings = client.get(f"/properties/{pid}/settings").json()
    assert settings["profile"]["min_rest_hours"]["needs_verification"] is True
    assert settings["profile"]["min_rest_hours"]["confirmed"] is True


def test_confirm_is_idempotent_and_writes_audit_rows(client) -> None:  # noqa: ANN001
    db = client.app.state.db
    out = run_typed_flow(client)
    body = {"session": out["session_id"], "acknowledged_legal_fields": list(LEGAL_FIELDS)}
    first = client.post("/onboarding/confirm", json=body).json()
    second = client.post("/onboarding/confirm", json=body).json()
    assert first["created"] is True and second["created"] is False
    assert first["property_id"] == second["property_id"]
    pid = first["property_id"]
    assert db[PROPERTIES].count_documents({"property_id": pid}) == 1
    assert db[PROPERTY_SETTINGS].count_documents({"property_id": pid}) == 1
    actions = [a["action"] for a in db[AUDIT].find({"detail.property_id": pid})]
    for a in ("onboarding.start", "onboarding.answer", "property.create",
              "property_settings.create", "onboarding.confirm"):
        assert a in actions, a
    assert actions.count("property.create") == 1 and actions.count("onboarding.confirm") == 2
    late = client.post("/onboarding/answer", json={"session_id": out["session_id"], "text": "5"})
    assert late.status_code == 409  # a confirmed session cannot change


def test_property_isolation(client) -> None:  # noqa: ANN001
    ids = []
    for name, rooms in (("Synthetic A", "40 rooms"), ("Synthetic B", "80 rooms")):
        out = run_typed_flow(client, {**TYPED_ANSWERS, "rooms": rooms}, hotel_name=name)
        client.post("/onboarding/confirm", json={"session": out["session_id"],
                                                 "acknowledged_legal_fields": list(LEGAL_FIELDS)})
        ids.append(out["property_id"])
    a, b = ids
    sa = client.get(f"/properties/{a}/settings").json()
    sb = client.get(f"/properties/{b}/settings").json()
    assert sa["property_id"] == a and sa["profile"]["hotel_name"]["value"] == "Synthetic A"
    assert sb["profile"]["rooms"]["value"] == 80
    assert "Synthetic B" not in json.dumps(sa) and "Synthetic A" not in json.dumps(sb)
    assert client.get(f"/properties/{a}").json()["rooms"] == 40
    assert client.get("/properties/prop_9999/settings").status_code == 404
    # the three SYNTHETIC demo properties exist (startup seed) and are isolated too
    demo = list(client.app.state.db[PROPERTIES].find({"demo": True}, {"_id": 0}))
    assert sorted(d["rooms"] for d in demo) == [12, 35, 80]
    seen = {client.get(f"/properties/{d['property_id']}/settings").json()["property_id"]
            for d in demo}
    assert seen == {d["property_id"] for d in demo} and not seen & set(ids)


def test_field_edits_win_and_bad_edits_are_rejected(client) -> None:  # noqa: ANN001
    sid = start(client)["session_id"]
    r = client.patch("/onboarding/field", json={"session_id": sid, "field": "rooms", "value": 30})
    assert r.status_code == 200
    s = r.json()
    assert s["fields"]["rooms"]["method"] == "edit" and s["fields"]["rooms"]["confidence"] == 1
    assert s["fields"]["hotel_type"]["value"] == "small_hotel"   # re-templated by size band
    assert s["question"]["field"] == "location"                  # rooms is never asked again
    a = client.post("/onboarding/answer", json={"session_id": sid, "text": "45 rooms"}).json()
    assert a["fields"]["rooms"]["value"] == 30 and "kept your edit" in a["warnings"]["rooms"][0]
    assert client.patch("/onboarding/field", json={"session_id": sid, "field": "rooms",
                                                   "value": "lots"}).status_code == 422
    assert client.patch("/onboarding/field", json={"session_id": sid, "field": "salary",
                                                   "value": 1}).status_code == 422
    assert client.get("/onboarding/summary", params={"session": "nope"}).status_code == 404


class FakeLLM:
    name = "fake"

    def __init__(self, replies: dict) -> None:
        self.replies = replies

    def available(self) -> tuple[bool, str]:
        return True, "ok"

    def complete_json(self, system: str, user: str) -> str:
        field = user.split("(field ")[1].split(")")[0]
        return json.dumps(self.replies.get(field, {}))


class FakeSTT:
    name = "fake_stt"

    def __init__(self, transcripts: list[str]) -> None:
        self.transcripts, self.paths = list(transcripts), []

    def available(self) -> tuple[bool, str]:
        return True, "ok"

    def transcribe(self, path: Path) -> str:
        assert path.exists()
        self.paths.append(path)
        return self.transcripts.pop(0)


def test_low_confidence_llm_answer_blocks_confirm_until_the_owner_checks_it(client) -> None:  # noqa: ANN001
    configure(client, llm={"allow_cloud_llm_for_owner_text": True})
    client.app.state.onboarding_llm = FakeLLM({"rooms": {"rooms": 21}})   # said 12, LLM says 21
    sid = start(client)["session_id"]
    a = client.post("/onboarding/answer", json={"session_id": sid, "text": "barah kamre",
                                                "consent": True}).json()
    assert a["extractor"] == "llm" and a["mismatches"] == ["rooms"]
    assert a["fields"]["rooms"]["confidence"] == 0.3 and not a["fields"]["rooms"]["confirmed"]
    assert a["needs_confirmation"] == ["rooms"]
    # without consent the LLM is never called: rules only
    sid2 = start(client)["session_id"]
    b = client.post("/onboarding/answer", json={"session_id": sid2, "text": "barah kamre"}).json()
    assert b["extractor"] == "rules" and b["fields"]["rooms"]["value"] == 12
    for f, text in TYPED_ANSWERS.items():
        if f != "rooms":
            client.post("/onboarding/answer", json={"session_id": sid, "text": text})
    body = {"session": sid, "acknowledged_legal_fields": list(LEGAL_FIELDS)}
    blocked = client.post("/onboarding/confirm", json=body)
    assert blocked.status_code == 422 and blocked.json()["detail"]["needs_confirmation"] == [
        "rooms"]
    client.patch("/onboarding/field", json={"session_id": sid, "field": "rooms", "value": 12})
    assert client.post("/onboarding/confirm", json=body).json()["created"] is True


def test_audio_needs_the_config_flag_and_consent(client) -> None:  # noqa: ANN001
    sid = start(client)["session_id"]
    wav = ("a.wav", b"RIFF-synthetic-bytes", "audio/wav")
    off = client.post("/onboarding/answer", data={"session_id": sid, "consent": "true"},
                      files={"file": wav}).json()
    assert off["stt_error"] and off["input_fallback"] == "text"
    assert off["question"]["field"] == "rooms" and off["answers"] == 0
    configure(client, audio={"allow_cloud_stt_for_owner_audio": True})
    client.app.state.onboarding_stt = FakeSTT(["barah kamre"])
    no_consent = client.post("/onboarding/answer", data={"session_id": sid},
                             files={"file": wav}).json()
    assert "consent" in no_consent["stt_error"].lower()
    bad = client.post("/onboarding/answer", data={"session_id": sid, "consent": "true"},
                      files={"file": ("a.exe", b"MZ", "application/x-msdownload")})
    assert bad.status_code == 422
    configure(client, audio={"max_megabytes": 0.000001})
    big = client.post("/onboarding/answer", data={"session_id": sid, "consent": "true"},
                      files={"file": wav})
    assert big.status_code == 422 and "larger" in big.json()["detail"]


def test_full_flow_with_fake_stt_and_fake_llm(client) -> None:  # noqa: ANN001
    configure(client, audio={"allow_cloud_stt_for_owner_audio": True},
              llm={"allow_cloud_llm_for_owner_text": True})
    stt = FakeSTT(list(TYPED_ANSWERS.values()))
    client.app.state.onboarding_stt = stt
    client.app.state.onboarding_llm = FakeLLM({
        "rooms": {"rooms": 12}, "location": {"location": "Mussoorie"},
        "departments": {"departments": {"housekeeping": 3, "kitchen": 2, "front_office": 2}},
        "peak_months": {"peak_months": [5, 6, 12]},
        "shifts": {"shifts": [{"name": "morning", "start": "07:00", "end": "15:00"},
                              {"name": "evening", "start": "15:00", "end": "23:00"}]},
        "overtime_rate_multiplier": {"overtime_rate_multiplier": 2},
        "min_rest_hours": {"min_rest_hours": 10}})
    out = start(client, language="hi")
    assert out["question"]["language"] == "hi"
    sid = out["session_id"]
    while out["question"] is not None:
        r = client.post("/onboarding/answer", data={"session_id": sid, "consent": "true"},
                        files={"file": ("answer.webm", b"synthetic", "audio/webm")})
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["input"] == "voice" and out["extractor"] == "llm" and not out["mismatches"]
    assert out["fields"]["rooms"]["source"] == "voice"
    assert out["fields"]["rooms"]["confidence"] == 0.9
    assert all(not p.exists() for p in stt.paths) and len(stt.paths) == 7  # audio not kept
    r = client.post("/onboarding/confirm", json={"session": sid,
                                                 "acknowledged_legal_fields": list(LEGAL_FIELDS)})
    assert r.json()["created"] is True


def test_onboarding_documents_and_indexes(client) -> None:  # noqa: ANN001
    run_typed_flow(client)
    db = client.app.state.db
    for name in ONBOARDING_COLLECTIONS:
        docs = list(db[name].find({}, {"_id": 0}))
        assert docs and all({"id", "created_at", "source", "property_id"} <= set(d)
                            for d in docs), name
    unique = {tuple(k for k, _ in i["key"]) for i in db[PROPERTIES].index_information().values()
              if i.get("unique")}
    assert {("property_id",), ("onboarding_session_id",)} <= unique


def test_demo_reset_recreates_the_three_demo_properties(client) -> None:  # noqa: ANN001
    run_typed_flow(client)
    r = client.post("/demo/reset").json()
    assert r["demo_property_ids"] == ["prop_0001", "prop_0002", "prop_0003"]
    db = client.app.state.db
    assert db[PROPERTIES].count_documents({}) == 3
    rooms = [client.get(f"/properties/{p}").json()["rooms"] for p in r["demo_property_ids"]]
    assert rooms == [12, 35, 80]


@pytest.mark.parametrize("mode", ["mock"])
def test_onboarding_works_in_mock_mode(mock_client, mode: str) -> None:  # noqa: ANN001
    out = run_typed_flow(mock_client)
    assert out["status"] == "ready_for_summary"
    db = mock_client.app.state.db
    assert db["onboarding_session"].find_one({"session_id": out["session_id"]})["source"] == (
        "api:mock")
