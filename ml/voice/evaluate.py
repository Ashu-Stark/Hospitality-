"""Evaluate voice providers (Task T11): WER and extraction accuracy per provider.

Rows:
  reference  the extractor on the manifest's reference transcripts (WER 0 by definition): an
             UPPER BOUND, and optimistic, because the transcripts and the glossary were written
             together for the SYNTHETIC demo.
  baseline   no understanding at all: no room, the most common issue / department, default
             urgency. Every provider must beat this.
  <provider> each available provider on every clip whose audio file exists (cloud providers only
             on cleared clips). Unavailable providers are listed with the reason.
Also refreshes the cached demo result (cache/demo_result.json) from the first provider that
transcribes the demo clip, or from its reference transcript when no audio / provider exists.

Run from ml/:  python run.py eval-voice
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from ml.voice.api import VoiceResult
from ml.voice.config import (
    CACHE_PATH,
    CLIPS_DIR,
    Clip,
    Glossary,
    Manifest,
    VoiceConfig,
    load_glossary,
    load_manifest,
    load_voice_config,
)
from ml.voice.extraction import Extraction, extract_fields
from ml.voice.providers import ProviderUnavailable, build_providers, run_provider
from ml.voice.wer import wer

METRICS_PATH = Path(__file__).resolve().parents[1] / "docs" / "metrics" / "voice_eval.json"
FIELDS = ("room", "issue", "urgency", "department")


def field_scores(pred: Extraction, clip: Clip) -> dict[str, bool]:
    exp = clip.expected.model_dump()
    scores = {f: getattr(pred, f) == exp[f] for f in FIELDS}
    scores["all_fields"] = all(scores.values())
    return scores


def summarise(name: str, rows: list[tuple[float, dict[str, bool]]]) -> dict:
    n = len(rows)
    out = {"provider": name, "clips": n}
    if n:
        out["wer"] = round(sum(w for w, _ in rows) / n, 4)
        for f in (*FIELDS, "all_fields"):
            out[f"{f}_accuracy"] = round(sum(s[f] for _, s in rows) / n, 4)
    return out


def baseline_predictor(manifest: Manifest, cfg: VoiceConfig) -> Callable[[str], Extraction]:
    issue = Counter(c.expected.issue for c in manifest.clips).most_common(1)[0][0]
    dept = Counter(c.expected.department for c in manifest.clips).most_common(1)[0][0]
    return lambda _text: Extraction(room=None, issue=issue, department=dept,
                                    urgency=cfg.default_urgency, matched_terms=[])


def evaluate(manifest: Manifest, glossary: Glossary, cfg: VoiceConfig,
             clips_dir: Path = CLIPS_DIR) -> tuple[list[dict], dict[str, str]]:
    ref = [(0.0, field_scores(extract_fields(c.reference, glossary, cfg), c))
           for c in manifest.clips]
    base = baseline_predictor(manifest, cfg)
    table = [summarise("reference", ref),
             summarise("baseline", [(1.0, field_scores(base(""), c)) for c in manifest.clips])]
    skipped: dict[str, str] = {}
    present = [c for c in manifest.clips if (clips_dir / c.file).exists()]
    for provider in build_providers(cfg):
        rows = []
        for clip in present:
            try:
                text = run_provider(provider, clips_dir / clip.file, manifest, cfg)
            except ProviderUnavailable as e:
                skipped[provider.name] = str(e)
                break
            rows.append((wer(clip.reference, text),
                         field_scores(extract_fields(text, glossary, cfg), clip)))
        if rows:
            table.append(summarise(provider.name, rows))
        elif provider.name not in skipped:
            ok, reason = provider.available()
            skipped[provider.name] = "no audio clips in ml/voice/clips/" + (
                "" if ok else f"; {reason}")
    return table, skipped


def refresh_cache(manifest: Manifest, glossary: Glossary, cfg: VoiceConfig,
                  clips_dir: Path = CLIPS_DIR, cache_path: Path = CACHE_PATH) -> VoiceResult:
    clip = manifest.clip(manifest.demo_clip)
    path = clips_dir / clip.file
    provider, text = "reference_transcript (no audio or provider yet)", clip.reference
    if path.exists():
        for p in build_providers(cfg):
            try:
                text, provider = run_provider(p, path, manifest, cfg), p.name
                break
            except ProviderUnavailable:
                continue
    result = VoiceResult(audio_file=clip.file, provider=provider, transcript=text,
                         extraction=extract_fields(text, glossary, cfg))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    cfg, glossary, manifest = load_voice_config(), load_glossary(), load_manifest()
    table, skipped = evaluate(manifest, glossary, cfg)
    print(f"Voice evaluation (SYNTHETIC / scripted clips; {len(manifest.clips)} in manifest, "
          f"{len(glossary.terms)} glossary terms)")
    for row in table:
        print("  " + ", ".join(f"{k}={v}" for k, v in row.items()))
    for name, reason in skipped.items():
        print(f"  skipped {name}: {reason}")
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps({"synthetic": True, "results": table,
                                        "skipped": skipped}, indent=2) + "\n", encoding="utf-8")
    cached = refresh_cache(manifest, glossary, cfg)
    print(f"  demo cache ({cached.provider}): {cached.extraction.model_dump()}")
    print(f"  saved {METRICS_PATH} and {CACHE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
