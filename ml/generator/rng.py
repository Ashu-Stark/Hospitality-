"""Named, independent random streams derived from the config seed.

Each stage gets the child SeedSequence at a fixed index, so adding a new stream at the
end never changes the draws of existing ones. Indices 0 and 1 equal what
np.random.default_rng(seed).spawn(2) produced in Task 2.
"""

from __future__ import annotations

import numpy as np

STREAMS = ("weather", "occupancy", "staff", "skills", "attrition", "signals", "heroes",
           "replacement_skills")


def stream_rngs(seed: int, *names: str) -> list[np.random.Generator]:
    """One Generator per requested stream name, in the order given."""
    unknown = [n for n in names if n not in STREAMS]
    if unknown:
        raise ValueError(f"unknown stream(s) {unknown}; known: {STREAMS}")
    children = np.random.SeedSequence(seed).spawn(len(STREAMS))
    return [np.random.default_rng(children[STREAMS.index(n)]) for n in names]
