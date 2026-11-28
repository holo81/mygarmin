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

import bisect
import math
import sqlite3
import statistics
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


_MAX_GAP_S = 30  # cap per-sample time delta so pauses are not counted as moving time
_MIN_PARTIAL_SPLIT_M = 100


def estimate_max_hr(
    samples: list[sqlite3.Row], summary_max: int | None, configured_max: int | None = None
) -> tuple[int | None, str]:
    """Return (maxHR, source). Prefer the athlete's configured max; otherwise the
    99.5th-percentile sample (robust to one-sample spikes); otherwise the activity's
    recorded max. The raw activity max alone is never preferred over samples."""
    if configured_max:
        return configured_max, "configured_max_hr"
    hrs = sorted(s["heart_rate_bpm"] for s in samples if s["heart_rate_bpm"] is not None)
    if hrs:
        idx = min(len(hrs) - 1, max(0, math.ceil(0.995 * len(hrs)) - 1))
        return hrs[idx], "observed_sample_p99_5"
    if summary_max:
        return summary_max, "activity_max_hr"
    return None, "unavailable"


def _dts(samples: list[sqlite3.Row]) -> list[float]:
    """Per-sample duration: gap to the next sample, capped; last sample reuses the previous gap."""
    n = len(samples)
    offs = [s["offset_seconds"] for s in samples]
    out: list[float] = []
    for i in range(n):
        if i + 1 < n and offs[i] is not None and offs[i + 1] is not None:
            out.append(float(min(max(offs[i + 1] - offs[i], 0), _MAX_GAP_S)))
        else:
            out.append(out[-1] if out else 1.0)
    return out


def hr_zones(
    samples: list[sqlite3.Row],
    max_hr: int | None,
    zone_floors: list[int] | None = None,
) -> dict[str, Any] | None:
    """Time-in-zone distribution; each sample counts for its own (capped) time delta.

    If `zone_floors` (the user's configured Z1..Z5 bpm floors) is provided, we use
    those absolute thresholds. Otherwise a percent-of-maxHR model (`basis` says which).
    Time below the Z1 floor is counted in Z1 in both modes.
    """
    dts = _dts(samples)
    timed = [(s["heart_rate_bpm"], dt) for s, dt in zip(samples, dts, strict=True) if s["heart_rate_bpm"] is not None]
    if not timed:
        return None
    seconds = [0.0] * 5

    if zone_floors and len(zone_floors) == 5 and all(zone_floors):
        floors = zone_floors
        for hr, dt in timed:
            zi = 0
            for i in range(5):
                if hr >= floors[i]:
                    zi = i
            seconds[zi] += dt
        basis = "configured_zone_floors_bpm"
        detail: Any = {"floorsBpm": floors}
    elif max_hr:
        for hr, dt in timed:
            pct = hr / max_hr
            zi = 0
            for i, (lo, _hi) in enumerate(_ZONE_BOUNDS_PCT):
                if pct >= lo:
                    zi = i
            seconds[zi] += dt
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
                "seconds": _round(seconds[i], 1),
                "percent": _round(100 * seconds[i] / total, 1),
            }
            for i in range(5)
        ],
    }


def splits(samples: list[sqlite3.Row], split_meters: int = 1000) -> list[dict[str, Any]] | None:
    """Per-split aggregates on cumulative distance (km markers), moving time only.
    The first split starts at the first recorded distance and the last may be partial
    (reported with its real distance); fragments under 100 m are dropped."""
    rows = [
        (s["offset_seconds"], s["distance_meters"], s["heart_rate_bpm"], s["elevation_meters"])
        for s in samples
        if s["distance_meters"] is not None and s["offset_seconds"] is not None
    ]
    if len(rows) < 2:
        return None
    # moving time: cumulative capped gaps
    mts = [0.0]
    for i in range(1, len(rows)):
        mts.append(mts[-1] + min(max(rows[i][0] - rows[i - 1][0], 0), _MAX_GAP_S))
    ds: list[float] = []
    for r in rows:  # enforce non-decreasing distance
        ds.append(max(r[1], ds[-1]) if ds else r[1])
    d0, d_end = ds[0], ds[-1]
    if d_end - d0 < split_meters:
        return None

    def mt_at(target: float) -> float:
        i = bisect.bisect_left(ds, target)
        if i == 0:
            return mts[0]
        if i >= len(ds):
            return mts[-1]
        if ds[i] == ds[i - 1]:
            return mts[i]
        return mts[i - 1] + (target - ds[i - 1]) / (ds[i] - ds[i - 1]) * (mts[i] - mts[i - 1])

    bounds = [d0]
    k = math.floor(d0 / split_meters) + 1
    while k * split_meters < d_end:
        bounds.append(float(k * split_meters))
        k += 1
    bounds.append(d_end)

    out: list[dict[str, Any]] = []
    for idx in range(len(bounds) - 1):
        a, b = bounds[idx], bounds[idx + 1]
        dist = b - a
        if dist < _MIN_PARTIAL_SPLIT_M:
            continue
        last = idx == len(bounds) - 2
        inside = [i for i, d in enumerate(ds) if a <= d < b or (last and d == b)]
        hrs = [rows[i][2] for i in inside if rows[i][2] is not None]
        el_start = next((rows[i][3] for i in range(len(rows)) if ds[i] >= a and rows[i][3] is not None), None)
        el_end = next((rows[i][3] for i in reversed(range(len(rows))) if ds[i] <= b and rows[i][3] is not None), None)
        dur = mt_at(b) - mt_at(a)
        pace = (dur / 60) / (dist / 1000) if dur > 0 else None
        out.append(
            {
                "split": len(out) + 1,
                "distanceMeters": _round(dist, 1) if dist != int(dist) else int(dist),
                "durationSeconds": _round(dur, 1),
                "paceMinPerKm": _round(pace, 2),
                "avgHrBpm": _round(_mean(hrs), 0),
                "elevationChangeMeters": _round(
                    (el_end - el_start) if (el_start is not None and el_end is not None) else None, 1
                ),
            }
        )
    return out or None


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


