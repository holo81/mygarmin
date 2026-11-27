"""Normalization: map raw Garmin API JSON into typed DB-ready row dicts.

Why this layer exists
---------------------
The Personal API returns the same payloads as Garmin's Health/Activity REST
services. Field documentation appears in two casings across Garmin's materials:
camelCase in the REST API spec (e.g. ``restingHeartRateInBeatsPerMinute``) and
PascalCase in the data-export docs (e.g. ``RestingHeartRateInBeatsPerMinute``).
To be robust we look up each field case-insensitively via ``_get``.

Data-integrity rules enforced here
----------------------------------
* NULL stays NULL. We never coerce a missing field to 0.
* Source units are preserved (meters, seconds, m/s, bpm, ms). No unit math here.
* Stress sentinels (-1..-5) and avg-stress sentinels (-1/-2) are preserved as-is.
* Derived values (e.g. mean sleep respiration) are clearly named and documented
  as derived, not presented as a distinct API field.
"""

from __future__ import annotations

from typing import Any


def _get(obj: dict[str, Any], *names: str) -> Any:
    """Case-insensitive, multi-alias field getter. Returns None if absent."""
    if not isinstance(obj, dict):
        return None
    # Fast path: exact match.
    for n in names:
        if n in obj:
            return obj[n]
    # Case-insensitive fallback.
    lowered = {k.lower(): v for k, v in obj.items()}
    for n in names:
        if n.lower() in lowered:
            return lowered[n.lower()]
    return None


def _as_int(v: Any) -> int | None:
    if v is None or isinstance(v, bool):
        return int(v) if isinstance(v, bool) else None
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


def _mean(values: list[float]) -> float | None:
    vals = [v for v in values if isinstance(v, (int, float))]
    return (sum(vals) / len(vals)) if vals else None


# --- activities ------------------------------------------------------------

