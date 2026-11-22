"""
Insights (BUILD_PROMPT §4.3): every number is computed here from the aggregates; nothing on the
Insights page is written by hand. Valid buckets only (at least 75% of expected readings), with
flagged values left out (the dashboard's default).

Sites are compared ON THE SAME DAYS (or hours): sensors have gaps in different seasons, so a
plain average would rank a sensor that missed the winter as "hot" (DECISIONS.md D-034).

The pure functions take plain Python data so the unit tests can feed known answers;
`build_insights` loads the data with fixed, parameterised queries and assembles the page.
"""
from __future__ import annotations

import time as _time
from collections import defaultdict
from datetime import date
from typing import Any

from ..db import Transaction
from ..variables import LAND_USES, VARIABLES
from . import data, stats

MIN_DAYS_TO_RANK = 30            # matched days a site needs before it is ranked
MIN_HOT_DAYS_TO_RANK = 5         # hot days a site must have reported before its hot-day share is ranked
MIN_MONTHS_FOR_TREND = 4
AFTERNOON_HOURS = range(12, 18)  # 12:00-18:00 local time
INSIGHT_VARIABLES = ("temperature_c", "pm25")
CACHE_SECONDS = 600
_cache: dict[tuple, tuple[float, dict[str, Any]]] = {}


def _r(value: float | None, places: int = 2) -> float | None:
    return None if value is None else round(value, places)


# --------------------------------------------------------------------------- pure functions
def valid_means(buckets: dict[str, dict[str, Any]]) -> dict[str, tuple[float, int]]:
    """bucket -> (mean, n) for valid buckets with data."""
    return {b: (float(r["mean"]), int(r["n"])) for b, r in buckets.items()
            if r["is_valid"] and r["n"] and r["mean"] is not None}


def versus_others(daily: dict[int, dict[str, float]], sensor_id: int) -> dict[str, Any]:
    """Mean over days of (site daily value - average of the OTHER sites that day), with a 95%
    interval over days. Only days on which at least one other site reported count."""
    diffs = []
    for day, value in daily.get(sensor_id, {}).items():
        others = [d[day] for sid, d in daily.items() if sid != sensor_id and day in d]
        if others:
            diffs.append(value - sum(others) / len(others))
    m, lo, hi = stats.mean_ci(diffs)
    return {"difference": _r(m), "low": _r(lo), "high": _r(hi), "days": len(diffs),
            "direction": stats.direction(lo, hi)}


def hot_days(daily_max: dict[int, dict[str, float]], threshold: float) -> set[str]:
    """Days on which the hottest valid daily maximum in the network reached the threshold."""
    peak: dict[str, float] = {}
    for days in daily_max.values():
        for d, v in days.items():
            peak[d] = max(peak.get(d, v), v)
    return {d for d, v in peak.items() if v >= threshold}


def hot_day_share(daily_max: dict[int, dict[str, float]], sensor_id: int, hot: set[str],
                  threshold: float) -> dict[str, Any]:
    """Of the network's hot days on which this site reported, on how many it also reached the threshold."""
    seen = [d for d in hot if d in daily_max.get(sensor_id, {})]
    hits = sum(1 for d in seen if daily_max[sensor_id][d] >= threshold)
    return {"hot_days_reported": len(seen), "hot_days_reached": hits,
            "share_pct": _r(100 * hits / len(seen), 1) if seen else None}


def trend_points(monthly: dict[int, dict[str, tuple[float, int]]], sensor_id: int) -> dict[str, Any]:
    """Slope (per month) of a sensor's valid monthly means, and of its difference from the
    average of the OTHER sensors in the same months (removes the shared seasonal cycle)."""
    own = monthly.get(sensor_id, {})
    months = sorted(own)
    if not months:
        return {"months": 0, "absolute": None, "relative": None}
    first = date.fromisoformat(months[0] + "-01")

    def index(m: str) -> int:
        d = date.fromisoformat(m + "-01")
        return (d.year - first.year) * 12 + d.month - first.month

    absolute = stats.linear_trend([index(m) for m in months], [own[m][0] for m in months])
    rel_x, rel_y = [], []
    for m in months:
        others = [v[m][0] for sid, v in monthly.items() if sid != sensor_id and m in v]
        if others:
            rel_x.append(index(m))
            rel_y.append(own[m][0] - sum(others) / len(others))
    relative = stats.linear_trend(rel_x, rel_y)

    def pack(t: dict[str, Any]) -> dict[str, Any] | None:
        if t["n"] < MIN_MONTHS_FOR_TREND or t["slope"] is None:
            return None
        return {"slope_per_month": _r(t["slope"], 3), "low": _r(t["low"], 3), "high": _r(t["high"], 3),
                "months": t["n"], "direction": stats.direction(t["low"], t["high"])}

    return {"months": len(months), "absolute": pack(absolute), "relative": pack(relative)}


