"""Normalization: map real Garmin Personal API JSON into DB-ready row dicts.

Schemas here match the live Personal API (the modern Garmin Connect services),
confirmed against real responses:
  * usersummary-service/usersummary/daily        -> daily_summaries
  * sleep-service/sleep/dailySleep               -> sleep_summaries
  * hrv-service/hrv/{date} & /daily/{from}/{to}  -> hrv_summaries
  * wellness-service bodyBattery/reports/daily   -> body_battery_samples
  * wellness-service/dailyHeartRate              -> daily_hr_samples
  * usersummary-service/stats/stress/daily/...   -> stress (overall level)
  * activitylist-service .../search/activities   -> activities
  * activity-service/activity/{id} (summaryDTO)  -> activity summary enrichment

Data-integrity rules:
  * NULL stays NULL (missing != zero).
  * Timestamps from the API are epoch MILLISECONDS; we store epoch SECONDS (UTC)
    plus a device offset in seconds, derived from the GMT vs Local pair.
  * Source units preserved (meters, seconds, m/s, bpm, ms); no unit math here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _get(obj: dict[str, Any], *names: str) -> Any:
    if not isinstance(obj, dict):
        return None
    for n in names:
        if n in obj:
            return obj[n]
    lowered = {k.lower(): v for k, v in obj.items()}
    for n in names:
        if n.lower() in lowered:
            return lowered[n.lower()]
    return None


def _as_int(v: Any) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _as_float(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_bool_int(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)):
        return 1 if v else 0
    if isinstance(v, str):
        return 1 if v.strip().lower() in ("true", "1", "yes") else 0
    return None


def _ms_to_s(v: Any) -> int | None:
    """Epoch milliseconds -> epoch seconds (UTC)."""
    iv = _as_int(v)
    return iv // 1000 if iv is not None else None


def _parse_dt(s: Any) -> datetime | None:
    """Parse Garmin timestamps like '2026-10-21T00:00:00.0' (no tz)."""
    if not isinstance(s, str) or not s:
        return None
    text = s.replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _offset_seconds_from_gmt_local(gmt: Any, local: Any) -> int | None:
    """Derive device local offset (seconds) from paired GMT/Local naive stamps."""
    g = _parse_dt(gmt)
    loc = _parse_dt(local)
    if g is None or loc is None:
        return None
    return int((loc - g).total_seconds())


def _offset_from_ms(gmt_ms: Any, local_ms: Any) -> int | None:
    g = _as_int(gmt_ms)
    loc = _as_int(local_ms)
    if g is None or loc is None:
        return None
    return int((loc - g) / 1000)


def _gmt_str_to_s(s: Any) -> int | None:
    dt = _parse_dt(s)
    if dt is None:
        return None
    return int(dt.replace(tzinfo=UTC).timestamp())


# --- daily summary (usersummary/daily) -------------------------------------

def normalize_daily(obj: dict[str, Any]) -> dict[str, Any] | None:
    calendar_date = _get(obj, "calendarDate")
    if not calendar_date:
        return None
    offset = _offset_seconds_from_gmt_local(
        _get(obj, "wellnessStartTimeGmt"), _get(obj, "wellnessStartTimeLocal")
    )
    start_s = _gmt_str_to_s(_get(obj, "wellnessStartTimeGmt"))
    duration_ms = _as_int(_get(obj, "durationInMilliseconds"))
    moderate_min = _as_int(_get(obj, "moderateIntensityMinutes"))
    vigorous_min = _as_int(_get(obj, "vigorousIntensityMinutes"))
    return {
        "summary_id": f"daily-{calendar_date}",
        "calendar_date": calendar_date,
        "start_time_seconds": start_s,
        "start_time_offset_seconds": offset,
        "duration_seconds": duration_ms // 1000 if duration_ms is not None else None,
        "steps": _as_int(_get(obj, "totalSteps")),
        "steps_goal": _as_int(_get(obj, "dailyStepGoal")),
        "distance_meters": _as_float(_get(obj, "totalDistanceMeters")),
        "floors_climbed": _as_int(_get(obj, "floorsAscended")),
        "floors_climbed_goal": _as_int(_get(obj, "userFloorsAscendedGoal")),
        "active_kilocalories": _as_int(_get(obj, "activeKilocalories")),
        "bmr_kilocalories": _as_int(_get(obj, "bmrKilocalories")),
        "total_kilocalories": _as_int(_get(obj, "totalKilocalories")),
        "active_time_seconds": _as_int(_get(obj, "activeSeconds")),
        "sleeping_seconds": _as_int(_get(obj, "sleepingSeconds")),
        # API provides intensity in MINUTES; store as seconds for schema consistency.
        "moderate_intensity_seconds": moderate_min * 60 if moderate_min is not None else None,
        "vigorous_intensity_seconds": vigorous_min * 60 if vigorous_min is not None else None,
        "intensity_goal_seconds": (
            _as_int(_get(obj, "intensityMinutesGoal")) * 60
            if _get(obj, "intensityMinutesGoal") is not None
            else None
        ),
        "min_hr_bpm": _as_int(_get(obj, "minHeartRate")),
        "max_hr_bpm": _as_int(_get(obj, "maxHeartRate")),
        "average_hr_bpm": _as_int(_get(obj, "lastSevenDaysAvgRestingHeartRate")),
        "resting_hr_bpm": _as_int(_get(obj, "restingHeartRate")),
        "resting_hr_7d_avg": _as_int(_get(obj, "lastSevenDaysAvgRestingHeartRate")),
        "avg_stress_level": _as_int(_get(obj, "averageStressLevel")),
        "max_stress_level": _as_int(_get(obj, "maxStressLevel")),
        "stress_duration_seconds": _as_int(_get(obj, "stressDuration")),
        "rest_stress_duration_seconds": _as_int(_get(obj, "restStressDuration")),
        "activity_stress_duration_seconds": _as_int(_get(obj, "activityStressDuration")),
        "low_stress_duration_seconds": _as_int(_get(obj, "lowStressDuration")),
        "medium_stress_duration_seconds": _as_int(_get(obj, "mediumStressDuration")),
        "high_stress_duration_seconds": _as_int(_get(obj, "highStressDuration")),
        "stress_qualifier": _get(obj, "stressQualifier"),
        "body_battery_charged": _as_int(_get(obj, "bodyBatteryChargedValue")),
        "body_battery_drained": _as_int(_get(obj, "bodyBatteryDrainedValue")),
        "body_battery_high": _as_int(_get(obj, "bodyBatteryHighestValue")),
        "body_battery_low": _as_int(_get(obj, "bodyBatteryLowestValue")),
        "body_battery_most_recent": _as_int(_get(obj, "bodyBatteryMostRecentValue")),
        "avg_spo2": _as_float(_get(obj, "averageSpo2")),
        "lowest_spo2": _as_int(_get(obj, "lowestSpo2")),
        "avg_waking_respiration": _as_float(_get(obj, "avgWakingRespirationValue")),
        "highest_respiration": _as_float(_get(obj, "highestRespirationValue")),
        "lowest_respiration": _as_float(_get(obj, "lowestRespirationValue")),
    }


def normalize_daily_hr_samples(obj: dict[str, Any]) -> list[dict[str, Any]]:
    """dailyHeartRate.heartRateValues = [[epochMs, bpm], ...] -> offset rows."""
    calendar_date = _get(obj, "calendarDate")
    values = _get(obj, "heartRateValues") or []
    start_ms = _as_int(_get(obj, "startTimestampGMT"))
    out: list[dict[str, Any]] = []
    if not (isinstance(values, list) and calendar_date):
        return out
    base = None
    if start_ms is not None:
        base = start_ms
    for pair in values:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        ts_ms, bpm = pair[0], pair[1]
        val = _as_int(bpm)
        ts = _as_int(ts_ms)
        if val is None or ts is None:
            continue  # null bpm = no reading; skip (not zero)
        if base is None:
            base = ts
        out.append(
            {
                "calendar_date": calendar_date,
                "offset_seconds": int((ts - base) / 1000),
                "heart_rate_bpm": val,
            }
        )
    return out


# --- sleep (sleep/dailySleep) ----------------------------------------------

def normalize_sleep(obj: dict[str, Any]) -> dict[str, Any] | None:
    calendar_date = _get(obj, "calendarDate")
    if not calendar_date:
        return None
    scores = _get(obj, "sleepScores") or {}
    overall = scores.get("overall") if isinstance(scores, dict) else None
    score_value = _as_int(_get(overall, "value")) if isinstance(overall, dict) else None
    score_qualifier = _get(overall, "qualifierKey") if isinstance(overall, dict) else None
    start_s = _ms_to_s(_get(obj, "sleepStartTimestampGMT"))
    offset = _offset_from_ms(
        _get(obj, "sleepStartTimestampGMT"), _get(obj, "sleepStartTimestampLocal")
    )
    return {
        "summary_id": f"sleep-{calendar_date}",
        "calendar_date": calendar_date,
        "start_time_seconds": start_s,
        "start_time_offset_seconds": offset,
        "duration_seconds": _as_int(_get(obj, "sleepTimeSeconds")),
        "unmeasurable_seconds": _as_int(_get(obj, "unmeasurableSleepSeconds")),
        "deep_seconds": _as_int(_get(obj, "deepSleepSeconds")),
        "light_seconds": _as_int(_get(obj, "lightSleepSeconds")),
        "rem_seconds": _as_int(_get(obj, "remSleepSeconds")),
        "awake_seconds": _as_int(_get(obj, "awakeSleepSeconds")),
        "total_nap_seconds": _as_int(_get(obj, "napTimeSeconds")),
        "overall_score_value": score_value,
        "overall_score_qualifier": score_qualifier,
        "avg_sleep_respiration": _as_float(_get(obj, "averageRespirationValue")),
        "avg_sleep_spo2": _as_float(_get(obj, "averageSpO2Value")),
        "lowest_spo2": _as_int(_get(obj, "lowestSpO2Value")),
        "avg_sleep_stress": _as_float(_get(obj, "avgSleepStress")),
        "avg_sleep_hr": _as_float(_get(obj, "avgHeartRate")),
        "awake_count": _as_int(_get(obj, "awakeCount")),
        "validation": _get(obj, "sleepWindowConfirmationType"),
    }


def normalize_sleep_stages(obj: dict[str, Any]) -> list[dict[str, Any]]:
    """The dailySleep endpoint provides stage totals, not interval maps.

    Detailed stage intervals (sleepLevelsMap) are not part of this endpoint's
    response, so we return no interval rows here. The summary stage *durations*
    are stored on the summary row. (Returning [] keeps the caller generic.)
    """
    return []


# --- HRV (hrv/{date} and hrv/daily/{from}/{to}) ----------------------------

def normalize_hrv(obj: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a single HRV summary (either the daily object's hrvSummary or
    one element of the range endpoint's hrvSummaries list)."""
    summary = _get(obj, "hrvSummary")
    src = summary if isinstance(summary, dict) else obj
    calendar_date = _get(src, "calendarDate")
    if not calendar_date:
        return None
    baseline = _get(src, "baseline") or {}
    return {
        "summary_id": f"hrv-{calendar_date}",
        "calendar_date": calendar_date,
        "start_time_seconds": _gmt_str_to_s(_get(obj, "startTimestampGMT")),
        "start_time_offset_seconds": _offset_seconds_from_gmt_local(
            _get(obj, "startTimestampGMT"), _get(obj, "startTimestampLocal")
        ),
        "duration_seconds": None,
        "last_night_avg_ms": _as_float(_get(src, "lastNightAvg")),
        "last_night_5min_high_ms": _as_float(_get(src, "lastNight5MinHigh")),
        "weekly_avg_ms": _as_float(_get(src, "weeklyAvg")),
        "baseline_low_ms": _as_float(_get(baseline, "balancedLow", "lowUpper")),
        "baseline_high_ms": _as_float(_get(baseline, "balancedUpper")),
        "status": _get(src, "status"),
    }