def normalize_activity(obj: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one activity summary. Returns None if no stable id is present."""
    summary_id = _get(obj, "summaryId")
    activity_id = _get(obj, "activityId")
    # summaryId is the stable natural key; fall back to activityId if absent.
    key = summary_id or (str(activity_id) if activity_id is not None else None)
    if key is None:
        return None
    return {
        "summary_id": str(key),
        "activity_id": str(activity_id) if activity_id is not None else None,
        "activity_type": _get(obj, "activityType"),
        "activity_name": _get(obj, "activityName"),
        "start_time_seconds": _as_int(_get(obj, "startTimeInSeconds")),
        "start_time_offset_seconds": _as_int(_get(obj, "startTimeOffsetInSeconds")),
        "duration_seconds": _as_int(_get(obj, "durationInSeconds")),
        "distance_meters": _as_float(_get(obj, "distanceInMeters")),
        "active_kilocalories": _as_int(_get(obj, "activeKilocalories")),
        "avg_hr_bpm": _as_int(_get(obj, "averageHeartRateInBeatsPerMinute")),
        "max_hr_bpm": _as_int(_get(obj, "maxHeartRateInBeatsPerMinute")),
        "avg_speed_mps": _as_float(_get(obj, "averageSpeedInMetersPerSecond")),
        "max_speed_mps": _as_float(_get(obj, "maxSpeedInMetersPerSecond")),
        "avg_pace_min_per_km": _as_float(_get(obj, "averagePaceInMinutesPerKilometer")),
        "avg_run_cadence_spm": _as_float(_get(obj, "averageRunCadenceInStepsPerMinute")),
        "max_run_cadence_spm": _as_float(_get(obj, "maxRunCadenceInStepsPerMinute")),
        "avg_bike_cadence_rpm": _as_float(_get(obj, "averageBikeCadenceInRoundsPerMinute")),
        "avg_swim_cadence_spm": _as_float(
            _get(obj, "averageSwimCadenceInStrokesPerMinute")
        ),
        "total_elevation_gain_m": _as_float(_get(obj, "totalElevationGainInMeters")),
        "total_elevation_loss_m": _as_float(_get(obj, "totalElevationLossInMeters")),
        "starting_latitude": _as_float(_get(obj, "startingLatitudeInDegree")),
        "starting_longitude": _as_float(_get(obj, "startingLongitudeInDegree")),
        "steps": _as_int(_get(obj, "steps")),
        "device_name": _get(obj, "deviceName"),
        "is_parent": _as_bool_int(_get(obj, "isParent")),
        "parent_summary_id": _get(obj, "parentSummaryId"),
        "manual": _as_bool_int(_get(obj, "manual")),
    }


def normalize_activity_samples(
    details_obj: dict[str, Any],
) -> list[dict[str, Any]]:
    """Normalize the samples array inside an activityDetails object."""
    samples = _get(details_obj, "samples") or []
    out: list[dict[str, Any]] = []
    for i, s in enumerate(samples):
        if not isinstance(s, dict):
            continue
        out.append(
            {
                "sample_index": i,
                "offset_seconds": None,  # computed by caller relative to start
                "clock_time_seconds": _as_int(_get(s, "startTimeInSeconds")),
                "latitude": _as_float(_get(s, "latitudeInDegree")),
                "longitude": _as_float(_get(s, "longitudeInDegree")),
                "elevation_meters": _as_float(_get(s, "elevationInMeters")),
                "heart_rate_bpm": _as_int(_get(s, "heartRate")),
                "speed_mps": _as_float(_get(s, "speedMetersPerSecond")),
                "cadence": _as_float(
                    _get(s, "stepsPerMinute", "bikeCadenceInRPM")
                ),
                "power_watts": _as_float(_get(s, "powerInWatts")),
                "distance_meters": _as_float(_get(s, "totalDistanceInMeters")),
                "temperature_celsius": _as_float(_get(s, "airTemperatureCelcius")),
                "source": "activityDetails",
            }
        )
    # Backfill offset_seconds from clock times if we have a start.
    start = min(
        (r["clock_time_seconds"] for r in out if r["clock_time_seconds"] is not None),
        default=None,
    )
    if start is not None:
        for r in out:
            if r["clock_time_seconds"] is not None:
                r["offset_seconds"] = r["clock_time_seconds"] - start
    return out


# --- daily summaries -------------------------------------------------------

def normalize_daily(obj: dict[str, Any]) -> dict[str, Any] | None:
    calendar_date = _get(obj, "calendarDate")
    summary_id = _get(obj, "summaryId")
    if not summary_id and not calendar_date:
        return None
    return {
        "summary_id": str(summary_id) if summary_id else f"daily-{calendar_date}",
        "calendar_date": calendar_date,
        "start_time_seconds": _as_int(_get(obj, "startTimeInSeconds")),
        "start_time_offset_seconds": _as_int(_get(obj, "startTimeOffsetInSeconds")),
        "duration_seconds": _as_int(_get(obj, "durationInSeconds")),
        "steps": _as_int(_get(obj, "steps")),
        "steps_goal": _as_int(_get(obj, "stepsGoal")),
        "distance_meters": _as_float(_get(obj, "distanceInMeters")),
        "floors_climbed": _as_int(_get(obj, "floorsClimbed")),
        "floors_climbed_goal": _as_int(_get(obj, "floorsClimbedGoal")),
        "active_kilocalories": _as_int(_get(obj, "activeKilocalories")),
        "bmr_kilocalories": _as_int(_get(obj, "bmrKilocalories")),
        "active_time_seconds": _as_int(_get(obj, "activeTimeInSeconds")),
        "moderate_intensity_seconds": _as_int(
            _get(obj, "moderateIntensityDurationInSeconds")
        ),
        "vigorous_intensity_seconds": _as_int(
            _get(obj, "vigorousIntensityDurationInSeconds")
        ),
        "intensity_goal_seconds": _as_int(_get(obj, "intensityDurationGoalInSeconds")),
        "min_hr_bpm": _as_int(_get(obj, "minHeartRateInBeatsPerMinute")),
        "max_hr_bpm": _as_int(_get(obj, "maxHeartRateInBeatsPerMinute")),
        "average_hr_bpm": _as_int(_get(obj, "averageHeartRateInBeatsPerMinute")),
        "resting_hr_bpm": _as_int(_get(obj, "restingHeartRateInBeatsPerMinute")),
        "avg_stress_level": _as_int(_get(obj, "averageStressLevel")),
        "max_stress_level": _as_int(_get(obj, "maxStressLevel")),
        "stress_duration_seconds": _as_int(_get(obj, "stressDurationInSeconds")),
        "rest_stress_duration_seconds": _as_int(_get(obj, "restStressDurationInSeconds")),
        "activity_stress_duration_seconds": _as_int(
            _get(obj, "activityStressDurationInSeconds")
        ),
        "low_stress_duration_seconds": _as_int(_get(obj, "lowStressDurationInSeconds")),
        "medium_stress_duration_seconds": _as_int(
            _get(obj, "mediumStressDurationInSeconds")
        ),
        "high_stress_duration_seconds": _as_int(_get(obj, "highStressDurationInSeconds")),
        "stress_qualifier": _get(obj, "stressQualifier"),
    }


def normalize_daily_hr_samples(obj: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand timeOffsetHeartRateSamples {offset: bpm} into rows."""
    calendar_date = _get(obj, "calendarDate")
    samples = _get(obj, "timeOffsetHeartRateSamples") or {}
    out: list[dict[str, Any]] = []
    if isinstance(samples, dict) and calendar_date:
        for offset, bpm in samples.items():
            off = _as_int(offset)
            val = _as_int(bpm)
            if off is not None and val is not None:
                out.append(
                    {
                        "calendar_date": calendar_date,
                        "offset_seconds": off,
                        "heart_rate_bpm": val,
                    }
                )
    return out


# --- sleep -----------------------------------------------------------------

def normalize_sleep(obj: dict[str, Any]) -> dict[str, Any] | None:
    summary_id = _get(obj, "summaryId")
    calendar_date = _get(obj, "calendarDate")
    if not summary_id and not calendar_date:
        return None

    overall = _get(obj, "overallSleepScore")
    score_value = None
    score_qualifier = _get(obj, "overallSleepScoreQualifierKey")
    if isinstance(overall, dict):
        score_value = _as_int(_get(overall, "value"))
        score_qualifier = score_qualifier or _get(overall, "qualifierKey")
    else:
        score_value = _as_int(_get(obj, "overallSleepScoreValue"))

    resp_samples = _get(obj, "timeOffsetSleepRespiration") or {}
    spo2_samples = _get(obj, "timeOffsetSleepSpo2") or {}
    avg_resp = (
        _mean([_as_float(v) for v in resp_samples.values()])
        if isinstance(resp_samples, dict)
        else None
    )
    avg_spo2 = (
        _mean([_as_float(v) for v in spo2_samples.values()])
        if isinstance(spo2_samples, dict)
        else None
    )

    return {
        "summary_id": str(summary_id) if summary_id else f"sleep-{calendar_date}",
        "calendar_date": calendar_date,
        "start_time_seconds": _as_int(_get(obj, "startTimeInSeconds")),
        "start_time_offset_seconds": _as_int(_get(obj, "startTimeOffsetInSeconds")),
        "duration_seconds": _as_int(_get(obj, "durationInSeconds")),
        "unmeasurable_seconds": _as_int(_get(obj, "unmeasurableSleepInSeconds")),
        "deep_seconds": _as_int(_get(obj, "deepSleepDurationInSeconds")),
        "light_seconds": _as_int(_get(obj, "lightSleepDurationInSeconds")),
        "rem_seconds": _as_int(_get(obj, "remSleepInSeconds")),
        "awake_seconds": _as_int(_get(obj, "awakeDurationInSeconds")),
        "total_nap_seconds": _as_int(_get(obj, "totalNapDurationInSeconds")),
        "overall_score_value": score_value,
        "overall_score_qualifier": score_qualifier,
        "avg_sleep_respiration": avg_resp,  # DERIVED (mean of samples)
        "avg_sleep_spo2": avg_spo2,  # DERIVED (mean of samples)
        "validation": _get(obj, "validation"),
    }


def normalize_sleep_stages(obj: dict[str, Any]) -> list[dict[str, Any]]:
    levels = _get(obj, "sleepLevelsMap") or {}
    out: list[dict[str, Any]] = []
    if isinstance(levels, dict):
        for stage, intervals in levels.items():
            if not isinstance(intervals, list):
                continue
            for iv in intervals:
                start = _as_int(_get(iv, "startTimeInSeconds"))
                end = _as_int(_get(iv, "endTimeInSeconds"))
                if start is not None and end is not None:
                    out.append(
                        {
                            "stage": str(stage).lower(),
                            "start_time_seconds": start,
                            "end_time_seconds": end,
                        }
                    )
    return out


# --- stress / body battery -------------------------------------------------

def normalize_stress(obj: dict[str, Any]) -> dict[str, Any] | None:
    summary_id = _get(obj, "summaryId")
    calendar_date = _get(obj, "calendarDate")
    if not summary_id and not calendar_date:
        return None
    bb_event = _get(obj, "bodyBatteryDynamicFeedbackEvent")
    bb_level = _get(bb_event, "bodyBatteryLevel") if isinstance(bb_event, dict) else None
    return {
        "summary_id": str(summary_id) if summary_id else f"stress-{calendar_date}",
        "calendar_date": calendar_date,
        "start_time_seconds": _as_int(_get(obj, "startTimeInSeconds")),
        "start_time_offset_seconds": _as_int(_get(obj, "startTimeOffsetInSeconds")),
        "duration_seconds": _as_int(_get(obj, "durationInSeconds")),
        "body_battery_level": bb_level,
    }


def normalize_stress_samples(obj: dict[str, Any]) -> list[dict[str, Any]]:
    calendar_date = _get(obj, "calendarDate")
    samples = _get(obj, "timeOffsetStressLevelValues") or {}
    out: list[dict[str, Any]] = []
    if isinstance(samples, dict) and calendar_date:
        for offset, value in samples.items():
            off = _as_int(offset)
            val = _as_int(value)
            if off is not None and val is not None:
                out.append(
                    {
                        "calendar_date": calendar_date,
                        "offset_seconds": off,
                        "stress_value": val,  # may be sentinel < 0
                    }
                )
    return out


def normalize_body_battery_samples(obj: dict[str, Any]) -> list[dict[str, Any]]:
    calendar_date = _get(obj, "calendarDate")
    samples = _get(obj, "timeOffsetBodyBatteryValues") or {}
    out: list[dict[str, Any]] = []
    if isinstance(samples, dict) and calendar_date:
        for offset, value in samples.items():
            off = _as_int(offset)
            val = _as_int(value)
            if off is not None and val is not None:
                out.append(
                    {
                        "calendar_date": calendar_date,
                        "offset_seconds": off,
                        "body_battery_value": val,
                    }
                )
    return out


# --- HRV -------------------------------------------------------------------

def normalize_hrv(obj: dict[str, Any]) -> dict[str, Any] | None:
    summary_id = _get(obj, "summaryId")
    calendar_date = _get(obj, "calendarDate")
    # HRV payloads sometimes nest under hrvSummary.
    summary = _get(obj, "hrvSummary")
    src = summary if isinstance(summary, dict) else obj
    if not summary_id and not calendar_date:
        calendar_date = _get(src, "calendarDate")
    if not summary_id and not calendar_date:
        return None
    return {
        "summary_id": str(summary_id) if summary_id else f"hrv-{calendar_date}",
        "calendar_date": calendar_date,
        "start_time_seconds": _as_int(_get(obj, "startTimeInSeconds")),
        "start_time_offset_seconds": _as_int(_get(obj, "startTimeOffsetInSeconds")),
        "duration_seconds": _as_int(_get(obj, "durationInSeconds")),
        "last_night_avg_ms": _as_float(_get(src, "lastNightAvg", "lastNightAvgHrv")),
        "last_night_5min_high_ms": _as_float(_get(src, "lastNight5MinHigh")),
        "weekly_avg_ms": _as_float(_get(src, "weeklyAvg")),
        "baseline_low_ms": _as_float(_get(src, "baselineBalancedLow", "baselineLow")),
        "baseline_high_ms": _as_float(_get(src, "baselineBalancedHigh", "baselineHigh")),
        "status": _get(src, "status", "hrvStatus"),
    }