def green_infrastructure(hourly: dict[int, dict[str, float]], park_ids: set[int], other_ids: set[int],
                         hot: set[str]) -> dict[str, Any]:
    """Park minus non-park temperature on MATCHED hours (both groups have valid data that hour).
    The interval is over days (one mean difference per day), because hours within a day are not
    independent. Hot afternoons: 12:00-18:00 on hot days."""
    by_hour: dict[str, float] = {}
    for bucket in {b for sid in park_ids | other_ids for b in hourly.get(sid, {})}:
        park = [hourly[s][bucket] for s in park_ids if bucket in hourly.get(s, {})]
        other = [hourly[s][bucket] for s in other_ids if bucket in hourly.get(s, {})]
        if park and other:
            by_hour[bucket] = sum(park) / len(park) - sum(other) / len(other)

    def summarise(buckets: list[str]) -> dict[str, Any]:
        per_day: dict[str, list[float]] = defaultdict(list)
        for b in buckets:
            per_day[b[:10]].append(by_hour[b])
        m, lo, hi = stats.mean_ci([sum(v) / len(v) for v in per_day.values()])
        return {"difference_c": _r(m), "low": _r(lo), "high": _r(hi), "hours": len(buckets),
                "days": len(per_day), "direction": stats.direction(lo, hi)}

    all_hours = sorted(by_hour)
    afternoons = [b for b in all_hours if b[:10] in hot and int(b[11:13]) in AFTERNOON_HOURS]
    return {"all_hours": summarise(all_hours), "hot_afternoons": summarise(afternoons)}


def diurnal_profile(hourly: dict[str, tuple[float, int]]) -> list[float | None]:
    """Reading-count-weighted mean for each hour of day 0-23 from valid hourly buckets."""
    sums = [[0.0, 0] for _ in range(24)]
    for bucket, (m, n) in hourly.items():
        h = int(bucket[11:13])
        sums[h][0] += m * n
        sums[h][1] += n
    return [_r(s / n) if n else None for s, n in sums]


def rank(items: list[dict[str, Any]], key: str, enough: str, minimum: int) -> list[str]:
    """Sensor codes, highest items[key] first; sites with too little data (items[enough] below
    `minimum`) are left unranked. Writes the position into items[key + '_rank']."""
    ranked = sorted((i for i in items if i.get(key) is not None and (i.get(enough) or 0) >= minimum),
                    key=lambda i: -i[key])
    for pos, item in enumerate(ranked, 1):
        item[f"{key}_rank"] = pos
    return [i["sensor_code"] for i in ranked]


# --------------------------------------------------------------------------- loading
def _thresholds(tx: Transaction) -> dict[str, dict[str, Any] | None]:
    rows = tx.fetch_all(data.SQL_THRESHOLDS)
    hot = sorted((t for t in rows if t["variable"] == "temperature_c" and t["period"] == "day_max"),
                 key=lambda t: t["value"])
    pm = sorted((t for t in rows if t["variable"] == "pm25" and t["period"] == "day"), key=lambda t: t["value"])
    return {"hot_day": hot[0] if hot else None, "pm25_day": pm[0] if pm else None}


