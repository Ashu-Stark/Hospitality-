"""Speech: text normalisation for spoken replies, server TTS (fake Sarvam), local speech-to-text provider. Offline."""

import re
import sys
from pathlib import Path

import pytest
from conftest import auth

from hoi_platform import config, mongo, ratelimit
from hoi_platform.services import ai, tts
from hoi_platform.services.speech_text import HI_0_99, for_speech, hi_number, sentences

VOICE_JS = Path(__file__).resolve().parent.parent / "hoi_platform" / "static" / "shared" / "voice.js"


@pytest.mark.parametrize(
    ("text", "lang", "want"),
    [
        ("11:00", "hi", "ग्यारह बजे"),
        ("07:30", "hi", "साढ़े सात बजे"),
        ("7:30", "hi", "साढ़े सात बजे"),
        ("13:00", "hi", "दोपहर एक बजे"),
        ("14:30", "hi", "दोपहर ढाई बजे"),
        ("13:30", "hi", "दोपहर डेढ़ बजे"),
        ("10:15", "hi", "सवा दस बजे"),
        ("10:45", "hi", "पौने ग्यारह बजे"),
        ("22:30", "hi", "रात साढ़े दस बजे"),
        ("18:00", "hi", "शाम छह बजे"),
        ("09:10", "hi", "नौ बजकर दस मिनट"),
        ("नाश्ता 07:30-10:30", "hi", "नाश्ता साढ़े सात बजे से साढ़े दस बजे तक"),
        ("नाश्ता 07:30-10:30 तक", "hi", "नाश्ता साढ़े सात बजे से साढ़े दस बजे तक"),
        ("चेकआउट 11:00 बजे है", "hi", "चेकआउट ग्यारह बजे है"),
        ("₹180", "hi", "एक सौ अस्सी रुपये"),
        ("180 रुपये", "hi", "एक सौ अस्सी रुपये"),
        ("कमरा 204", "hi", "कमरा दो सौ चार"),
        ("कमरा २०४", "hi", "कमरा दो सौ चार"),
        ("ext. 9", "hi", "एक्सटेंशन नौ"),
        ("₹1,250", "hi", "एक हज़ार दो सौ पचास रुपये"),
        ("11:00", "en", "eleven o'clock"),
        ("13:30", "en", "one thirty p.m."),
        ("12:00", "en", "twelve noon"),
        ("07:05", "en", "seven oh five"),
        ("Breakfast 07:30-10:30", "en", "Breakfast seven thirty to ten thirty"),
        ("Aloo paratha ₹180", "en", "Aloo paratha 180 rupees"),
        ("**Done** 😀 #1", "en", "Done 1"),
    ],
)
def test_for_speech(text, lang, want):
    assert for_speech(text, lang) == want


def test_numbers_and_sentences():
    assert hi_number(0) == "शून्य" and hi_number(99) == "निन्यानवे" and hi_number(100) == "एक सौ"
    assert hi_number(150000) == "एक लाख पचास हज़ार"
    assert sentences("नमस्ते। कैसे हैं? Fine. ok!") == ["नमस्ते।", "कैसे हैं?", "Fine.", "ok!"]


def test_js_mirror_uses_the_same_hindi_numbers():
    js = VOICE_JS.read_text(encoding="utf-8")
    m = re.search(r'const HI_0_99 = "([^"]+)"\.split', js)
    assert m and m.group(1).split(" ") == HI_0_99
    for fn in ("hiTime", "enTime", "normalize", "fillPicker", "setMuted"):
        assert fn in js


# ------------------------------------------------------------------ server TTS
class FakeSarvam:
    name = "fake-sarvam"

    def __init__(self, ok=True, fail=False):
        self.ok, self.fail, self.calls = ok, fail, []

    def available(self):
        return self.ok, "ok"

    def synth(self, text, language_code, model, speaker, pace):
        self.calls.append((text, language_code, model, speaker, pace))
        if self.fail:
            raise OSError("down")
        return b"RIFF" + b"\x00" * 64


@pytest.fixture
def sarvam(monkeypatch):
    monkeypatch.setattr(config, "settings", config.settings.__class__(**{**config.settings.__dict__, "tts_provider": "sarvam"}))
    ratelimit.reset()
    mongo.col("tts_cache").delete_many({})
    fake = FakeSarvam()
    tts.use(fake)
    yield fake
    tts.use()
    ratelimit.reset()


def _tok(client, owner):
    return client.get("/rooms", headers=owner).json()["rooms"][2]["guest_token"]


def test_tts_default_browser_is_204(client, owner):
    tts.use(FakeSarvam())
    try:
        r = client.post(f"/public/guest/{_tok(client, owner)}/tts", json={"text": "नमस्ते", "lang": "hi"})
        assert r.status_code == 204  # TTS_PROVIDER=browser (default)
    finally:
        tts.use()