def normalize_hrv_range(obj: dict[str, Any]) -> list[dict[str, Any]]:
    summaries = _get(obj, "hrvSummaries") or []
    out = []
    if isinstance(summaries, list):
        for s in summaries:
            row = normalize_hrv(s)
            if row:
                out.append(row)
    return out


# --- stress (stats/stress/daily range) -------------------------------------

def normalize_stress_range(items: list) -> list[dict[str, Any]]:
    """Each item: {calendarDate, values:{overallStressLevel, *Duration}}."""
    out: list[dict[str, Any]] = []
    for it in items or []:
        cal = _get(it, "calendarDate")
        vals = _get(it, "values") or {}
        if not cal:
            continue
        out.append(
            {
                "summary_id": f"stress-{cal}",
                "calendar_date": cal,
                "start_time_seconds": None,
                "start_time_offset_seconds": None,
                "duration_seconds": None,
                "body_battery_level": None,
                "_overall_stress": _as_int(_get(vals, "overallStressLevel")),
            }
        )
    return out


# --- body battery reports --------------------------------------------------

def normalize_body_battery_report(item: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]]]:
    """bodyBattery report item -> (calendarDate, [samples]).

    bodyBatteryValuesArray = [[epochMs, level], ...]; descriptor list confirms
    index 0=timestamp, 1=bodyBatteryLevel.
    """
    cal = _get(item, "date", "calendarDate")
    arr = _get(item, "bodyBatteryValuesArray") or []
    out: list[dict[str, Any]] = []
    if not (isinstance(arr, list) and cal):
        return cal, out
    base = None
    for pair in arr:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        ts = _as_int(pair[0])
        level = _as_int(pair[1])
        if ts is None or level is None:
            continue
        if base is None:
            base = ts
        out.append(
            {
                "calendar_date": cal,
                "offset_seconds": int((ts - base) / 1000),
                "body_battery_value": level,
            }
        )
    return cal, out


