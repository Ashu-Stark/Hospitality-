"""Groq key failover with fake transports: rotate only on 401/403/5xx/connection errors, never on 429. Offline."""

import io
import json
import logging
import urllib.error
import urllib.request

import pytest

from hoi_platform import config, ratelimit
from hoi_platform.services import ai, concierge

PRIMARY, B1, B2 = "gsk_primary_secret_aaaa", "gsk_backup_one_bbbb", "gsk_backup_two_cccc"
OK = {"choices": [{"message": {"content": '{"reply": "Hi there.", "lang": "en", "action": null}'}}]}


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code, retry_after=None):
    headers = {"retry-after": str(retry_after)} if retry_after is not None else {}
    return urllib.error.HTTPError("https://api.example/x", code, "err", headers, io.BytesIO(b"{}"))


@pytest.fixture
def transport(monkeypatch):
    """plan: key -> list of outcomes (int status, Exception, or 'ok'); records the key of every call."""
    calls, plan = [], {}

    def fake(req, timeout=0):
        key = req.get_header("Authorization").split(" ", 1)[1]
        calls.append(key)
        step = plan[key].pop(0) if len(plan[key]) > 1 else plan[key][0]
        if step == "ok":
            return Resp(json.dumps(OK).encode())
        if isinstance(step, Exception):
            raise step
        raise http_error(*step) if isinstance(step, tuple) else http_error(step)

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    monkeypatch.setattr(ai.time, "sleep", lambda s: None)
    for k in ("LLM_API_KEY", "LLM_API_KEYS_BACKUP", "STT_API_KEY", "STT_API_KEYS_BACKUP"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", PRIMARY)
    monkeypatch.setenv("GROQ_API_KEYS_BACKUP", f" {B1}, {B2} ,{PRIMARY}")
    ai._UNHEALTHY.clear()
    ai._COOLDOWN["until"] = 0.0
    ai.use()
    yield calls, plan
    ai._UNHEALTHY.clear()
    ai._COOLDOWN["until"] = 0.0


def chat():
    return ai.OpenAICompatChat().complete_json("sys", [{"role": "user", "content": "hi"}])


def test_keys_order_and_dedupe(transport):
    assert ai._keys("LLM") == [PRIMARY, B1, B2]


def test_401_rotates_to_next_key_and_marks_unhealthy(transport, caplog):
    calls, plan = transport
    plan.update({PRIMARY: [401], B1: ["ok"], B2: ["ok"]})
    with caplog.at_level(logging.INFO):
        assert "Hi there" in chat()
        assert calls == [PRIMARY, B1]
        chat()  # primary is skipped during its cool-down
        assert calls == [PRIMARY, B1, B1]
    assert "llm key #1 failed: 401" in caplog.text
    for k in (PRIMARY, B1, B2, "gsk_"):
        assert k not in caplog.text


def test_5xx_and_connection_errors_rotate(transport):
    calls, plan = transport
    plan.update({PRIMARY: [503], B1: [urllib.error.URLError("down")], B2: ["ok"]})
    assert "Hi there" in chat() and calls == [PRIMARY, B1, B2]


def test_429_never_rotates_then_rules(transport, client, caplog):
    calls, plan = transport
    plan.update({PRIMARY: [(429, 1)], B1: ["ok"], B2: ["ok"]})
    with pytest.raises(ai.AiUnavailable):
        chat()
    assert calls == [PRIMARY, PRIMARY]  # same key retried once after a short Retry-After, backups untouched
    assert ai.cooling_down()
    plan[PRIMARY] = [(429, 60)]
    ai._COOLDOWN["until"] = 0.0
    calls.clear()
    with pytest.raises(ai.AiUnavailable):
        chat()
    assert calls == [PRIMARY]  # long Retry-After: no wait, no rotation
    # the concierge answers with the rules meanwhile
    ratelimit.reset()
    tok = client.post("/auth/demo/demo.owner").json()["token"]
    room = client.get("/rooms", headers={"Authorization": f"Bearer {tok}"}).json()["rooms"][5]["guest_token"]
    out = client.post(f"/public/guest/{room}/chat", json={"message": "wifi?"}).json()
    assert out["source"] == "rules" and calls == [PRIMARY]  # cooling down: not even the primary is called
    for k in (PRIMARY, B1, B2):
        assert k not in caplog.text


def test_all_keys_bad_falls_back_to_rules(transport, client, caplog):
    calls, plan = transport
    plan.update({PRIMARY: [401], B1: [403], B2: [500]})
    ratelimit.reset()
    with caplog.at_level(logging.INFO):
        ctx = concierge.context(client.get("/rooms", headers=_owner(client)).json()["rooms"][6]["guest_token"])
        res, why = concierge.llm(ctx, "wifi?", [])
        assert res is None and "all keys failed" in why
        assert calls == [PRIMARY, B1, B2]
        calls.clear()
        res, why = concierge.llm(ctx, "wifi?", [])
        assert res is None and calls == []  # all unhealthy: no calls until the cool-down ends
    assert "llm key #3 failed: 500" in caplog.text
    for k in (PRIMARY, B1, B2):
        assert k not in caplog.text


def test_400_is_not_a_key_problem(transport):
    calls, plan = transport
    plan.update({PRIMARY: [400], B1: ["ok"], B2: ["ok"]})
    with pytest.raises(ai.AiUnavailable):
        chat()
    assert calls == [PRIMARY] and not ai._UNHEALTHY


def test_stt_uses_its_own_backups(transport, monkeypatch):
    calls, plan = transport
    monkeypatch.setenv("STT_API_KEYS_BACKUP", B2)
    plan.update({PRIMARY: [401], B2: ["ok"]})

    def ok_text(req, timeout=0):
        key = req.get_header("Authorization").split(" ", 1)[1]
        calls.append(key)
        if key == PRIMARY:
            raise http_error(401)
        return Resp(b'{"text": "two towels"}')

    monkeypatch.setattr(urllib.request, "urlopen", ok_text)
    assert ai.OpenAICompatWhisper().transcribe(b"0" * 2000, "audio/webm", "en") == "two towels"
    assert calls == [PRIMARY, B2] and ai._keys("STT") == [PRIMARY, B2]
    assert config.settings.ai_key_cooldown_minutes == 10


def _owner(client):
    return {"Authorization": "Bearer " + client.post("/auth/demo/demo.owner").json()["token"]}
