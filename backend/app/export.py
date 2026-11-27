"""Build a self-contained JSON export of a single activity for an AI coach.

Goal: give a coaching agent everything it needs to spot outliers, trends, splits,
and highlights for ONE activity — without pasting thousands of raw GPS points.

The bundle contains:
  * meta: schema version, generation time, a short notes block explaining units
    and which fields are source vs derived (so the agent doesn't misread them).
  * activity: the stored summary (source values, SI units).
  * derived: aggregates computed here from the time-series — HR zone distribution,
    per-kilometre splits, pace/HR drift (aerobic decoupling), elevation profile,
    and simple quality flags. All clearly namespaced under `derived`.
  * series: a DOWNSAMPLED time-series (default ~120 points) so trends are visible
    but the payload stays paste-friendly.

Everything is deterministic and computed from already-stored data; no network.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any

from .api import presenter as pv

SCHEMA_VERSION = "coach-export/1"

# Default HR zone model (percent of max HR). Documented as an assumption: if the
# user has no configured max HR we estimate it, and we say so in the notes.
_ZONE_BOUNDS_PCT = [(0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.01)]
_ZONE_LABELS = ["Z1 recovery", "Z2 aerobic", "Z3 tempo", "Z4 threshold", "Z5 anaerobic"]


def _as_num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _round(v: float | None, d: int = 2) -> float | None:
    return round(v, d) if v is not None else None


def _mean(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _estimate_max_hr(samples: list[sqlite3.Row], summary_max: int | None) -> tuple[int | None, str]:
    """Return (maxHR, source). Prefer the activity's recorded max; otherwise the
    observed max in samples; otherwise None. We never fabricate an age-based number
    silently — if we estimate, the source string says so."""
    observed = max((s["heart_rate_bpm"] for s in samples if s["heart_rate_bpm"] is not None), default=None)
    if summary_max:
        return summary_max, "activity_max_hr"
    if observed:
        return observed, "observed_sample_max"
    return None, "unavailable"


def _sample_gap(samples: list[sqlite3.Row]) -> int:
    offsets = [s["offset_seconds"] for s in samples if s["offset_seconds"] is not None]
    if len(offsets) < 2:
        return 1
    diffs = sorted(offsets[i + 1] - offsets[i] for i in range(len(offsets) - 1))
    return max(1, diffs[len(diffs) // 2])


def _hr_zones(
    samples: list[sqlite3.Row],
    max_hr: int | None,
    zone_floors: list[int] | None = None,
) -> dict[str, Any] | None:
    """Time-in-zone distribution.

    If `zone_floors` (the user's configured Z1..Z5 bpm floors) is provided, we use
    those absolute thresholds — accurate to the athlete. Otherwise we fall back to
    a percent-of-maxHR model and say so via `basis`.
    """
    hrs = [s["heart_rate_bpm"] for s in samples if s["heart_rate_bpm"] is not None]
    if not hrs:
        return None
    gap = _sample_gap(samples)
    seconds = [0, 0, 0, 0, 0]

    if zone_floors and len(zone_floors) == 5 and all(zone_floors):
        floors = zone_floors
        for hr in hrs:
            zi = 0
            for i in range(5):
                if hr >= floors[i]:
                    zi = i
            # below zone1 floor -> still count as Z1 (recovery/warmup)
            seconds[zi] += gap
        basis = "configured_zone_floors_bpm"
        detail: Any = {"floorsBpm": floors}
    elif max_hr:
        for hr in hrs:
            pct = hr / max_hr
            placed = False
            for zi, (lo, hi) in enumerate(_ZONE_BOUNDS_PCT):
                if lo <= pct < hi:
                    seconds[zi] += gap
                    placed = True
                    break
            if not placed and pct >= _ZONE_BOUNDS_PCT[-1][0]:
                seconds[4] += gap
        basis = "percent_of_max_hr_estimate"
        detail = {"maxHrUsed": max_hr}
    else:
        return None

    total = sum(seconds) or 1
    return {
        "basis": basis,
        **detail,
        "zones": [
            {
                "zone": _ZONE_LABELS[i],
                "seconds": seconds[i],
                "percent": _round(100 * seconds[i] / total, 1),
            }
            for i in range(5)
        ],
    }


def _splits(samples: list[sqlite3.Row], split_meters: int = 1000) -> list[dict[str, Any]] | None:
    """Per-split aggregates based on cumulative distance. Each split: duration,
    pace, avg HR, elevation change. Lets the coach see pacing & fade."""
    pts = [
        (s["offset_seconds"], s["distance_meters"], s["heart_rate_bpm"], s["elevation_meters"])
        for s in samples
        if s["distance_meters"] is not None and s["offset_seconds"] is not None
    ]
    if len(pts) < 2 or (pts[-1][1] or 0) < split_meters:
        return None
    splits = []
    next_mark = split_meters
    seg_start_t = pts[0][0]
    seg_hrs: list[float] = []
    seg_elev_start = pts[0][3]
    split_idx = 1
    for _, dist, hr, elev in pts:
        if hr is not None:
            seg_hrs.append(hr)
        if dist is not None and dist >= next_mark:
            # close this split at this point
            seg_end_t = _offset_at(pts, next_mark)
            dur = (seg_end_t - seg_start_t) if seg_end_t is not None else None
            pace = (dur / 60) / (split_meters / 1000) if dur else None
            splits.append(
                {
                    "split": split_idx,
                    "distanceMeters": split_meters,
                    "durationSeconds": dur,
                    "paceMinPerKm": _round(pace, 2),
                    "avgHrBpm": _round(_mean(seg_hrs), 0),
                    "elevationChangeMeters": _round(
                        (elev - seg_elev_start) if (elev is not None and seg_elev_start is not None) else None, 1
                    ),
                }
            )
            split_idx += 1
            next_mark += split_meters
            seg_start_t = seg_end_t if seg_end_t is not None else seg_start_t
            seg_hrs = []
            seg_elev_start = elev
    return splits or None


def _offset_at(pts: list[tuple], target_dist: float) -> int | None:
    """Linear-interpolate the time offset at a cumulative distance."""
    prev = None
    for t, d, _, _ in pts:
        if d is None or t is None:
            continue
        if d >= target_dist:
            if prev is None:
                return t
            pt, pd = prev
            if d == pd:
                return t
            frac = (target_dist - pd) / (d - pd)
            return int(pt + frac * (t - pt))
        prev = (t, d)
    return None


def _decoupling(samples: list[sqlite3.Row]) -> dict[str, Any] | None:
    """Aerobic decoupling: compare HR/pace efficiency first half vs second half.
    A positive value means the athlete 'drifted' (HR rose relative to pace) —
    a classic endurance/fatigue signal. DERIVED estimate.
    """
    pts = [
        (s["offset_seconds"], s["speed_mps"], s["heart_rate_bpm"])
        for s in samples
        if s["speed_mps"] and s["heart_rate_bpm"] and s["offset_seconds"] is not None
    ]
    if len(pts) < 20:
        return None
    mid = len(pts) // 2
    first, second = pts[:mid], pts[mid:]

    def eff(seg):
        spd = _mean([p[1] for p in seg])
        hr = _mean([p[2] for p in seg])
        return (spd / hr) if (spd and hr) else None

    e1, e2 = eff(first), eff(second)
    if not e1 or not e2:
        return None
    pct = (e1 - e2) / e1 * 100
    return {
        "method": "speed_per_hr first-half vs second-half",
        "decouplingPercent": _round(pct, 1),
        "interpretation": (
            "low drift (<5% typical for well-paced aerobic effort)"
            if pct < 5
            else "notable drift (possible fatigue, heat, or overpacing)"
        ),
    }


def _elevation_profile(samples: list[sqlite3.Row]) -> dict[str, Any] | None:
    els = [s["elevation_meters"] for s in samples if s["elevation_meters"] is not None]
    if len(els) < 2:
        return None
    gain = loss = 0.0
    for i in range(1, len(els)):
        d = els[i] - els[i - 1]
        if d > 0:
            gain += d
        else:
            loss += -d
    return {
        "minMeters": _round(min(els), 1),
        "maxMeters": _round(max(els), 1),
        "gainMeters": _round(gain, 0),
        "lossMeters": _round(loss, 0),
    }


def _series_stats(samples: list[sqlite3.Row], field: str) -> dict[str, Any] | None:
    vals = [_as_num(s[field]) for s in samples if s[field] is not None]
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return {
        "min": _round(min(vals), 1),
        "max": _round(max(vals), 1),
        "avg": _round(_mean(vals), 1),
    }


def _downsample(samples: list[sqlite3.Row], target: int = 120) -> list[dict[str, Any]]:
    if not samples:
        return []
    step = max(1, len(samples) // target)
    out = []
    for i in range(0, len(samples), step):
        s = samples[i]
        out.append(
            {
                "t": s["offset_seconds"],
                "hr": s["heart_rate_bpm"],
                "paceMinPerKm": pv.pace_from_speed(_as_num(s["speed_mps"])),
                "elevM": _round(_as_num(s["elevation_meters"]), 1),
                "cad": _round(_as_num(s["cadence"]), 0),
                "pw": _round(_as_num(s["power_watts"]), 0),
            }
        )
    return out


def build_activity_coach_export(
    activity: sqlite3.Row,
    samples: list[sqlite3.Row],
    unit_system: str,
    zone_floors: list[int] | None = None,
) -> dict[str, Any]:
    view = pv.activity_summary_view(activity)
    max_hr, max_hr_src = _estimate_max_hr(samples, view.get("maxHrBpm"))

    derived: dict[str, Any] = {
        "sampleCount": len(samples),
        "hrZones": _hr_zones(samples, max_hr, zone_floors),
        "hrZoneSource": max_hr_src,
        "splitsPerKm": _splits(samples, 1000),
        "aerobicDecoupling": _decoupling(samples),
        "elevationProfile": _elevation_profile(samples),
        "heartRate": _series_stats(samples, "heart_rate_bpm"),
        "cadence": _series_stats(samples, "cadence"),
        "power": _series_stats(samples, "power_watts"),
    }

    has_gps = any(s["latitude"] is not None and s["longitude"] is not None for s in samples)

    return {
        "meta": {
            "schema": SCHEMA_VERSION,
            "generatedAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "unitSystemHint": unit_system,
            "notes": (
                "All source values are in SI units unless the field name says otherwise "
                "(meters, seconds, m/s, bpm). Times are device-local ISO in `startLocalIso`. "
                "Everything under `derived` is computed by the dashboard from the recorded "
                "time-series, not reported by Garmin. HR zones use percent-of-maxHR; "
                "`derived.hrZoneSource` states where maxHR came from. `series` is downsampled "
                "for brevity. Treat missing fields as 'no data' (not zero)."
            ),
            "purpose": "Single-activity summary for review by an AI coaching assistant.",
        },
        "activity": view,
        "derived": derived,
        "capabilities": {
            "gps": has_gps,
            "heartRate": derived["heartRate"] is not None,
            "power": derived["power"] is not None,
            "cadence": derived["cadence"] is not None,
            "splits": derived["splitsPerKm"] is not None,
        },
        "series": {
            "downsampledTo": min(len(samples), 120),
            "fields": (
                "t=offsetSeconds, hr=bpm, paceMinPerKm, elevM, cad, pw=watts. "
                "Note: `cad` from the FIT record is per-leg for running (≈half the "
                "summary's avgRunCadenceSpm); double it for steps-per-minute. "
                "Compare to `activity.avgRunCadenceSpm` for the full-cadence figure."
            ),
            "points": _downsample(samples, 120),
        },
    }


# ===========================================================================
# Today's health snapshot export
# ===========================================================================
#
# A self-contained JSON bundle of the most recent day's health metrics, each
# with a baseline comparison (today vs 7-day and 30-day averages) so an AI coach
# can judge whether today is normal, elevated, or recovering — plus short trend
# arrays for context. All comparison figures are DERIVED here and labelled.

HEALTH_SCHEMA_VERSION = "health-snapshot/1"


def _baseline(today: float | None, history: list[float | None]) -> dict[str, Any] | None:
    """Compare today's value to the mean of `history` (excluding today / nulls)."""
    if today is None:
        return None
    vals = [v for v in history if v is not None]
    if not vals:
        return {"today": _round(today, 1), "avg": None, "delta": None, "vsBaseline": "no_baseline"}
    avg = sum(vals) / len(vals)
    delta = today - avg
    # A simple qualitative flag using a 1-sigma-ish band when we have spread.
    spread = (max(vals) - min(vals)) or 1
    rel = delta / spread
    if rel > 0.4:
        flag = "above_typical"
    elif rel < -0.4:
        flag = "below_typical"
    else:
        flag = "typical"
    return {
        "today": _round(today, 1),
        "avg": _round(avg, 1),
        "delta": _round(delta, 1),
        "n": len(vals),
        "vsBaseline": flag,
    }


def _col(rows: list[sqlite3.Row], key: str) -> list[float | None]:
    out: list[float | None] = []
    for r in rows:
        try:
            out.append(_as_num(r[key]))
        except (IndexError, KeyError):
            out.append(None)
    return out


def build_health_snapshot_export(
    *,
    daily: sqlite3.Row | None,
    sleep: sqlite3.Row | None,
    hrv: sqlite3.Row | None,
    body_battery: list[sqlite3.Row],
    fitness_age: sqlite3.Row | None = None,
    daily_7: list[sqlite3.Row],
    daily_30: list[sqlite3.Row],
    sleep_7: list[sqlite3.Row],
    sleep_30: list[sqlite3.Row],
    hrv_7: list[sqlite3.Row],
    hrv_30: list[sqlite3.Row],
    unit_system: str,
) -> dict[str, Any]:
    from .api import presenter as pv

    calendar_date = daily["calendar_date"] if daily else (
        sleep["calendar_date"] if sleep else (hrv["calendar_date"] if hrv else None)
    )

    # --- today's values (source) ---
    today_rhr = _as_num(daily["resting_hr_bpm"]) if daily else None
    today_steps = _as_num(daily["steps"]) if daily else None
    today_stress = _as_num(daily["avg_stress_level"]) if daily else None
    if today_stress is not None and today_stress < 0:
        today_stress = None  # sentinel: not enough data
    today_sleep_dur = _as_num(sleep["duration_seconds"]) if sleep else None
    today_sleep_score = _as_num(sleep["overall_score_value"]) if sleep else None
    today_hrv = _as_num(hrv["last_night_avg_ms"]) if hrv else None
    bb_latest = body_battery[-1]["body_battery_value"] if body_battery else None

    # --- baselines (derived): exclude today's row from history where present ---
    def hist(rows, key):
        # Drop the most recent (today) so the baseline is prior days.
        prior = rows[:-1] if len(rows) > 1 else []
        return _col(prior, key)

    comparisons = {
        "restingHeartRateBpm": {
            "7d": _baseline(today_rhr, hist(daily_7, "resting_hr_bpm")),
            "30d": _baseline(today_rhr, hist(daily_30, "resting_hr_bpm")),
            "note": "Lower is generally better; a sustained rise can signal fatigue/illness.",
        },
        "hrvMs": {
            "7d": _baseline(today_hrv, hist(hrv_7, "last_night_avg_ms")),
            "30d": _baseline(today_hrv, hist(hrv_30, "last_night_avg_ms")),
            "note": "Higher is generally better; a drop below baseline can indicate strain.",
        },
        "sleepDurationSeconds": {
            "7d": _baseline(today_sleep_dur, hist(sleep_7, "duration_seconds")),
            "30d": _baseline(today_sleep_dur, hist(sleep_30, "duration_seconds")),
        },
        "sleepScore": {
            "7d": _baseline(today_sleep_score, hist(sleep_7, "overall_score_value")),
            "30d": _baseline(today_sleep_score, hist(sleep_30, "overall_score_value")),
        },
        "stressLevel": {
            "7d": _baseline(today_stress, hist(daily_7, "avg_stress_level")),
            "30d": _baseline(today_stress, hist(daily_30, "avg_stress_level")),
        },
        "steps": {
            "7d": _baseline(today_steps, hist(daily_7, "steps")),
            "30d": _baseline(today_steps, hist(daily_30, "steps")),
        },
    }

    # --- trend arrays (last 30d, chronological) for the agent to eyeball ---
    def series(rows, key):
        return [
            {"date": r["calendar_date"], "value": _as_num(r[key])}
            for r in rows
        ]

    trends = {
        "restingHeartRateBpm": series(daily_30, "resting_hr_bpm"),
        "hrvMs": series(hrv_30, "last_night_avg_ms"),
        "sleepDurationSeconds": series(sleep_30, "duration_seconds"),
        "sleepScore": series(sleep_30, "overall_score_value"),
        "stressLevel": series(daily_30, "avg_stress_level"),
        "steps": series(daily_30, "steps"),
    }

    today_block: dict[str, Any] = {
        "calendarDate": calendar_date,
        "daily": pv.daily_view(daily) if daily else None,
        "sleep": pv.sleep_view(sleep) if sleep else None,
        "hrv": pv.hrv_view(hrv) if hrv else None,
        "bodyBatteryLatest": bb_latest,
        "bodyBatteryHigh": _as_num(daily["body_battery_high"]) if daily else None,
        "bodyBatteryLow": _as_num(daily["body_battery_low"]) if daily else None,
        "fitnessAge": pv.fitness_age_view(fitness_age) if fitness_age else None,
    }

    available = {
        "daily": daily is not None,
        "sleep": sleep is not None,
        "hrv": hrv is not None,
        "bodyBattery": bool(body_battery),
        "fitnessAge": fitness_age is not None,
    }

    return {
        "meta": {
            "schema": HEALTH_SCHEMA_VERSION,
            "generatedAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "unitSystemHint": unit_system,
            "notes": (
                "Snapshot of the most recent day with recorded data. `today` holds "
                "source values (SI units; durations in seconds, HRV in ms, HR in bpm). "
                "`comparisons` is DERIVED: today vs the mean of prior days in the 7d/30d "
                "window, with `delta` (today - avg) and a coarse `vsBaseline` flag "
                "(typical / above_typical / below_typical). `trends` are the raw 30-day "
                "series (chronological) for spotting direction and outliers. Treat null "
                "as 'no data' (not zero); negative stress sentinels are already nulled."
            ),
            "purpose": "Daily health snapshot for review by an AI coaching assistant.",
        },
        "available": available,
        "today": today_block,
        "comparisons": comparisons,
        "trends": trends,
    }
