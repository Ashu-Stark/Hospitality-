"""Onboarding demo (Part F): python run.py onboarding-demo [--llm]

Plays the cached SYNTHETIC Hindi / Hinglish fixture (fixtures/demo_transcript.yaml) through the
real API (FastAPI TestClient, in-memory mongomock: never MONGODB_URI) with no keys and no audio:
question by question, the fields extracted with their confidence, the summary, a Confirm that is
refused without the legal acknowledgements, then the Confirm result. --llm also lets the LLM
extractor read the answers (GROQ_API_KEY from the environment or the root .env; the fixture is
synthetic text, written by us).
"""

from __future__ import annotations

import argparse
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from backend.config import MONGOMOCK_URI, make_settings
from backend.onboarding.config import ONBOARDING_DIR
from backend.onboarding.schema import LEGAL_FIELDS

FIXTURE_PATH = ONBOARDING_DIR / "fixtures" / "demo_transcript.yaml"


class DemoFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    synthetic: bool
    language: str
    answers: dict[str, str]
    expected: dict[str, Any]
    expected_questions: list[str]


@lru_cache(maxsize=2)
def load_fixture(path: Path = FIXTURE_PATH) -> DemoFixture:
    return DemoFixture.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _fmt(fv: dict) -> str:
    flags = " [verify with a qualified person]" if fv["needs_verification"] else ""
    note = f" ({fv['note']})" if fv.get("note") else ""
    return f"{fv['value']}  source={fv['source']} confidence={fv['confidence']:.2f}{flags}{note}"


def play(client: TestClient, consent: bool = False, echo=print) -> dict:  # noqa: ANN001
    fx = load_fixture()
    s = client.post("/onboarding/start", json={"language": fx.language}).json()
    sid = s["session_id"]
    echo(f"session {sid[:8]}..  property_id {s['property_id']}  ({s['banner']})")
    out = s
    while out["question"] is not None:
        q = out["question"]
        text = fx.answers[q["field"]]
        echo(f"\nQ{q['number']} [{q['field']}] {q['text']}")
        echo(f"A  {text}")
        out = client.post("/onboarding/answer", json={"session_id": sid, "text": text,
                                                      "consent": consent}).json()
        echo(f"   extractor={out['extractor']}"
             + (f" (fallback: {out['fallback_reason']})" if out["fallback_reason"] else "")
             + (f" mismatches={out['mismatches']}" if out["mismatches"] else ""))
        for f in out["filled"]:
            echo(f"   {f}: {_fmt(out['fields'][f])}")
    summary = client.get("/onboarding/summary", params={"session": sid}).json()
    echo("\nSUMMARY (draft: nothing saved yet)")
    for name, fv in summary["fields"].items():
        echo(f"  {name:29} {_fmt(fv)}")
    for kind in ("errors", "warnings"):
        for f, msgs in summary[kind].items():
            echo(f"  {kind[:-1]}: {f}: {'; '.join(msgs)}")
    refused = client.post("/onboarding/confirm", json={"session": sid,
                                                       "acknowledged_legal_fields": []})
    echo(f"\nConfirm without legal acknowledgement -> HTTP {refused.status_code}: "
         f"{refused.json()['detail']['unacknowledged_legal_fields']}")
    ok = client.post("/onboarding/confirm", json={"session": sid,
                                                  "acknowledged_legal_fields": list(LEGAL_FIELDS)})
    again = client.post("/onboarding/confirm", json={
        "session": sid, "acknowledged_legal_fields": list(LEGAL_FIELDS)}).json()
    echo(f"Confirm with acknowledgement -> {ok.json()}")
    echo(f"Confirm again (double submit) -> created={again['created']} (same property)")
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Play the cached Hindi onboarding demo")
    p.add_argument("--llm", action="store_true", help="also use the LLM extractor (Groq key)")
    a = p.parse_args(argv)
    from backend.main import create_app  # after argparse: --help stays fast

    settings = make_settings("hoi_ops_onboarding_demo", mock=False, mongodb_uri=MONGOMOCK_URI)
    app = create_app(settings)
    if a.llm:
        from backend.onboarding.evaluate import load_key_from_dotenv

        cfg = app.state.onboarding_cfg
        load_key_from_dotenv(cfg.llm.api_key_env)
        if not os.environ.get(cfg.llm.api_key_env):
            print(f"--llm: {cfg.llm.api_key_env} not set; using the rule-based extractor")
        app.state.onboarding_cfg = cfg.model_copy(update={"llm": cfg.llm.model_copy(
            update={"allow_cloud_llm_for_owner_text": True})})
    print("Hotel onboarding demo: cached SYNTHETIC Hindi / Hinglish transcript, no audio")
    with TestClient(app) as client:
        summary = play(client, consent=a.llm)
    fx = load_fixture()
    from backend.onboarding.evaluate import same

    wrong = [f for f, v in fx.expected.items() if not same(f, summary["fields"][f]["value"], v)]
    verdict = "all match" if not wrong else f"MISMATCH {wrong}"
    print(f"\nexpected fields from the fixture: {verdict}")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
