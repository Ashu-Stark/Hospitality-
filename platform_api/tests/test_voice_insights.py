"""Worker voice commands (/me/voice/*) and super-admin insights (/platform/insights). Offline, SYNTHETIC data."""

from datetime import timedelta

import pytest
from conftest import jpeg

from hoi_platform import mongo, ratelimit
from hoi_platform.services import ai, insights


@pytest.fixture(autouse=True)
def _fresh():
    ratelimit.reset()
    ai.use()
    yield
    ai.use()


def _setup(client, owner):
    client.post("/dispatch/reset", headers=owner)
    client.put("/dispatch/context", json={"working": {"HS05": "housekeeping", "MT1": "maintenance"}, "bands": {}}, headers=owner)


def cmd(client, worker, text, lang="en"):
    r = client.post("/me/voice/command", json={"text": text, "lang": lang}, headers=worker)
    assert r.status_code == 200, r.text
    return r.json()


def test_worker_voice_flow(client, owner, worker):
    _setup(client, owner)
    assert cmd(client, worker, "what's next")["intent"] == "whats_next"
    job = client.post("/dispatch/jobs", json={"title": "Extra towels", "room": "305", "department": "housekeeping"}, headers=owner).json()
    assert job["offer_to"] == "HS05"
    nxt = cmd(client, worker, "what's next")
    assert nxt["intent"] == "whats_next" and "Extra towels" in nxt["reply"] and nxt["proposed_action"]["action"] == "accept"
    hi = cmd(client, worker, "अगला काम क्या है", "hi")
    assert hi["lang"] == "hi" and "नया काम" in hi["reply"]
    acc = cmd(client, worker, "accept")
    assert acc["intent"] == "accept" and acc["proposed_action"]["params"]["job_id"] == job["id"]
    assert client.get("/dispatch/jobs", headers=owner).json()[0]["status"] == "offered"  # command never acts
    r = client.post("/me/voice/act", json={"action": "accept", "params": {"job_id": job["id"]}}, headers=worker)
    assert r.status_code == 200 and r.json()["job"]["status"] == "accepted"
    st = cmd(client, worker, "start")
    assert st["proposed_action"] == {"action": "photo", "params": {"job_id": job["id"], "kind": "before"}, "label": "Take BEFORE photo"}
    assert client.post("/me/voice/act", json={"action": "start", "params": {"job_id": job["id"]}}, headers=worker).status_code == 422
    client.post(
        f"/dispatch/jobs/{job['id']}/photos", data={"kind": "before"}, files={"file": ("b.jpg", jpeg(), "image/jpeg")}, headers=worker
    )
    st = cmd(client, worker, "shuru karo")
    assert st["proposed_action"]["action"] == "start"
    assert (
        client.post("/me/voice/act", json={"action": "start", "params": {"job_id": job["id"]}}, headers=worker).json()["job"]["status"]
        == "in_progress"
    )
    done = cmd(client, worker, "ho gaya")
    assert (
        done["intent"] == "done" and done["proposed_action"]["action"] == "photo" and done["proposed_action"]["params"]["kind"] == "after"
    )
    assert client.post("/me/voice/act", json={"action": "done", "params": {"job_id": job["id"]}}, headers=worker).status_code == 422
    assert mongo.col("audit_log").find_one({"action": "voice.accept"})


def test_worker_voice_report_issue_and_decline(client, owner, worker):
    _setup(client, owner)
    rep = cmd(client, worker, "Room 204 tap leaking, urgent")
    assert rep["intent"] == "report_issue"
    p = rep["proposed_action"]["params"]
    assert p["room"] == "204" and p["department"] == "maintenance" and p["urgency"] == "high"
    r = client.post("/me/voice/act", json={"action": "report_issue", "params": p}, headers=worker)
    assert r.status_code == 200 and r.json()["job"]["department"] == "maintenance" and r.json()["job"]["room"] == "204"
    bad = client.post("/me/voice/act", json={"action": "report_issue", "params": {"room": "999", "issue": "x"}}, headers=worker)
    assert bad.status_code == 404
    hi = cmd(client, worker, "कमरा 305 में एसी खराब है", "hi")
    assert hi["intent"] == "report_issue" and hi["proposed_action"]["params"]["room"] == "305"
    job = client.post("/dispatch/jobs", json={"title": "Fresh linen", "room": "101", "department": "housekeeping"}, headers=owner).json()
    dec = cmd(client, worker, "no, busy")
    assert dec["intent"] == "decline" and dec["proposed_action"]["params"]["job_id"] == job["id"]
    assert client.post("/me/voice/act", json={"action": "decline", "params": {"job_id": job["id"]}}, headers=worker).status_code == 200
    # someone else's job cannot be accepted by voice
    other = client.post("/dispatch/jobs", json={"title": "Fix fan", "room": "102", "department": "maintenance"}, headers=owner).json()
    assert client.post("/me/voice/act", json={"action": "accept", "params": {"job_id": other["id"]}}, headers=worker).status_code == 409
    assert cmd(client, worker, "help")["intent"] == "help"
    assert cmd(client, worker, "my shift")["intent"] == "my_shift"


def test_worker_voice_roles_and_transcribe(client, owner, worker, monkeypatch):
    assert client.post("/me/voice/command", json={"text": "next"}, headers=owner).status_code == 403
    files = {"audio": ("a.webm", b"0" * 3000, "audio/webm")}
    assert client.post("/me/voice/transcribe", files=files, data={"consent": "false"}, headers=worker).status_code == 422
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert client.post("/me/voice/transcribe", files=files, data={"consent": "true"}, headers=worker).status_code == 503

    class Stt:
        name = "fake-stt"

        def available(self):
            return True, "ok"

        def transcribe(self, audio, mime, lang):
            return "अगला काम"

    monkeypatch.setenv("GROQ_API_KEY", "test-not-a-real-key")
    ai.use(stt=Stt())
    r = client.post("/me/voice/transcribe", files=files, data={"consent": "true", "lang": "hi"}, headers=worker)
    assert r.json() == {"text": "अगला काम", "provider": "fake-stt"}


