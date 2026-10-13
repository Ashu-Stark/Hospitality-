"""T11 voice: glossary, extraction, WER, adapters (no network), privacy guard, fallback."""

import json
from pathlib import Path

import pytest

from ml import voice
from ml.voice.api import VoiceUnavailable
from ml.voice.config import load_glossary, load_manifest, load_voice_config
from ml.voice.evaluate import evaluate, refresh_cache
from ml.voice.extraction import Extraction, extract_fields, validate_against
from ml.voice.providers import (
    FasterWhisper,
    GroqWhisper,
    ProviderUnavailable,
    Sarvam,
    build_providers,
    guard_external,
    multipart,
    run_provider,
)
from ml.voice.wer import wer


@pytest.fixture(scope="module")
def setup():
    return load_voice_config(), load_glossary(), load_manifest()


def test_glossary_and_manifest_load(setup) -> None:
    cfg, g, m = setup
    assert 20 <= len(g.terms) <= 30
    assert all(t.english and (t.hindi or t.romanised) for t in g.terms)
    assert g.review_defaults["local_variants"] == "TODO_HM_STUDENT"
    assert all(c.expected.issue in g.issues for c in m.clips)
    assert all(c.source in cfg.allowed_external_sources for c in m.clips)


@pytest.mark.parametrize("text, room, issue, urgency", [
    ("Room no. 204 AC not working, urgent!", "204", "ac_not_working", "high"),
    ("कमरा 305 में गरम पानी नहीं आ रहा", "305", "no_hot_water", "normal"),
    ("kamra 210 mein chadar badalni hai, aaram se", "210", "linen_change", "low"),
    ("light gayi hai room 101 mein", "101", "power_cut", "normal"),  # longest phrase wins
    ("please call me back", None, None, "normal"),
])
def test_extract_fields(setup, text, room, issue, urgency) -> None:
    cfg, g, _ = setup
    e = extract_fields(text, g, cfg)
    assert (e.room, e.issue, e.urgency) == (room, issue, urgency)


def test_schema_rejects_values_outside_the_glossary(setup) -> None:
    _, g, _ = setup
    bad = Extraction(room="204", issue="unicorn", department="maintenance", urgency="high",
                     matched_terms=[])
    with pytest.raises(ValueError, match="not in the glossary"):
        validate_against(bad, g)
    with pytest.raises(ValueError):
        Extraction(room="2O4", issue=None, department=None, urgency="normal", matched_terms=[])


def test_wer() -> None:
    assert wer("room 204 ac not working", "room 204 ac not working") == 0
    assert wer("room 204 ac not working", "room 204 a c working") == pytest.approx(2 / 5)
    assert wer("कमरा 305", "कमरा 305।") == 0


def test_adapters_unavailable_without_keys(setup, monkeypatch) -> None:
    cfg, _, _ = setup
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    names = [p.name for p in build_providers(cfg)]
    assert names == cfg.provider_order
    assert GroqWhisper(cfg.groq, 1).available() == (False, "set GROQ_API_KEY")
    assert Sarvam(cfg.sarvam, 1).available()[0] is False
    assert isinstance(FasterWhisper(cfg.faster_whisper).available()[0], bool)


def test_privacy_guard_blocks_uncleared_files(setup, tmp_path, monkeypatch) -> None:
    cfg, _, m = setup
    secret = tmp_path / "real_guest_call.wav"
    secret.write_bytes(b"RIFF....")
    with pytest.raises(ProviderUnavailable, match="not a cleared clip"):
        guard_external(secret, m, cfg)
    monkeypatch.setenv("GROQ_API_KEY", "dummy")
    sent = []
    groq = GroqWhisper(cfg.groq, 1)
    monkeypatch.setattr(groq, "transcribe", lambda p: sent.append(p) or "x")
    with pytest.raises(ProviderUnavailable):
        run_provider(groq, secret, m, cfg)
    assert sent == []  # nothing was sent


def test_cloud_adapter_request_shape(setup, tmp_path, monkeypatch) -> None:
    cfg, _, m = setup
    clip = tmp_path / m.demo_clip
    clip.write_bytes(b"RIFFfake")
    monkeypatch.setenv("SARVAM_API_KEY", "k")
    seen = {}

    def fake_post(url, headers, body, timeout):
        seen.update(url=url, headers=headers, body=body)
        return {"transcript": "room 204 ka AC kaam nahi kar raha, jaldi bhejo"}

    monkeypatch.setattr("ml.voice.providers._post", fake_post)
    text = run_provider(Sarvam(cfg.sarvam, 1), clip, m, cfg)
    assert text.startswith("room 204") and seen["headers"]["api-subscription-key"] == "k"
    assert b'name="model"' in seen["body"] and b"RIFFfake" in seen["body"]
    body, ctype = multipart({"a": "b"}, "file", clip)
    assert ctype.startswith("multipart/form-data; boundary=") and body.endswith(b"--\r\n")


def test_extract_falls_back_to_cached_demo(setup, tmp_path, monkeypatch) -> None:
    cfg, g, m = setup
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    cache = tmp_path / "demo.json"
    refresh_cache(m, g, cfg, clips_dir=tmp_path, cache_path=cache)
    r = voice.extract(Path("clips") / m.demo_clip, cache_path=cache)
    assert r.fallback_used and r.extraction.room == "204" and r.synthetic
    assert json.loads(cache.read_text("utf-8"))["extraction"]["issue"] == "ac_not_working"
    with pytest.raises(VoiceUnavailable, match="not found"):
        voice.extract(tmp_path / "unknown.wav", cache_path=cache)


def test_evaluate_reference_beats_baseline(setup, tmp_path) -> None:
    cfg, g, m = setup
    table, skipped = evaluate(m, g, cfg, clips_dir=tmp_path)
    rows = {r["provider"]: r for r in table}
    assert rows["reference"]["all_fields_accuracy"] > rows["baseline"]["all_fields_accuracy"]
    assert set(skipped) == set(cfg.provider_order)


def test_hindi_full_stop_is_punctuation(setup) -> None:
    cfg, g, _ = setup
    e = extract_fields("\u0915\u092e\u0930\u093e 221 \u092e\u0947\u0902 \u092a\u093e\u0928\u0940 "
                       "\u091f\u092a\u0915 \u0930\u0939\u093e \u0939\u0948\u0964", g, cfg)
    assert (e.room, e.issue) == ("221", "water_leak")
