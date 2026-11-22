"""Formulas behind the Insights numbers, checked against hand-worked examples."""
import math

import pytest

from backend.app.services import stats


def test_mean_ci_matches_a_hand_calculation():
    # values 2, 4, 4, 4, 5, 5, 7, 9: mean 5, sample sd 2.138, t(7) = 2.365
    m, lo, hi = stats.mean_ci([2, 4, 4, 4, 5, 5, 7, 9])
    half = 2.365 * 2.13809 / math.sqrt(8)
    assert m == 5 and lo == pytest.approx(5 - half, abs=1e-3) and hi == pytest.approx(5 + half, abs=1e-3)


def test_mean_ci_small_samples():
    assert stats.mean_ci([]) == (None, None, None)
    assert stats.mean_ci([3.0]) == (3.0, None, None)


def test_linear_trend_recovers_an_exact_line():
    t = stats.linear_trend([0, 1, 2, 3, 4], [1, 3, 5, 7, 9])
    assert t["slope"] == pytest.approx(2) and t["low"] == pytest.approx(2) and t["high"] == pytest.approx(2)


def test_linear_trend_interval_contains_zero_for_noise():
    t = stats.linear_trend(list(range(10)), [5, 6, 4, 5, 6, 4, 5, 6, 4, 5])
    assert t["low"] < 0 < t["high"] and stats.direction(t["low"], t["high"]) == "no clear change"


def test_linear_trend_needs_three_points():
    assert stats.linear_trend([0, 1], [1, 2])["slope"] is None


@pytest.mark.parametrize(("low", "high", "word"), [(0.1, 0.5, "rising"), (-0.5, -0.1, "falling"),
                                                    (-0.1, 0.1, "no clear change"), (None, 1, "not enough data")])
def test_direction(low, high, word):
    assert stats.direction(low, high) == word


def test_t_table_edges():
    assert stats.t95(1) == 12.706 and stats.t95(100) == 1.96 and stats.t95(0) == math.inf