def data_version(tx: Transaction) -> tuple:
    """Changes whenever readings, sensors or thresholds change: part of the cache key."""
    r = tx.fetch_one("SELECT MAX(last_reading_utc) AS last, COUNT(*) AS n FROM sensors")
    t = tx.fetch_one("SELECT MAX(updated_at) AS t, SUM(value) AS v FROM thresholds")
    runs = tx.fetch_one("SELECT MAX(run_id) AS run FROM ingestion_runs")
    rows = tx.fetch_all("SELECT sensor_id, land_use, status, sensitive_receptor, location_verified "
                        "FROM sensors ORDER BY sensor_id")
    return (str(r["last"]), r["n"], str(t["t"]), t["v"], runs["run"], tuple(tuple(x.values()) for x in rows))


def build_insights(tx: Transaction, start: date, end: date) -> dict[str, Any]:
    """Everything the Insights page shows, for one date range (cached per data version)."""
    key = (start, end, data_version(tx))
    hit = _cache.get(key)
    if hit and _time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    result = compute(tx, start, end)
    _cache.clear()          # one entry is enough: the page asks for one range at a time
    _cache[key] = (_time.monotonic(), result)
    return result


def _site(sid: int, s: dict, temp: dict, pm: dict, daily_max: dict, hot: set[str], hot_threshold: float | None,
          pm_standard: float | None, days_in_range: int) -> dict[str, Any] | None:
    t_days, p_days = temp.get(sid, {}), pm.get(sid, {})
    if not t_days and not p_days:
        return None
    t_vs = versus_others(temp, sid) if t_days else None
    p_vs = versus_others(pm, sid) if p_days else None
    share = hot_day_share(daily_max, sid, hot, hot_threshold) if t_days and hot_threshold is not None else None
    pm_exceed = sum(1 for m in p_days.values() if pm_standard is not None and m > pm_standard)
    return {
        "sensor_id": sid, "sensor_code": s["sensor_code"], "sensor_name": s["sensor_name"],
        "land_use": s["land_use"], "sensitive_receptor": bool(s["sensitive_receptor"]),
        "location_verified": bool(s["location_verified"]), "status": s["status"], "days_in_range": days_in_range,
        "temperature_days": len(t_days),
        "mean_temperature_c": _r(stats.mean(list(t_days.values()))) if t_days else None,
        "temperature_vs_others": t_vs,
        "temperature_vs_others_c": t_vs["difference"] if t_vs else None,
        "matched_temperature_days": t_vs["days"] if t_vs else 0,
        "hot_days": sum(1 for v in daily_max.get(sid, {}).values() if hot_threshold is not None and v >= hot_threshold)
        if t_days else None,
        "hot_day_share": share,
        "hot_day_share_pct": share["share_pct"] if share else None,
        "hot_days_reported": share["hot_days_reported"] if share else 0,
        "pm25_days": len(p_days),
        "mean_pm25": _r(stats.mean(list(p_days.values()))) if p_days else None,
        "pm25_vs_others": p_vs,
        "pm25_vs_others_ugm3": p_vs["difference"] if p_vs else None,
        "matched_pm25_days": p_vs["days"] if p_vs else 0,
        "pm25_exceedance_days": pm_exceed if p_days else None,
        "pm25_exceedances_per_100": _r(100 * pm_exceed / len(p_days), 1) if p_days else None,
    }