_ELEV_HYSTERESIS_M = 3.0


def _elevation_profile(samples: list[sqlite3.Row]) -> dict[str, Any] | None:
    els = [s["elevation_meters"] for s in samples if s["elevation_meters"] is not None]
    if len(els) < 2:
        return None
    # Zigzag filter: a reversal only counts once it exceeds the hysteresis, so
    # sensor jitter on flat ground yields ~0 gain/loss.
    gain = loss = 0.0
    pivot = ext = els[0]
    direction = 0
    for e in els[1:]:
        if direction == 0:
            if e - pivot >= _ELEV_HYSTERESIS_M:
                direction, ext = 1, e
            elif pivot - e >= _ELEV_HYSTERESIS_M:
                direction, ext = -1, e
        elif direction == 1:
            if e > ext:
                ext = e
            elif ext - e >= _ELEV_HYSTERESIS_M:
                gain += ext - pivot
                pivot, direction, ext = ext, -1, e
        else:
            if e < ext:
                ext = e
            elif e - ext >= _ELEV_HYSTERESIS_M:
                loss += pivot - ext
                pivot, direction, ext = ext, 1, e
    if direction == 1:
        gain += ext - pivot
    elif direction == -1:
        loss += pivot - ext
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
    n = len(samples)
    step = max(1, math.ceil((n - 1) / (target - 1)))
    idxs = list(range(0, n, step))
    if idxs[-1] != n - 1:
        idxs.append(n - 1)  # count stays <= target by construction
    out = []
    for i in idxs:
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
    max_hr_configured: int | None = None,
) -> dict[str, Any]:
    view = pv.activity_summary_view(activity)
    max_hr, max_hr_src = estimate_max_hr(samples, view.get("maxHrBpm"), max_hr_configured)

    derived: dict[str, Any] = {
        "sampleCount": len(samples),
        "hrZones": hr_zones(samples, max_hr, zone_floors),
        "hrZoneSource": max_hr_src,
        "splitsPerKm": splits(samples, 1000),
        "aerobicDecoupling": _decoupling(samples),
        "elevationProfile": _elevation_profile(samples),
        "heartRate": _series_stats(samples, "heart_rate_bpm"),
        "cadence": _series_stats(samples, "cadence"),
        "power": _series_stats(samples, "power_watts"),
    }

    points = _downsample(samples, 120)
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
                "time-series, not reported by Garmin. HR zones use configured zone floors when available, else percent-of-maxHR; "
                "`derived.hrZoneSource` states where maxHR came from. Splits and zone time use "
                "moving time only (gaps over 30s are capped). `series` is downsampled "
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
                        "fields": (
                "t=offsetSeconds, hr=bpm, paceMinPerKm, elevM, cad, pw=watts. "
                "`cad` is already steps per minute for running/walking (rpm for cycling); "
                "do NOT double it."
            ),
            "points": points,
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


_MIN_BASELINE_N = 5
_STD_REL_FLOOR = 0.05
_STD_ABS_FLOOR = 0.5


def _baseline(today: float | None, history: list[float | None]) -> dict[str, Any] | None:
    """Compare today's value to the prior values in `history` (nulls dropped).

    Needs >= 5 prior values for a flag, else `insufficient_history`. The spread is
    the sample std with a floor (5% of the mean, or 0.5) so tiny noise isn't flagged;
    above/below only beyond 1.0 spread."""
    if today is None:
        return None
    vals = [v for v in history if v is not None]
    if not vals:
        return {"today": _round(today, 1), "avg": None, "delta": None, "vsBaseline": "no_baseline"}
    avg = sum(vals) / len(vals)
    delta = today - avg
    out: dict[str, Any] = {"today": _round(today, 1), "avg": _round(avg, 1), "delta": _round(delta, 1), "n": len(vals)}
    if len(vals) < _MIN_BASELINE_N:
        out["vsBaseline"] = "insufficient_history"
        return out
    spread = max(statistics.stdev(vals), _STD_REL_FLOOR * abs(avg), _STD_ABS_FLOOR)
    z = delta / spread
    out["vsBaseline"] = "above_typical" if z > 1.0 else "below_typical" if z < -1.0 else "typical"
    return out


