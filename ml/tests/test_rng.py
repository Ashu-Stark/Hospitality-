import numpy as np
import pytest

from ml.generator.rng import STREAMS, stream_rngs


def test_first_two_streams_match_task2_spawn() -> None:
    old_weather, old_occ = np.random.default_rng(42).spawn(2)
    weather, occ = stream_rngs(42, "weather", "occupancy")
    assert np.array_equal(weather.random(5), old_weather.random(5))
    assert np.array_equal(occ.random(5), old_occ.random(5))


def test_streams_independent_of_request_order() -> None:
    (a,) = stream_rngs(1, "staff")
    _, b = stream_rngs(1, "weather", "staff")
    assert np.array_equal(a.random(3), b.random(3))


def test_streams_differ() -> None:
    draws = [g.random() for g in stream_rngs(1, *STREAMS)]
    assert len(set(draws)) == len(STREAMS)


def test_unknown_stream_raises() -> None:
    with pytest.raises(ValueError):
        stream_rngs(1, "nope")