def compute(tx: Transaction, start: date, end: date) -> dict[str, Any]:
    sensors = {s["sensor_id"]: s for s in tx.fetch_all(data.SQL_SENSORS)}
    measures = {v: {s["sensor_id"] for s in data.selected_sensors(tx, v, [], [])} for v in INSIGHT_VARIABLES}
    lo, hi = start.isoformat(), end.isoformat()
    daily = {v: data._aggregate_points(tx, "day", v, lo, hi, True) for v in INSIGHT_VARIABLES}
    monthly = {v: data._aggregate_points(tx, "month", v, lo[:7], hi[:7], True) for v in INSIGHT_VARIABLES}
    hourly_t = data._aggregate_points(tx, "hour", "temperature_c", f"{lo} 00:00", f"{hi} 23:00", True)
    hourly_pm = data._aggregate_points(tx, "hour", "pm25", f"{lo} 00:00", f"{hi} 23:00", True)
    thresholds = _thresholds(tx)
    days_in_range = (end - start).days + 1
    hot_threshold = float(thresholds["hot_day"]["value"]) if thresholds["hot_day"] else None
    pm_standard = float(thresholds["pm25_day"]["value"]) if thresholds["pm25_day"] else None

    # ---- disparities (aim 2) and equity (aim 5): compared on the same days
    temp = {sid: {d: m for d, (m, _) in valid_means(b).items()} for sid, b in daily["temperature_c"].items()}
    pm = {sid: {d: m for d, (m, _) in valid_means(b).items()} for sid, b in daily["pm25"].items()}
    daily_max = {sid: {d: float(r["max"]) for d, r in b.items() if r["is_valid"] and r["max"] is not None}
                 for sid, b in daily["temperature_c"].items()}
    hot = hot_days(daily_max, hot_threshold) if hot_threshold is not None else set()
    sites = [x for sid, s in sorted(sensors.items(), key=lambda kv: kv[1]["sensor_code"])
             if (x := _site(sid, s, temp, pm, daily_max, hot, hot_threshold, pm_standard, days_in_range))]
    rankings = {
        "temperature": rank(sites, "temperature_vs_others_c", "matched_temperature_days", MIN_DAYS_TO_RANK),
        "hot_days": rank(sites, "hot_day_share_pct", "hot_days_reported", MIN_HOT_DAYS_TO_RANK),
        "pm25": rank(sites, "pm25_vs_others_ugm3", "matched_pm25_days", MIN_DAYS_TO_RANK),
        "pm25_exceedances": rank(sites, "pm25_exceedances_per_100", "pm25_days", MIN_DAYS_TO_RANK),
    }
    by_land_use = []
    for lu in LAND_USES:
        group = [s for s in sites if s["land_use"] == lu]
        if group:
            def avg(key: str, g: list = group, places: int = 2) -> float | None:
                return _r(stats.mean([s[key] for s in g if s[key] is not None]), places)

            by_land_use.append({"land_use": lu, "sensors": [s["sensor_code"] for s in group],
                                "temperature_vs_others_c": avg("temperature_vs_others_c"),
                                "hot_day_share_pct": avg("hot_day_share_pct", places=1),
                                "pm25_vs_others_ugm3": avg("pm25_vs_others_ugm3")})
    equity = [equity_entry(s, rankings) for s in sites if s["sensitive_receptor"]]

    # ---- trends (aim 1)
    trends = {}
    for v in INSIGHT_VARIABLES:
        valid_monthly = {sid: valid_means(b) for sid, b in monthly[v].items() if sid in measures[v]}
        trends[v] = [{"sensor_code": sensors[sid]["sensor_code"], "land_use": sensors[sid]["land_use"],
                      "unit": VARIABLES[v]["unit"],
                      "monthly": [{"month": m, "mean": _r(mv[0])} for m, mv in sorted(valid_monthly[sid].items())],
                      **trend_points(valid_monthly, sid)}
                     for sid in sorted(valid_monthly, key=lambda i: sensors[i]["sensor_code"])]
    months_covered = len({m for b in monthly["temperature_c"].values() for m in b})

    # ---- seasonal and daily patterns (aim 3)
    seasonal = {v: [{"sensor_code": sensors[sid]["sensor_code"],
                     "seasons": [{"season": p["t"], "mean": p["mean"], "valid": p["valid"]}
                                 for p in data._season_points(daily[v].get(sid, {}), start, end)]}
                    for sid in sorted(daily[v], key=lambda i: sensors[i]["sensor_code"])] for v in INSIGHT_VARIABLES}
    diurnal = {v: [{"sensor_code": sensors[sid]["sensor_code"], "land_use": sensors[sid]["land_use"],
                    "hours": diurnal_profile(valid_means(b))}
                   for sid, b in sorted(h.items(), key=lambda kv: sensors[kv[0]]["sensor_code"]) if valid_means(b)]
               for v, h in (("temperature_c", hourly_t), ("pm25", hourly_pm))}

    # ---- green infrastructure (aim 4)
    hourly_valid = {sid: {b: m for b, (m, _) in valid_means(bk).items()} for sid, bk in hourly_t.items()}
    park = {sid for sid in hourly_valid if sensors[sid]["land_use"] == "Parkland"}
    other = {sid for sid in hourly_valid if sensors[sid]["land_use"] != "Parkland"}
    green = green_infrastructure(hourly_valid, park, other, hot)
    green.update({
        "park_sensors": sorted(sensors[s]["sensor_code"] for s in park),
        "other_sensors": sorted(sensors[s]["sensor_code"] for s in other),
        "hot_day_threshold_c": hot_threshold, "hot_days": len(hot),
        "park_sensor_valid_hours": {sensors[s]["sensor_code"]: len(hourly_valid[s]) for s in
                                    sorted(park, key=lambda i: sensors[i]["sensor_code"])},
        "hours_in_range": days_in_range * 24,
    })
    green["caveats"] = green_caveats(green, sensors, park)

    result = {
        "start": lo, "end": hi, "days": days_in_range, "months": months_covered,
        "thresholds": {"hot_day_c": hot_threshold, "pm25_standard": pm_standard},
        "sites": sites, "rankings": rankings, "by_land_use": by_land_use, "equity": equity,
        "trends": trends, "seasonal": seasonal, "diurnal": diurnal, "green_infrastructure": green,
        "network": network_gaps(tx, sensors, sites, daily["temperature_c"], days_in_range),
    }
    result["recommendations"] = recommendations(result)
    return result


