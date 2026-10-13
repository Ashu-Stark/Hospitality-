"""Onboarding Part F: cached Hindi demo fixture, demo properties, evaluation (all SYNTHETIC)."""

import io
import json
import urllib.error

import pytest

from backend.onboarding import evaluate
from backend.onboarding.config import load_config
from backend.onboarding.demo import load_fixture, play
from backend.onboarding.llm import GroqChat

CFG = load_config()


def test_cached_hindi_demo_transcript_gives_the_expected_summary(client) -> None:  # noqa: ANN001
    fx = load_fixture()
    assert fx.synthetic and fx.language == "hi"
    lines: list[str] = []
    summary = play(client, echo=lines.append)
    for field, expected in fx.expected.items():
        assert evaluate.same(field, summary["fields"][field]["value"], expected), field
    asked = [ln.split("[")[1].split("]")[0] for ln in lines if ln.startswith("\nQ")]
    assert asked == fx.expected_questions
    assert any("HTTP 422" in ln for ln in lines) and any("created=False" in ln for ln in lines)
    r = client.get("/onboarding/demo-transcript").json()
    assert r["synthetic"] is True and r["answers"] == fx.answers


def test_eval_manifest_is_synthetic_and_covers_the_languages() -> None:
    m = evaluate.load_manifest()
    assert m.synthetic and len(m.utterances) >= 20
    assert {"english", "hindi_roman", "hindi_devanagari", "hinglish"} <= {
        u.language for u in m.utterances}
    assert len({u.id for u in m.utterances}) == len(m.utterances)


def test_eval_rules_offline_reports_accuracy_and_the_optimism_warning() -> None:
    out = evaluate.run(use_llm=False)
    assert "written by us" in out["warning"] and out["synthetic"]
    assert out["rules"]["fields"] >= 20 and 0 <= out["rules"]["accuracy"] <= 1
    assert "not run" in out["llm"]["not_run"] and "no recorded" in out["audio"]
    assert "OPTIMISTIC" in evaluate.report(out)


class WrongRooms:
    """Fake LLM that always claims 99 rooms: every rooms answer must be flagged."""

    name = "fake"

    def available(self) -> tuple[bool, str]:
        return True, "ok"

    def complete_json(self, system: str, user: str) -> str:
        return json.dumps({"rooms": 99})


def test_eval_counts_cross_check_mismatches_with_a_fake_llm() -> None:
    out = evaluate.run(use_llm=True, adapter=WrongRooms())
    cc = out["llm"]["cross_check"]
    assert cc["numbers_flagged_please_confirm"] == len(evaluate.load_manifest().utterances)
    assert cc["flags_that_were_real_llm_errors"] == cc["numbers_flagged_please_confirm"]


def test_dotenv_loader_reads_only_the_requested_key(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    env = tmp_path / ".env"
    env.write_text("MONGODB_URI=mongodb+srv://example\nGROQ_API_KEY=test-key\n", encoding="utf-8")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("MONGODB_URI", "mongomock://")
    evaluate.load_key_from_dotenv("GROQ_API_KEY", env)
    import os

    assert os.environ["GROQ_API_KEY"] == "test-key"
    assert os.environ["MONGODB_URI"] == "mongomock://"


def test_groq_adapter_retries_on_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls, waits = [], []

    def fake_urlopen(req, timeout):  # noqa: ANN001, ANN202
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "rate", {"retry-after": "2"}, None)
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode())

    monkeypatch.setenv(CFG.llm.api_key_env, "test-not-a-real-key")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", waits.append)
    assert GroqChat(CFG.llm).complete_json("s", "u") == "{}"
    assert len(calls) == 2 and waits == [2.0]
