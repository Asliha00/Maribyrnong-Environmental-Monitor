"""Insights formulas (BUILD_PROMPT §4.3) on synthetic data with known answers."""
import pytest

from backend.app.services import analysis


def days(start_month: int, n: int, value: float, year: int = 2025) -> dict[str, float]:
    return {f"{year}-{start_month:02d}-{d:02d}": value for d in range(1, n + 1)}


# ---------- comparing sites on the same days ----------
def test_versus_others_is_not_fooled_by_a_seasonal_gap():
    """Site A reported only in summer. A plain average would call it 10 °C hotter than B and C,
    which report all year; on the same days it is exactly 1 °C warmer."""
    summer, winter = days(1, 28, 30.0), days(7, 28, 10.0)
    b = {**summer, **winter}
    c = {**summer, **winter}
    a = {d: 31.0 for d in summer}
    daily = {1: a, 2: b, 3: c}
    vs = analysis.versus_others(daily, 1)
    assert vs["difference"] == 1.0 and vs["days"] == 28 and vs["direction"] == "rising"
    plain_gap = sum(a.values()) / len(a) - sum(b.values()) / len(b)
    assert plain_gap == 11.0                            # what the naive comparison would have said
    # B: 0.5 below mean(A, C) on the 28 summer days, level with C on the 28 winter days
    assert analysis.versus_others(daily, 2)["difference"] == -0.25


def test_versus_others_needs_another_site_that_day():
    assert analysis.versus_others({1: days(1, 5, 20.0)}, 1)["days"] == 0


def test_hot_days_and_share():
    maxes = {1: {"2025-01-01": 36.0, "2025-01-02": 30.0, "2025-01-03": 37.0},
             2: {"2025-01-01": 34.0, "2025-01-03": 35.5}}
    hot = analysis.hot_days(maxes, 35.0)
    assert hot == {"2025-01-01", "2025-01-03"}
    assert analysis.hot_day_share(maxes, 2, hot, 35.0) == {"hot_days_reported": 2, "hot_days_reached": 1,
                                                          "share_pct": 50.0}


def test_rank_leaves_out_sites_with_too_little_data():
    items = [{"sensor_code": "A", "x": 2.0, "n": 40}, {"sensor_code": "B", "x": 5.0, "n": 10},
             {"sensor_code": "C", "x": 1.0, "n": 50}]
    assert analysis.rank(items, "x", "n", 30) == ["A", "C"]
    assert items[0]["x_rank"] == 1 and "x_rank" not in items[1]


# ---------- trends ----------
def test_relative_trend_removes_the_shared_season():
    season = [10, 12, 15, 18, 22, 25, 24, 20, 16, 12, 10, 9]
    months = [f"2025-{m:02d}" for m in range(1, 13)]
    monthly = {1: {m: (season[i] + 0.1 * i, 100) for i, m in enumerate(months)},     # drifts +0.1/month
               2: {m: (season[i], 100) for i, m in enumerate(months)},
               3: {m: (season[i] - 1, 100) for i, m in enumerate(months)}}
    t = analysis.trend_points(monthly, 1)
    assert t["months"] == 12
    assert t["relative"]["slope_per_month"] == pytest.approx(0.1, abs=1e-3)
    assert t["relative"]["direction"] == "rising"
    assert t["absolute"]["direction"] == "no clear change"     # the season swamps the drift


def test_trend_needs_enough_months():
    monthly = {1: {"2025-01": (10, 1), "2025-02": (11, 1), "2025-03": (12, 1)}, 2: {}}
    assert analysis.trend_points(monthly, 1)["absolute"] is None


# ---------- green infrastructure ----------
def test_green_infrastructure_on_matched_hours_and_hot_afternoons():
    hourly = {1: {}, 2: {}, 3: {}}
    for d in ("2025-01-10", "2025-01-11", "2025-07-01"):
        for h in range(24):
            b = f"{d} {h:02d}:00"
            hourly[2][b] = 25.0                   # non-park
            hourly[3][b] = 27.0                   # non-park
            if d != "2025-07-01" or h < 6:        # the park misses most of one day
                hourly[1][b] = 24.0 if 12 <= h < 18 and d == "2025-01-10" else 25.5
    g = analysis.green_infrastructure(hourly, {1}, {2, 3}, hot={"2025-01-10"})
    assert g["all_hours"]["hours"] == 24 + 24 + 6 and g["all_hours"]["days"] == 3
    ha = g["hot_afternoons"]
    assert ha["hours"] == 6 and ha["days"] == 1 and ha["difference_c"] == -2.0
    assert ha["low"] is None                      # one day: no interval can be computed


def test_green_infrastructure_without_park_data():
    g = analysis.green_infrastructure({2: {"2025-01-01 13:00": 25.0}}, set(), {2}, hot=set())
    assert g["all_hours"]["hours"] == 0 and g["all_hours"]["difference_c"] is None


def test_diurnal_profile_weights_by_readings():
    profile = analysis.diurnal_profile({"2025-01-01 14:00": (20.0, 6), "2025-01-02 14:00": (26.0, 2),
                                        "2025-01-01 03:00": (10.0, 6)})
    assert profile[14] == 21.5 and profile[3] == 10.0 and profile[0] is None and len(profile) == 24


# ---------- recommendations are rules over numbers ----------
def _result(green_dir="falling", receptor_dir="rising"):
    site = {"sensor_code": "S1", "sensor_name": "Site One", "land_use": "Residential", "pm25_days": 300,
            "pm25_exceedance_days": 2, "temperature_vs_others": {"difference": 0.5, "low": 0.3, "high": 0.7,
                                                                  "days": 300, "direction": "rising"},
            "pm25_vs_others": {"difference": 1.0, "low": 0.5, "high": 1.5, "days": 300, "direction": "rising"}}
    gi = {"difference_c": -1.2, "low": -2.0, "high": -0.4, "hours": 80, "days": 12, "direction": green_dir}
    return {"sites": [site], "rankings": {"temperature": ["S1"], "pm25": ["S1"]},
            "thresholds": {"pm25_standard": 25.0},
            "green_infrastructure": {"hot_afternoons": gi, "all_hours": {**gi, "hours": 4000, "days": 300}},
            "equity": [{"sensor_code": "S1", "sensor_name": "Site One",
                        "comparison": {"temperature": {**site["temperature_vs_others"], "unit": "°C",
                                                       "label": "Temperature", "direction": receptor_dir}},
                        "more_exposed": ["temperature"] if receptor_dir == "rising" else []}],
            "network": {"low_completeness": [], "uncovered_land_uses": ["Commercial"],
                        "single_sensor_land_uses": [], "sensors_per_land_use": {"Commercial": 0}}}


def test_recommendations_carry_their_evidence():
    recs = {r["id"]: r for r in analysis.recommendations(_result())}
    assert "1.2 °C cooler" in recs["canopy"]["text"] and "Site One" in recs["canopy"]["text"]
    assert recs["canopy"]["evidence"][1]["value"] == -1.2
    assert recs["heat-hotspot"]["evidence"][0]["value"] == 0.5
    assert recs["receptor-S1"]["priority"] == "high"
    assert "Commercial" in recs["placement"]["text"]
    assert all(r["evidence"] for r in recs.values())


def test_no_cooling_claim_without_a_clear_difference():
    recs = {r["id"]: r for r in analysis.recommendations(_result(green_dir="no clear change",
                                                                 receptor_dir="no clear change"))}
    assert "canopy" not in recs and "canopy-evidence" in recs
    assert recs["receptor-S1"]["priority"] == "medium"
    assert "not measurably more exposed" in recs["receptor-S1"]["text"]