def equity_entry(s: dict[str, Any], rankings: dict[str, list[str]]) -> dict[str, Any]:
    """A sensitive site against the others, on the same days. 'more_exposed' only when the
    whole 95% interval is above zero."""
    comparison: dict[str, Any] = {}
    if s["temperature_vs_others"]:
        comparison["temperature"] = {**s["temperature_vs_others"], "unit": "°C", "label": "Temperature",
                                     "rank": s.get("temperature_vs_others_c_rank"),
                                     "ranked_sites": len(rankings["temperature"])}
    if s["pm25_vs_others"]:
        comparison["pm25"] = {**s["pm25_vs_others"], "unit": "µg/m³", "label": "PM2.5",
                              "rank": s.get("pm25_vs_others_ugm3_rank"), "ranked_sites": len(rankings["pm25"])}
    if s["hot_day_share"] and s["hot_day_share"]["hot_days_reported"]:
        comparison["hot_days"] = {**s["hot_day_share"], "rank": s.get("hot_day_share_pct_rank"),
                                  "ranked_sites": len(rankings["hot_days"])}
    more = [k for k in ("temperature", "pm25") if k in comparison and comparison[k]["direction"] == "rising"]
    return {"sensor_code": s["sensor_code"], "sensor_name": s["sensor_name"], "land_use": s["land_use"],
            "comparison": comparison, "more_exposed": more}


def green_caveats(green: dict[str, Any], sensors: dict[int, dict], park: set[int]) -> list[str]:
    """Plain-English limits, written from the numbers (never fixed text about results)."""
    n_park = len(park)
    out = [f"Only {n_park} park sensor{'s' if n_park != 1 else ''} ({', '.join(green['park_sensors']) or 'none'}) "
           f"and {len(green['other_sensors'])} other sensors: a difference can come from where each sensor is "
           "mounted (height, shade, nearby surfaces), not only from the park."]
    hours = green["park_sensor_valid_hours"]
    shares = {code: 100 * n / green["hours_in_range"] for code, n in hours.items()}
    if any(s < 90 for s in shares.values()):
        listed = ", ".join(f"{code} {s:.0f}%" for code, s in shares.items())
        out.append(f"Park sensors have valid data for only part of the period ({listed} of hours), so the "
                   "comparison uses only the hours when both groups reported.")
    ha = green["hot_afternoons"]
    out.append(f"Hot afternoons: {ha['hours']} matched hours on {ha['days']} hot days (days reaching "
               f"{green['hot_day_threshold_c']} °C)." + (" A small sample: treat this figure as indicative."
                                                         if ha["days"] < 30 else ""))
    if any(not sensors[s]["location_verified"] for s in park):
        out.append("Park sensor locations are approximate and not yet verified with the council.")
    return out