def _col(rows: list[sqlite3.Row], key: str, nonneg: bool = False) -> list[float | None]:
    out: list[float | None] = []
    for r in rows:
        try:
            v = _as_num(r[key])
        except (IndexError, KeyError):
            v = None
        if nonneg and v is not None and v < 0:
            v = None  # Garmin stress sentinels (-1/-2) mean "no data"
        out.append(v)
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
    body_battery_date: str | None = None,
) -> dict[str, Any]:
    calendar_date = daily["calendar_date"] if daily else (
        sleep["calendar_date"] if sleep else (hrv["calendar_date"] if hrv else None)
    )

    # A metric whose own date differs from the anchor is stale: never used as "today".
    sleep_fresh = sleep is not None and sleep["calendar_date"] == calendar_date
    hrv_fresh = hrv is not None and hrv["calendar_date"] == calendar_date
    bb_fresh = bool(body_battery) and (body_battery_date is None or body_battery_date == calendar_date)
    stale = []
    if sleep is not None and not sleep_fresh:
        stale.append("sleep")
    if hrv is not None and not hrv_fresh:
        stale.append("hrv")
    if body_battery and not bb_fresh:
        stale.append("bodyBattery")

    # --- today's values (source) ---
    today_rhr = _as_num(daily["resting_hr_bpm"]) if daily else None
    today_steps = _as_num(daily["steps"]) if daily else None
    today_stress = _as_num(daily["avg_stress_level"]) if daily else None
    if today_stress is not None and today_stress < 0:
        today_stress = None  # sentinel: not enough data
    today_sleep_dur = _as_num(sleep["duration_seconds"]) if sleep_fresh else None
    today_sleep_score = _as_num(sleep["overall_score_value"]) if sleep_fresh else None
    today_hrv = _as_num(hrv["last_night_avg_ms"]) if hrv_fresh else None
    bb_latest = body_battery[-1]["body_battery_value"] if bb_fresh else None

    # --- baselines (derived): only rows dated before the anchor ---
    def hist(rows, key, nonneg=False):
        prior = [r for r in rows if calendar_date is None or r["calendar_date"] < calendar_date]
        return _col(prior, key, nonneg)

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
            "7d": _baseline(today_stress, hist(daily_7, "avg_stress_level", True)),
            "30d": _baseline(today_stress, hist(daily_30, "avg_stress_level", True)),
        },
        "steps": {
            "7d": _baseline(today_steps, hist(daily_7, "steps")),
            "30d": _baseline(today_steps, hist(daily_30, "steps")),
        },
    }

    # --- trend arrays (last 30d, chronological) for the agent to eyeball ---
    def series(rows, key, nonneg=False):
        return [
            {"date": r["calendar_date"], "value": v}
            for r, v in zip(rows, _col(rows, key, nonneg), strict=True)
        ]

    trends = {
        "restingHeartRateBpm": series(daily_30, "resting_hr_bpm"),
        "hrvMs": series(hrv_30, "last_night_avg_ms"),
        "sleepDurationSeconds": series(sleep_30, "duration_seconds"),
        "sleepScore": series(sleep_30, "overall_score_value"),
        "stressLevel": series(daily_30, "avg_stress_level", True),
        "steps": series(daily_30, "steps"),
    }

    today_block: dict[str, Any] = {
        "calendarDate": calendar_date,
        "daily": pv.daily_view(daily) if daily else None,
        "sleep": pv.sleep_view(sleep) if sleep else None,
        "hrv": pv.hrv_view(hrv) if hrv else None,
        "bodyBattery": (
            {"calendarDate": body_battery_date, "latest": body_battery[-1]["body_battery_value"]}
            if body_battery
            else None
        ),
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
                "Snapshot anchored on the most recent daily date (`today.calendarDate`). "
                "`today` holds source values (SI units; durations in seconds, HRV in ms, "
                "HR in bpm). Metrics whose own `calendarDate` differs from the anchor are "
                "listed in `staleMetrics`; they are not compared as today's value. "
                "`comparisons` is DERIVED: today vs prior days in the 7d/30d window, with "
                "`delta` (today - avg) and `vsBaseline` (typical / above_typical / "
                "below_typical beyond 1 std with a floor; insufficient_history with fewer "
                "than 5 prior values). `trends` are the 30-day series (chronological). "
                "Treat null as 'no data' (not zero); negative stress sentinels (-1/-2) are "
                "nulled in today, baselines and trends."
            ),
            "purpose": "Daily health snapshot for review by an AI coaching assistant.",
        },
        "available": available,
        "staleMetrics": stale,
        "today": today_block,
        "comparisons": comparisons,
        "trends": trends,
    }
