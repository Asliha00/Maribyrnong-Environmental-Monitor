"""
Small, dependency-free statistics for the Insights page (BUILD_PROMPT §4.3).

Kept separate and pure so each formula can be unit-tested against hand-worked examples and
quoted in the technical document.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

# Two-sided 95% critical values of Student's t by degrees of freedom (standard tables);
# above 30 the normal value 1.96 is close enough for this report.
T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
       11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093,
       20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048,
       29: 2.045, 30: 2.042}


def t95(df: int) -> float:
    return T95.get(df, 1.96) if df >= 1 else math.inf


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def mean_ci(values: Sequence[float]) -> tuple[float | None, float | None, float | None]:
    """Mean and its 95% confidence interval (t-based). None where it cannot be computed."""
    n = len(values)
    if n == 0:
        return None, None, None
    m = sum(values) / n
    if n < 2:
        return m, None, None
    sd = math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1))
    half = t95(n - 1) * sd / math.sqrt(n)
    return m, m - half, m + half


def linear_trend(x: Sequence[float], y: Sequence[float]) -> dict[str, float | None]:
    """Ordinary least squares y = a + b x. Returns slope b with its 95% CI (t, n-2 df)."""
    n = len(x)
    if n < 3:
        return {"slope": None, "low": None, "high": None, "n": n}
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((xi - mx) ** 2 for xi in x)
    if sxx == 0:
        return {"slope": None, "low": None, "high": None, "n": n}
    slope = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y, strict=True)) / sxx
    intercept = my - slope * mx
    rss = sum((yi - intercept - slope * xi) ** 2 for xi, yi in zip(x, y, strict=True))
    se = math.sqrt(rss / (n - 2) / sxx)
    half = t95(n - 2) * se
    return {"slope": slope, "low": slope - half, "high": slope + half, "n": n}


def direction(low: float | None, high: float | None) -> str:
    """'rising' / 'falling' only when the whole 95% interval is on one side of zero."""
    if low is None or high is None:
        return "not enough data"
    if low > 0:
        return "rising"
    if high < 0:
        return "falling"
    return "no clear change"