def network_gaps(tx: Transaction, sensors: dict[int, dict], sites: list[dict], daily_temp: dict,
                 days_in_range: int) -> dict[str, Any]:
    """Low completeness, variables not fitted, land uses with no or one sensor."""
    low = []
    for s in sites:
        days = daily_temp.get(s["sensor_id"], {})
        comp = sum(float(r["completeness_pct"] or 0) for r in days.values()) / days_in_range if days else 0.0
        if comp < data.MIN_COMPLETENESS_PCT:
            low.append({"sensor_code": s["sensor_code"], "completeness_pct": _r(comp, 1)})
    not_fitted = [{"sensor_code": sensors[r["sensor_id"]]["sensor_code"], "variable": r["variable"],
                   "label": VARIABLES.get(r["variable"], {}).get("label", r["variable"])}
                  for r in tx.fetch_all("SELECT DISTINCT sensor_id, variable FROM error_log "
                                        "WHERE error_type = 'not_fitted' AND sensor_id IS NOT NULL")
                  if r["sensor_id"] in sensors]
    counts = {lu: sum(1 for s in sensors.values() if s["land_use"] == lu and s["status"] == "Active")
              for lu in LAND_USES}
    return {"low_completeness": low,
            "not_fitted": sorted(not_fitted, key=lambda x: (x["sensor_code"], x["variable"])),
            "sensors_per_land_use": counts,
            "uncovered_land_uses": [lu for lu, n in counts.items() if n == 0],
            "single_sensor_land_uses": [lu for lu, n in counts.items() if n == 1]}


def _ci(x: dict[str, Any], unit: str) -> str:
    return f"95% CI {x['low']:+} to {x['high']:+} {unit}; {x['days']} days" if x.get("low") is not None \
        else f"{x.get('days', 0)} days"


