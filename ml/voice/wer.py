"""Word error rate (Task T11): word-level edit distance / reference length."""

from __future__ import annotations

import re

# Devanagari letters and marks are kept; the dandas (U+0964 / U+0965, Hindi full
# stops) count as punctuation.
_PUNCT = re.compile(r"[^\w\s\u0900-\u0963\u0966-\u097F]")


def words(text: str) -> list[str]:
    """Lower-case words with punctuation removed (Devanagari kept)."""
    return _PUNCT.sub(" ", text.lower()).split()


def edit_distance(ref: list[str], hyp: list[str]) -> int:
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1]


def wer(reference: str, hypothesis: str) -> float:
    ref, hyp = words(reference), words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return edit_distance(ref, hyp) / len(ref)