def test_tts_sarvam_cache_and_fallbacks(client, owner, worker, sarvam, monkeypatch):
    url = f"/public/guest/{_tok(client, owner)}/tts"
    r = client.post(url, json={"text": "चेकआउट 11:00 बजे है।", "lang": "hi"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content.startswith(b"RIFF")
    text, code, model, speaker, pace = sarvam.calls[0]
    assert text == "चेकआउट ग्यारह बजे है।" and code == "hi-IN" and model == "bulbul:v3" and speaker == "priya" and pace == 0.9
    assert client.post(url, json={"text": "चेकआउट 11:00 बजे है।", "lang": "hi"}).status_code == 200
    assert len(sarvam.calls) == 1  # cache hit: no second paid call
    assert client.post(url, json={"text": "Hello", "lang": "en"}).status_code == 200 and sarvam.calls[-1][1] == "en-IN"
    assert client.post(url, json={"text": "x" * 501, "lang": "en"}).status_code == 422
    assert client.post("/me/voice/tts", json={"text": "Accept?", "lang": "en"}, headers=worker).status_code == 200
    assert client.post("/me/voice/tts", json={"text": "Accept?", "lang": "en"}, headers=owner).status_code == 403
    tts.use(FakeSarvam(ok=False))  # no SARVAM_API_KEY
    assert client.post(url, json={"text": "new text", "lang": "en"}).status_code == 204
    tts.use(FakeSarvam(fail=True))  # API error
    assert client.post(url, json={"text": "another text", "lang": "en"}).status_code == 204


def test_sarvam_client_without_key(monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    assert tts.SarvamTts().available()[0] is False


def test_tts_rate_limit(client, owner, sarvam):
    url = f"/public/guest/{_tok(client, owner)}/tts"
    codes = [client.post(url, json={"text": f"t{i}", "lang": "en"}).status_code for i in range(21)]
    assert codes[:20] == [200] * 20 and codes[20] == 429


# ------------------------------------------------------------------ local speech-to-text (faster-whisper)
def _local(monkeypatch):
    monkeypatch.setattr(config, "settings", config.settings.__class__(**{**config.settings.__dict__, "stt_provider": "local"}))


def test_local_stt_without_package_is_503(client, owner, monkeypatch):
    _local(monkeypatch)
    ai.use()
    monkeypatch.setitem(sys.modules, "faster_whisper", None)  # import fails like a machine without the package
    monkeypatch.setattr(ai.importlib.util, "find_spec", lambda name: None)
    assert isinstance(ai.stt_adapter(), ai.LocalWhisper)
    ratelimit.reset()
    r = client.post(
        f"/public/guest/{_tok(client, owner)}/transcribe",
        files={"audio": ("a.webm", b"0" * 3000, "audio/webm")},
        data={"consent": "true"},
    )
    assert r.status_code == 503 and "type instead" in r.json()["detail"]


def test_local_stt_with_fake_model_deletes_temp_file(monkeypatch):
    _local(monkeypatch)
    seen = {}

    class Seg:
        text = " दो तौलिये चाहिए "

    class Model:
        def transcribe(self, pcm, language=None, beam_size=1, vad_filter=True):
            seen["lang"] = language
            return [Seg()], None

    def decode(path):
        seen["path"] = path
        assert Path(path).exists()  # the temp file exists while decoding
        return [0.0]

    monkeypatch.setattr(ai, "_decode", decode)

    monkeypatch.setattr(ai.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(ai.LocalWhisper, "model", classmethod(lambda cls: Model()))
    out = ai.transcribe(b"0" * 2000, "audio/webm;codecs=opus", "hi")
    assert out == {"text": "दो तौलिये चाहिए", "provider": "local-whisper"}
    assert seen["lang"] == "hi" and seen["path"].endswith(".webm") and not Path(seen["path"]).exists()


def test_worker_auth_helper_still_works(client):
    assert auth(client, "HS05")


def test_local_stt_cuda_runtime_failure_falls_back_to_cpu(monkeypatch):
    _local(monkeypatch)

    class Seg:
        text = "hello"

    class Gpu:
        def transcribe(self, *a, **k):
            raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")

    class Cpu:
        def transcribe(self, *a, **k):
            return [Seg()], None

    monkeypatch.setattr(ai.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(ai, "_decode", lambda path: [0.0])
    monkeypatch.setattr(ai.LocalWhisper, "_model", Gpu())
    monkeypatch.setattr(ai.LocalWhisper, "_device", "cuda")

    def to_cpu(cls):
        cls._model, cls._device = Cpu(), "cpu"

    monkeypatch.setattr(ai.LocalWhisper, "to_cpu", classmethod(to_cpu))
    monkeypatch.setattr(ai.LocalWhisper, "model", classmethod(lambda cls: cls._model))
    assert ai.transcribe(b"0" * 2000, "audio/wav", "en")["text"] == "hello" and ai.LocalWhisper._device == "cpu"
