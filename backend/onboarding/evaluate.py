"""Onboarding extraction eval (Part F): python run.py eval-onboarding [--no-llm] [--out PATH]

Runs every SYNTHETIC utterance in eval/utterances.yaml through the rule-based extractor and, when
GROQ_API_KEY is set (environment, or the root .env, read for that one key only), the LLM
extractor. Reports field-level accuracy per extractor and language, and the cross-check numbers:
how many LLM numbers the normaliser flagged, and how many of those flags were real LLM errors.
The utterances were WRITTEN BY US together with the word lists, so the scores are optimistic
and say nothing about real speech. Recorded clips: if an utterance names a clip that exists in
ml/voice/clips it would be transcribed; none exist yet, so STT WER is reported as not run.
Never sends anything but these synthetic sentences; never touches MongoDB.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from backend.config import REPO_ROOT
from backend.onboarding.config import ONBOARDING_DIR, load_config
from backend.onboarding.extract import ExtractionResult, extract_rules
from backend.onboarding.llm import ChatAdapter, default_adapter, extract
from ml.voice.config import CLIPS_DIR

MANIFEST_PATH = ONBOARDING_DIR / "eval" / "utterances.yaml"
RESULTS_PATH = ONBOARDING_DIR / "eval" / "results.json"
TOLERANCE = 1e-6
WARNING = ("OPTIMISTIC: the utterances were written by us (the developers) together with the "
           "extractor's word lists; they are not recorded speech and contain no speech-to-text "
           "errors. These scores say nothing about real Hindi / Hinglish speech.")


class Utterance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    language: str
    question: str | None
    text: str
    expected: dict[str, Any]
    clip: str | None = None


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    synthetic: bool
    utterances: list[Utterance]


def load_manifest(path: Path = MANIFEST_PATH) -> Manifest:
    return Manifest.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_key_from_dotenv(name: str, env_file: Path = REPO_ROOT / ".env") -> None:
    """setdefault ONE variable from the root .env (never prints it; ignores every other line,
    so MONGODB_URI is never picked up here)."""
    if os.environ.get(name) or not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key.strip() == name and value.strip():
            os.environ.setdefault(name, value.strip().strip('"').strip("'"))
            return


def same(field: str, got: Any, exp: Any) -> bool:
    if got is None:
        return False
    if field == "peak_months":
        return sorted(got) == sorted(exp)
    if field == "shifts":
        return [(s["name"], s["start"], s["end"]) for s in got] == [
            (s["name"], s["start"], s["end"]) for s in exp]
    if isinstance(exp, (int, float)) and not isinstance(exp, bool):
        return isinstance(got, (int, float)) and abs(float(got) - float(exp)) < TOLERANCE
    if isinstance(exp, str):
        return str(got).strip().lower() == exp.strip().lower()
    return got == exp


def score(results: list[tuple[Utterance, ExtractionResult]]) -> dict:
    total = correct = extra = 0
    by_lang: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    errors = []
    for u, r in results:
        for field, exp in u.expected.items():
            got = r.fields[field].value if field in r.fields else None
            ok = same(field, got, exp)
            total, correct = total + 1, correct + ok
            by_lang[u.language][0] += ok
            by_lang[u.language][1] += 1
            if not ok:
                errors.append({"id": u.id, "field": field, "expected": exp, "got": got})
        extra += len(set(r.fields) - set(u.expected))
    return {"fields": total, "correct": correct,
            "accuracy": round(correct / total, 4) if total else None,
            "by_language": {k: {"correct": c, "fields": n, "accuracy": round(c / n, 4)}
                            for k, (c, n) in sorted(by_lang.items())},
            "extra_fields_not_expected": extra, "errors": errors}


def run(use_llm: bool = True, adapter: ChatAdapter | None = None) -> dict:
    cfg = load_config()
    manifest = load_manifest()
    rules = [(u, extract_rules(u.text, u.question, cfg)) for u in manifest.utterances]
    out: dict[str, Any] = {"synthetic": True, "warning": WARNING,
                           "utterances": len(manifest.utterances),
                           "languages": sorted({u.language for u in manifest.utterances}),
                           "rules": score(rules)}
    if use_llm:
        if adapter is None:  # the real Groq adapter: key from the environment or root .env
            load_key_from_dotenv(cfg.llm.api_key_env)
            adapter = default_adapter(cfg)
        ok, why = adapter.available()
    else:
        ok, why = False, "--no-llm"
    if ok:
        llm = [(u, extract(u.text, u.question, adapter, cfg)) for u in manifest.utterances]
        flagged = real = 0
        for u, r in llm:
            for f in r.mismatches:
                flagged += 1
                exp = u.expected.get(f)
                real += exp is None or not same(f, r.fields[f].value, exp)
        fallbacks = [r.fallback_reason for _, r in llm if r.method == "rules"]
        out["llm"] = {**score(llm), "model": cfg.llm.model,
                      "calls_fell_back_to_rules": len(fallbacks),
                      "fallback_reasons": sorted(set(filter(None, fallbacks))),
                      "cross_check": {"numbers_flagged_please_confirm": flagged,
                                      "flags_that_were_real_llm_errors": real,
                                      "flags_on_correct_values": flagged - real}}
    else:
        out["llm"] = {"not_run": f"LLM extractor not run: {why}"}
    clips = [u.clip for u in manifest.utterances if u.clip and (CLIPS_DIR / u.clip).exists()]
    out["audio"] = (f"{len(clips)} recorded clips found" if clips else
                    "not run: no recorded onboarding clips in ml/voice/clips, so no STT word "
                    "error rate and no audio extraction accuracy")
    return out


def report(out: dict) -> str:
    lines = ["Onboarding extraction eval (SYNTHETIC utterances)", WARNING, "",
             f"utterances: {out['utterances']}  languages: {', '.join(out['languages'])}"]
    for name in ("rules", "llm"):
        r = out[name]
        if "not_run" in r:
            lines.append(f"{name}: {r['not_run']}")
            continue
        lines.append(f"{name}: field accuracy {r['correct']}/{r['fields']} = {r['accuracy']:.1%}"
                     f"  (extra fields not expected: {r['extra_fields_not_expected']})")
        for lang, v in r["by_language"].items():
            lines.append(f"    {lang:17} {v['correct']}/{v['fields']} = {v['accuracy']:.1%}")
        for e in r["errors"]:
            lines.append(f"    miss {e['id']} {e['field']}: expected {e['expected']}, "
                         f"got {e['got']}")
        if name == "llm":
            cc = r["cross_check"]
            lines.append(f"    model {r['model']}; fell back to rules "
                         f"{r['calls_fell_back_to_rules']} times {r['fallback_reasons'] or ''}")
            lines.append(f"    cross-check: {cc['numbers_flagged_please_confirm']} numbers "
                         f"flagged 'please confirm', {cc['flags_that_were_real_llm_errors']} of "
                         f"them real LLM errors, {cc['flags_on_correct_values']} on correct "
                         "values")
    lines.append(f"audio: {out['audio']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--no-llm", action="store_true", help="rule-based extractor only")
    p.add_argument("--out", type=Path, default=RESULTS_PATH)
    a = p.parse_args(argv)
    out = run(use_llm=not a.no_llm)
    a.out.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(report(out))
    print(f"\nwritten: {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
