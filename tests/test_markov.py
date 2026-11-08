from __future__ import annotations

from fractions import Fraction

import pytest

from wtpm.markov import run_markov, time_to_rand

EPS = 1e-9


def test_random_values_match_tidal_time_to_rand():
    assert [time_to_rand(t) for t in (0, Fraction(1, 4), 1, Fraction(301, 3))] == [
        0.5,
        0.6295689214020967,
        0.5177721455693245,
        0.08714574761688709,
    ]


@pytest.mark.parametrize(
    ("steps", "start", "matrix", "expected"),
    [
        (8, 1, [[3, 5, 2], [4, 4, 2], [0, 1, 0]], {
            0: [1, 0, 1, 1, 0, 0, 0, 1],
            1: [1, 1, 0, 2, 2, 2, 2, 2],
            2: [1, 2, 2, 2, 2, 2, 2, 2],
            7: [1, 1, 0, 2, 2, 2, 2, 2],
            123: [1, 2, 2, 2, 2, 2, 2, 2],
        }),
        (4, 0, [[0.5, 0.5, 0], [1, 0, 0], [0, 1, 0]], {
            0: [0, 2, 2, 2],
            1: [0, 0, 0, 2],
            2: [0, 0, 2, 2],
            7: [0, 0, 2, 2],
            123: [0, 0, 0, 2],
        }),
        (6, 2, [[0, 0.3, 0.7], [0.2, 0, 0.8], [0, 0, 0]], {c: [2] * 6 for c in (0, 1, 2, 7, 123)}),
        (8, 0, [[0.5, 0.5, EPS], [1, EPS, EPS], [EPS, 1, EPS]], {
            0: [0, 0, 1, 0, 0, 0, 0, 0],
            1: [0, 1, 0, 1, 0, 1, 0, 0],
            2: [0, 1, 0, 1, 0, 0, 1, 0],
            3: [0, 1, 0, 0, 1, 0, 1, 0],
            50: [0, 0, 0, 1, 0, 1, 0, 0],
            199: [0, 1, 0, 0, 1, 0, 0, 0],
        }),
    ],
)
def test_chain_matches_tidal_markov_pat_per_cycle(steps, start, matrix, expected):
    rows = [[float(p) for p in row] for row in matrix]
    for cycle, states in expected.items():
        assert run_markov(steps, rows, start, cycle) == states
