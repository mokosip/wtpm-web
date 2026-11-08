from __future__ import annotations

from fractions import Fraction

SEED_SCALE = 536870912
INT64 = 1 << 64


def _signed(value: int) -> int:
    value %= INT64
    return value - INT64 if value >= INT64 >> 1 else value


def _xorwise(value: int) -> int:
    a = _signed((value << 13) ^ value)
    b = _signed((a >> 17) ^ a)
    return _signed((b << 5) ^ b)


def time_to_rand(time: Fraction | int) -> float:
    if time == 0:
        return 0.5
    cycles = Fraction(time) / 300
    seed = _xorwise(int((cycles - int(cycles)) * SEED_SCALE))
    return (seed % SEED_SCALE) / SEED_SCALE


def run_markov(steps: int, matrix: list[list[float]], start: int, cycle: int) -> list[int]:
    thresholds = []
    for row in matrix:
        by_sum: dict[float, int] = {}
        total = 0.0
        for index, weight in enumerate(row):
            total += weight
            by_sum[total] = index
        thresholds.append(sorted(by_sum.items()))
    delta = Fraction(1, steps)
    states, state, time = [start], start, cycle + delta
    while len(states) < steps:
        row = thresholds[state]
        target = time_to_rand(time) * row[-1][0]
        state = next((index for total, index in row if total >= target), 0)
        states.append(state)
        time += delta
    return states