# --- activities (activitylist search) --------------------------------------

_PACE_FLOOR_MPS = 0.1


def normalize_hr_zones(items: list) -> list[dict[str, Any]]:
    """Each item is the configured zone set for one sport."""
    out: list[dict[str, Any]] = []
    for it in items or []:
        sport = _get(it, "sport")
        if not sport:
            continue
        out.append(
            {
                "sport": sport,
                "training_method": _get(it, "trainingMethod"),
                "resting_hr_used": _as_int(_get(it, "restingHeartRateUsed")),
                "lactate_threshold_hr_used": _as_int(_get(it, "lactateThresholdHeartRateUsed")),
                "max_hr_used": _as_int(_get(it, "maxHeartRateUsed")),
                "zone1_floor": _as_int(_get(it, "zone1Floor")),
                "zone2_floor": _as_int(_get(it, "zone2Floor")),
                "zone3_floor": _as_int(_get(it, "zone3Floor")),
                "zone4_floor": _as_int(_get(it, "zone4Floor")),
                "zone5_floor": _as_int(_get(it, "zone5Floor")),
            }
        )
    return out


def normalize_fitness_age(obj: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(obj, dict):
        return None
    last_updated = _get(obj, "lastUpdated")
    calendar_date = last_updated.split("T")[0] if isinstance(last_updated, str) else None
    if not calendar_date:
        return None
    components = _get(obj, "components") or {}
    rhr = components.get("rhr") if isinstance(components, dict) else None
    bmi = components.get("bmi") if isinstance(components, dict) else None
    vdays = components.get("vigorousDaysAvg") if isinstance(components, dict) else None
    vmin = components.get("vigorousMinutesAvg") if isinstance(components, dict) else None
    import json as _json

    return {
        "calendar_date": calendar_date,
        "chronological_age": _as_float(_get(obj, "chronologicalAge")),
        "fitness_age": _as_float(_get(obj, "fitnessAge")),
        "achievable_fitness_age": _as_float(_get(obj, "achievableFitnessAge")),
        "previous_fitness_age": _as_float(_get(obj, "previousFitnessAge")),
        "rhr_value": _as_int(_get(rhr, "value")) if isinstance(rhr, dict) else None,
        "bmi_value": _as_float(_get(bmi, "value")) if isinstance(bmi, dict) else None,
        "bmi_target": _as_float(_get(bmi, "targetValue")) if isinstance(bmi, dict) else None,
        "vigorous_days_avg": _as_float(_get(vdays, "value")) if isinstance(vdays, dict) else None,
        "vigorous_days_target": _as_float(_get(vdays, "targetValue")) if isinstance(vdays, dict) else None,
        "vigorous_minutes_avg": _as_float(_get(vmin, "value")) if isinstance(vmin, dict) else None,
        "vigorous_minutes_target": _as_float(_get(vmin, "targetValue")) if isinstance(vmin, dict) else None,
        "components_json": _json.dumps(components) if components else None,
    }


def normalize_weight_range(obj: dict[str, Any]) -> list[dict[str, Any]]:
    """weight/range -> one row per day, using that day's latestWeight entry.

    Weight stays in GRAMS (source unit); the UI converts for display.
    """
    summaries = _get(obj, "dailyWeightSummaries") or []
    out: list[dict[str, Any]] = []
    if not isinstance(summaries, list):
        return out
    for s in summaries:
        cal = _get(s, "summaryDate", "calendarDate")
        latest = _get(s, "latestWeight") or {}
        if not cal:
            continue
        out.append(
            {
                "calendar_date": cal,
                "weight_grams": _as_float(_get(latest, "weight")),
                "bmi": _as_float(_get(latest, "bmi")),
                "body_fat_pct": _as_float(_get(latest, "bodyFat")),
                "body_water_pct": _as_float(_get(latest, "bodyWater")),
                "muscle_mass_g": _as_float(_get(latest, "muscleMass")),
                "bone_mass_g": _as_float(_get(latest, "boneMass")),
                "source_type": _get(latest, "sourceType"),
            }
        )
    return out


def normalize_activity(obj: dict[str, Any]) -> dict[str, Any] | None:
    activity_id = _get(obj, "activityId")
    if activity_id is None:
        return None
    atype = _get(obj, "activityType") or {}
    type_key = _get(atype, "typeKey") if isinstance(atype, dict) else atype
    start_gmt = _get(obj, "startTimeGMT")
    start_local = _get(obj, "startTimeLocal")
    start_s = _gmt_str_to_s(start_gmt)
    offset = _offset_seconds_from_gmt_local(start_gmt, start_local)
    avg_speed = _as_float(_get(obj, "averageSpeed"))
    pace = None
    if avg_speed and avg_speed > _PACE_FLOOR_MPS:
        pace = (1000.0 / avg_speed) / 60.0
    return {
        "summary_id": str(activity_id),
        "activity_id": str(activity_id),
        "activity_type": type_key,
        "activity_name": _get(obj, "activityName"),
        "start_time_seconds": start_s,
        "start_time_offset_seconds": offset,
        "duration_seconds": _as_int(_get(obj, "duration")),
        "distance_meters": _as_float(_get(obj, "distance")),
        "active_kilocalories": _as_int(_get(obj, "calories")),
        "avg_hr_bpm": _as_int(_get(obj, "averageHR")),
        "max_hr_bpm": _as_int(_get(obj, "maxHR")),
        "avg_speed_mps": avg_speed,
        "max_speed_mps": _as_float(_get(obj, "maxSpeed")),
        "avg_pace_min_per_km": pace,
        "avg_run_cadence_spm": _as_float(_get(obj, "averageRunningCadenceInStepsPerMinute")),
        "max_run_cadence_spm": _as_float(_get(obj, "maxRunningCadenceInStepsPerMinute")),
        "avg_bike_cadence_rpm": _as_float(_get(obj, "averageBikingCadenceInRevPerMinute")),
        "avg_swim_cadence_spm": _as_float(_get(obj, "averageSwimCadenceInStrokesPerMinute")),
        "total_elevation_gain_m": _as_float(_get(obj, "elevationGain")),
        "total_elevation_loss_m": _as_float(_get(obj, "elevationLoss")),
        "starting_latitude": _as_float(_get(obj, "startLatitude")),
        "starting_longitude": _as_float(_get(obj, "startLongitude")),
        "steps": _as_int(_get(obj, "steps")),
        "device_name": _get(obj, "deviceName"),
        "is_parent": _as_bool_int(_get(obj, "isParent")),
        "parent_summary_id": None,
        "manual": _as_bool_int(_get(obj, "manualActivity")),
    }