def recommendations(r: dict[str, Any]) -> list[dict[str, Any]]:
    """Rules -> recommendations, each with the evidence numbers it rests on."""
    out: list[dict[str, Any]] = []
    sites = {s["sensor_code"]: s for s in r["sites"]}
    g = r["green_infrastructure"]
    hottest = sites[r["rankings"]["temperature"][0]] if r["rankings"]["temperature"] else None
    hottest_is_warm = hottest and hottest["temperature_vs_others"]["direction"] == "rising"

    ha, al = g["hot_afternoons"], g["all_hours"]
    green_evidence = [
        {"label": "Parks minus other sites, all matched hours", "value": al["difference_c"], "unit": "°C",
         "detail": f"95% CI {al['low']} to {al['high']}; {al['hours']} hours on {al['days']} days"},
        {"label": "Parks minus other sites, hot afternoons", "value": ha["difference_c"], "unit": "°C",
         "detail": f"95% CI {ha['low']} to {ha['high']}; {ha['hours']} hours on {ha['days']} hot days"}]
    if ha["direction"] == "falling" and hottest:
        out.append({"id": "canopy", "priority": "high", "title": "Extend tree canopy near the hottest site",
                    "text": f"Parkland sites were on average {abs(ha['difference_c']):.1f} °C cooler than other sites "
                            f"during hot afternoons. Prioritise canopy and shade near {hottest['sensor_name']} "
                            f"({hottest['sensor_code']}).", "evidence": green_evidence})
    elif ha["difference_c"] is not None:
        overall = ("Over all matched hours the parks were slightly cooler"
                   if al["direction"] == "falling" else
                   "Over all matched hours the parks were slightly warmer" if al["direction"] == "rising" else
                   "Over all matched hours there was no clear difference")
        out.append({"id": "canopy-evidence", "priority": "medium",
                    "title": "More park data is needed to measure the cooling effect on hot days",
                    "text": f"{overall} ({al['difference_c']:+.2f} °C), but on hot afternoons the difference was "
                            "not distinguishable from zero with the data available. Improve the park sensors' "
                            "reliability before relying on this result.", "evidence": green_evidence})
    if hottest_is_warm:
        tv = hottest["temperature_vs_others"]
        out.append({"id": "heat-hotspot", "priority": "high", "title": f"Heat hotspot: {hottest['sensor_name']}",
                    "text": f"{hottest['sensor_name']} ({hottest['land_use']}) was the warmest site compared with "
                            "the others on the same days. Target heat-relief measures (shade, cool surfaces, "
                            "drinking water) here first.",
                    "evidence": [{"label": "Warmer than the other sites on the same days", "value": tv["difference"],
                                  "unit": "°C", "detail": _ci(tv, "°C")}]})
    worst = sites[r["rankings"]["pm25"][0]] if r["rankings"]["pm25"] else None
    if worst:
        pv = worst["pm25_vs_others"]
        out.append({"id": "air-quality", "priority": "high" if worst["pm25_exceedance_days"] else "medium",
                    "title": f"Air quality focus: {worst['sensor_name']}",
                    "text": f"{worst['sensor_name']} ({worst['land_use']}) had the highest PM2.5 compared with the "
                            "other sites on the same days. "
                            + ("It exceeded the 24-hour standard on some days: investigate local sources (traffic, "
                               "industry, wood smoke) and consider a targeted monitoring campaign."
                               if worst["pm25_exceedance_days"] else "It stayed within the 24-hour standard."),
                    "evidence": [{"label": "PM2.5 above the other sites on the same days", "value": pv["difference"],
                                  "unit": "µg/m³", "detail": _ci(pv, "µg/m³")},
                                 {"label": "Days over the 24-hour standard", "value": worst["pm25_exceedance_days"],
                                  "unit": "days", "detail": f"of {worst['pm25_days']} valid days; standard "
                                                            f"{r['thresholds']['pm25_standard']} µg/m³"}]})
    for e in r["equity"]:
        c = e["comparison"]
        if e["more_exposed"]:
            out.append({"id": f"receptor-{e['sensor_code']}", "priority": "high",
                        "title": f"Protect a sensitive site: {e['sensor_name']}",
                        "text": f"{e['sensor_name']} is a sensitive site and was more exposed than the other sites on "
                                "the same days. Consider shade, cooling and indoor-air plans for hot or smoky days.",
                        "evidence": [{"label": f"{c[k]['label']} above the other sites", "value": c[k]["difference"],
                                      "unit": c[k]["unit"], "detail": _ci(c[k], c[k]["unit"])}
                                     for k in e["more_exposed"]]})
        elif c:
            out.append({"id": f"receptor-{e['sensor_code']}", "priority": "medium",
                        "title": f"Keep monitoring a sensitive site: {e['sensor_name']}",
                        "text": f"{e['sensor_name']} was not measurably more exposed than the other sites on the same "
                                "days. Keep its sensor running: as a sensitive site it is where a change matters most.",
                        "evidence": [{"label": f"{c[k]['label']} versus the other sites", "value": c[k]["difference"],
                                      "unit": c[k]["unit"], "detail": _ci(c[k], c[k]["unit"])}
                                     for k in ("temperature", "pm25") if k in c]})
    net = r["network"]
    if net["low_completeness"]:
        out.append({"id": "maintenance", "priority": "medium", "title": "Fix sensors with gaps in their data",
                    "text": "These sensors sent fewer than 75% of their expected readings, so their figures and the "
                            "park comparison rest on partial data. Check power, connectivity and mounting.",
                    "evidence": [{"label": x["sensor_code"], "value": x["completeness_pct"], "unit": "%",
                                  "detail": "average daily completeness (temperature)"}
                                 for x in net["low_completeness"]]})
    gaps = net["uncovered_land_uses"] + net["single_sensor_land_uses"]
    if gaps:
        out.append({"id": "placement", "priority": "medium", "title": "Where to add sensors",
                    "text": "A land use with no sensor cannot be assessed, and one with a single sensor cannot "
                            "separate that site from the land use. Add sensors in: " + ", ".join(gaps) + ".",
                    "evidence": [{"label": lu, "value": net["sensors_per_land_use"][lu],
                                  "unit": "active sensor" if net["sensors_per_land_use"][lu] == 1 else "active sensors",
                                  "detail": "none: not assessed" if net["sensors_per_land_use"][lu] == 0
                                  else "one: site and land use cannot be separated"} for lu in gaps]})
    return out