# ------------------------------------------------------------------ insights
def test_insights_scoping_and_shape(client, platform, owner):
    assert client.get("/platform/insights", headers=owner).status_code == 403
    r = client.get("/platform/insights?days=30", headers=platform)
    assert r.status_code == 200
    out = r.json()
    assert out["k_min_workers"] == 5 and out["totals"]["hotels"] == len(out["hotels"]) and "SYNTHETIC" in out["note"]
    demo = next(h for h in out["hotels"] if h["tenant_id"] == "org_demo")
    for k in (
        "plan",
        "status",
        "rooms",
        "occupied_now",
        "staff",
        "active_users",
        "jobs",
        "guest_requests",
        "checkouts",
        "feedback",
        "inventory",
        "performance",
        "last_activity",
        "properties",
    ):
        assert k in demo
    assert demo["rooms"] == 24 + 6 and [p["rooms"] for p in demo["properties"]] == [24, 6]  # hotel + demo homestay
    assert demo["inventory"]["stock_value"] > 0
    assert demo["performance"]["suppressed"] is True and demo["performance"]["average_score"] is None  # < 5 scored workers


def test_insights_performance_shown_with_five_workers(client, platform):
    t = client.post("/platform/tenants", json={"name": "Five Workers Inn (test)", "first_property": "Main"}, headers=platform).json()[
        "tenant"
    ]
    tid = t["id"]
    now = mongo.now()
    docs = []
    for w in range(5):
        for k in range(5):
            created = now - timedelta(days=1, minutes=10 * k + w)
            docs.append(
                {
                    "id": mongo.new_id("job"),
                    "tenant_id": tid,
                    "title": "Clean",
                    "department": "housekeeping",
                    "room": "101",
                    "urgency": "medium",
                    "source": "test",
                    "status": "done",
                    "kind": "general",
                    "created_at": created,
                    "accepted_at": created + timedelta(seconds=5),
                    "started_at": created + timedelta(minutes=1),
                    "done_at": created + timedelta(minutes=20),
                    "assigned_to": f"W{w}",
                    "attempts": [
                        {"employee_id": f"W{w}", "offered_at": created, "outcome": "accepted", "at": created + timedelta(seconds=5)}
                    ],
                    "ranking": [],
                    "_v": 1,
                }
            )
    mongo.col("jobs").insert_many(docs)
    h = insights.hotel(next(x for x in client.get("/platform/tenants", headers=platform).json() if x["id"] == tid), 30)
    assert h["performance"]["suppressed"] is False and h["performance"]["workers_scored"] == 5 and h["performance"]["average_score"] > 0
    assert (
        h["jobs"]["count"] == 25
        and h["jobs"]["on_time_pct"] == 100.0
        and h["jobs"]["median_completion_min"] == pytest.approx(19.9, abs=0.2)
    )


def test_mic_allowed_on_web_apps(client):
    assert "microphone=(self)" in client.get("/guest/").headers["permissions-policy"]


# ------------------------------------------------------------------ provider switch (OpenAI-compatible)
class _Resp:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        import json as _j

        return _j.dumps(self.payload).encode()


def test_llm_and_stt_provider_from_env(monkeypatch):
    import json as _j
    import urllib.request

    from hoi_platform import config

    sent = []

    def fake_urlopen(req, timeout=0):
        sent.append(req)
        if req.full_url.endswith("/chat/completions"):
            return _Resp({"choices": [{"message": {"content": '{"reply": "hi", "lang": "en", "action": null}'}}]})
        return _Resp({"text": "hello"})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    for k in ("LLM_API_KEY", "STT_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1/")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("LLM_JSON_MODE", "false")
    monkeypatch.setenv("STT_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("STT_MODEL", "whisper-1")
    config.reload()
    try:
        assert ai.OpenAICompatChat().available()[0] is False  # no key at all -> rules fallback
        monkeypatch.setenv("LLM_API_KEY", "ollama")
        monkeypatch.setenv("GROQ_API_KEY", "groq-fallback-key")
        assert ai.chat_url() == "http://localhost:11434/v1/chat/completions"
        ai.OpenAICompatChat().complete_json("sys", [{"role": "user", "content": "hi"}])
        body = _j.loads(sent[-1].data)
        assert body["model"] == "qwen2.5:7b" and "response_format" not in body and "reasoning_effort" not in body
        assert sent[-1].get_header("Authorization") == "Bearer ollama"
        out = ai.transcribe(b"0" * 2000, "audio/webm", "en")
        assert out["text"] == "hello" and sent[-1].full_url == "https://api.openai.com/v1/audio/transcriptions"
        assert b'name="model"\r\n\r\nwhisper-1' in sent[-1].data
        assert sent[-1].get_header("Authorization") == "Bearer groq-fallback-key"  # STT_API_KEY unset -> GROQ_API_KEY
        monkeypatch.setenv("LLM_JSON_MODE", "true")
        for k in ("LLM_BASE_URL", "LLM_MODEL", "STT_BASE_URL", "STT_MODEL"):
            monkeypatch.delenv(k)
        config.reload()
        ai.OpenAICompatChat().complete_json("sys", [])
        body = _j.loads(sent[-1].data)
        assert sent[-1].full_url == "https://api.groq.com/openai/v1/chat/completions"
        assert body["model"] == "openai/gpt-oss-20b" and body["response_format"] == {"type": "json_object"}
    finally:
        monkeypatch.undo()
        config.reload()
