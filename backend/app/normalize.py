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

from datetime import UTC, datetime
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


def _first(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)


def _nested(obj: dict[str, Any], key: str, *names: str) -> Any:
    value = _get(obj, key)
    return _get(value, *names) if isinstance(value, dict) else None


def _timestamp_seconds(value: Any) -> int | None:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return int(parsed.timestamp())
        except ValueError:
            return None
    number = _as_float(value)
    if number is None:
        return None
    if abs(number) >= 100_000_000_000:
        number /= 1000
    return int(number)


def _local_offset(obj: dict[str, Any], gmt_names: tuple[str, ...], local_names: tuple[str, ...]) -> int | None:
    gmt = _timestamp_seconds(_get(obj, *gmt_names))
    local = _timestamp_seconds(_get(obj, *local_names))
    return local - gmt if gmt is not None and local is not None else None


def _millis_to_seconds(value: Any) -> int | None:
    number = _as_float(value)
    return int(round(number / 1000)) if number is not None else None


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
    activity_type = _get(obj, "activityType")
    if isinstance(activity_type, dict):
        activity_type = _get(activity_type, "typeKey")
    start_time = _first(
        _timestamp_seconds(_get(obj, "startTimeInSeconds", "startTimeGMT")),
        _timestamp_seconds(_get(obj, "beginTimestamp")),
    )
    return {
        "summary_id": str(key),
        "activity_id": str(activity_id) if activity_id is not None else None,
        "activity_type": activity_type,
        "activity_name": _get(obj, "activityName"),
        "start_time_seconds": start_time,
        "start_time_offset_seconds": _first(
            _as_int(_get(obj, "startTimeOffsetSeconds")),
            _local_offset(obj, ("startTimeGMT",), ("startTimeLocal",)),
        ),
        "duration_seconds": _as_int(_first(_get(obj, "durationInSeconds"), _get(obj, "duration"))),
        "distance_meters": _as_float(_first(_get(obj, "distanceInMeters"), _get(obj, "distance"))),
        "active_kilocalories": _as_int(
            _first(_get(obj, "activeKilocalories"), _get(obj, "calories"))
        ),
        "avg_hr_bpm": _as_int(
            _first(_get(obj, "averageHeartRateInBeatsPerMinute"), _get(obj, "averageHR"))
        ),
        "max_hr_bpm": _as_int(
            _first(_get(obj, "maxHeartRateInBeatsPerMinute"), _get(obj, "maxHR"))
        ),
        "avg_speed_mps": _as_float(
            _first(_get(obj, "averageSpeedInMetersPerSecond"), _get(obj, "averageSpeed"))
        ),
        "max_speed_mps": _as_float(
            _first(_get(obj, "maxSpeedInMetersPerSecond"), _get(obj, "maxSpeed"))
        ),
        "avg_pace_min_per_km": _as_float(_get(obj, "averagePaceInMinutesPerKilometer")),
        "avg_run_cadence_spm": _as_float(
            _first(
                _get(obj, "averageRunCadenceInStepsPerMinute"),
                _get(obj, "averageRunningCadenceInStepsPerMinute"),
            )
        ),
        "max_run_cadence_spm": _as_float(
            _first(
                _get(obj, "maxRunCadenceInStepsPerMinute"),
                _get(obj, "maxRunningCadenceInStepsPerMinute"),
            )
        ),
        "avg_bike_cadence_rpm": _as_float(_get(obj, "averageBikeCadenceInRoundsPerMinute")),
        "avg_swim_cadence_spm": _as_float(
            _get(obj, "averageSwimCadenceInStrokesPerMinute")
        ),
        "total_elevation_gain_m": _as_float(
            _first(_get(obj, "totalElevationGainInMeters"), _get(obj, "elevationGain"))
        ),
        "total_elevation_loss_m": _as_float(
            _first(_get(obj, "totalElevationLossInMeters"), _get(obj, "elevationLoss"))
        ),
        "starting_latitude": _as_float(
            _first(_get(obj, "startingLatitudeInDegree"), _get(obj, "startLatitude"))
        ),
        "starting_longitude": _as_float(
            _first(_get(obj, "startingLongitudeInDegree"), _get(obj, "startLongitude"))
        ),
        "steps": _as_int(_get(obj, "steps")),
        "device_name": _get(obj, "deviceName"),
        "is_parent": _as_bool_int(_get(obj, "isParent")),
        "parent_summary_id": _first(_get(obj, "parentSummaryId"), _get(obj, "parentId")),
        "manual": _as_bool_int(_first(_get(obj, "manual"), _get(obj, "manualActivity"))),
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
    summary_id = _first(_get(obj, "summaryId"), _get(obj, "uuid"))
    if not summary_id and not calendar_date:
        return None
    steps = _first(_nested(obj, "movement", "steps"), _get(obj, "steps"))
    floors = _first(
        _nested(obj, "movement", "floorsAscended"), _get(obj, "floorsClimbed")
    )
    calories = _get(obj, "calories")
    intensity = _get(obj, "intensityMinutes")
    heart_rate = _get(obj, "heartRate")
    stress = _get(obj, "stress")
    chronology = _get(obj, "wellnessChronology")
    def intensity_seconds(old_name: str, new_name: str) -> int | None:
        old_value = _get(obj, old_name)
        if old_value is not None:
            return _as_int(old_value)
        minutes = _nested(obj, "intensityMinutes", new_name)
        value = _as_int(minutes)
        return value * 60 if value is not None else None

    return {
        "summary_id": str(summary_id) if summary_id else f"daily-{calendar_date}",
        "calendar_date": calendar_date,
        "start_time_seconds": _first(
            _timestamp_seconds(_get(obj, "startTimeInSeconds")),
            _timestamp_seconds(_get(chronology, "startTimestampGmt")),
        ),
        "start_time_offset_seconds": _first(
            _as_int(_get(obj, "startTimeOffsetSeconds")),
            _local_offset(
                chronology if isinstance(chronology, dict) else {},
                ("startTimestampGmt",),
                ("startTimestampLocal",),
            ),
        ),
        "duration_seconds": _first(
            _as_int(_get(obj, "durationInSeconds")),
            _millis_to_seconds(_get(chronology, "totalDurationInMillis")),
        ),
        "steps": _as_int(_first(_get(obj, "steps"), _get(steps, "value"))),
        "steps_goal": _as_int(_first(_get(obj, "stepsGoal"), _get(steps, "goal"))),
        "distance_meters": _as_float(
            _first(_get(obj, "distanceInMeters"), _get(steps, "distanceInMeters"))
        ),
        "floors_climbed": _as_int(
            _first(_get(obj, "floorsClimbed"), _get(floors, "value"))
        ),
        "floors_climbed_goal": _as_int(
            _first(_get(obj, "floorsClimbedGoal"), _get(floors, "goal"))
        ),
        "active_kilocalories": _as_int(
            _first(_get(obj, "activeKilocalories"), _get(calories, "burnedActive"))
        ),
        "bmr_kilocalories": _as_int(
            _first(_get(obj, "bmrKilocalories"), _get(calories, "burnedResting"))
        ),
        "active_time_seconds": _as_int(_get(obj, "activeTimeInSeconds")),
        "moderate_intensity_seconds": intensity_seconds(
            "moderateIntensityDurationInSeconds", "moderate"
        ),
        "vigorous_intensity_seconds": intensity_seconds(
            "vigorousIntensityDurationInSeconds", "vigorous"
        ),
        "intensity_goal_seconds": intensity_seconds("intensityDurationGoalInSeconds", "goal"),
        "min_hr_bpm": _as_int(
            _first(_get(obj, "minHeartRateInBeatsPerMinute"), _get(heart_rate, "minValue"))
        ),
        "max_hr_bpm": _as_int(
            _first(_get(obj, "maxHeartRateInBeatsPerMinute"), _get(heart_rate, "maxValue"))
        ),
        "average_hr_bpm": _as_int(
            _first(_get(obj, "averageHeartRateInBeatsPerMinute"), _get(heart_rate, "averageValue"))
        ),
        "resting_hr_bpm": _as_int(
            _first(_get(obj, "restingHeartRateInBeatsPerMinute"), _get(heart_rate, "restingValue"))
        ),
        "avg_stress_level": _as_int(
            _first(_get(obj, "averageStressLevel"), _get(stress, "avgLevel"))
        ),
        "max_stress_level": _as_int(
            _first(_get(obj, "maxStressLevel"), _get(stress, "maxLevel"))
        ),
        "stress_duration_seconds": _first(
            _as_int(_get(obj, "stressDurationInSeconds")),
            _millis_to_seconds(_get(stress, "totalDurationInMillis")),
        ),
        "rest_stress_duration_seconds": _first(
            _as_int(_get(obj, "restStressDurationInSeconds")),
            _millis_to_seconds(_get(stress, "restDurationInMillis")),
        ),
        "activity_stress_duration_seconds": _as_int(
            _first(
                _get(obj, "activityStressDurationInSeconds"),
                _millis_to_seconds(_get(stress, "activityDurationInMillis")),
            )
        ),
        "low_stress_duration_seconds": _first(
            _as_int(_get(obj, "lowStressDurationInSeconds")),
            _millis_to_seconds(_get(stress, "lowStressDurationInMillis")),
        ),
        "medium_stress_duration_seconds": _as_int(
            _first(
                _get(obj, "mediumStressDurationInSeconds"),
                _millis_to_seconds(_get(stress, "mediumStressDurationInMillis")),
            )
        ),
        "high_stress_duration_seconds": _first(
            _as_int(_get(obj, "highStressDurationInSeconds")),
            _millis_to_seconds(_get(stress, "highStressDurationInMillis")),
        ),
        "stress_qualifier": _first(_get(obj, "stressQualifier"), _get(stress, "qualifier")),
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
    summary_id = _first(_get(obj, "summaryId"), _get(obj, "id"))
    calendar_date = _get(obj, "calendarDate")
    if not summary_id and not calendar_date:
        return None

    overall = _first(_get(obj, "overallSleepScore"), _nested(obj, "sleepScores", "overall"))
    score_value = None
    score_qualifier = _get(obj, "overallSleepScoreQualifierKey")
    if isinstance(overall, dict):
        score_value = _as_int(_get(overall, "value"))
        score_qualifier = score_qualifier or _get(overall, "qualifierKey")
    else:
        score_value = _as_int(_first(overall, _get(obj, "overallSleepScoreValue")))

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
        "start_time_seconds": _first(
            _timestamp_seconds(_get(obj, "startTimeInSeconds")),
            _timestamp_seconds(_get(obj, "sleepStartTimestampGMT")),
        ),
        "start_time_offset_seconds": _first(
            _as_int(_get(obj, "startTimeOffsetSeconds")),
            _local_offset(obj, ("sleepStartTimestampGMT",), ("sleepStartTimestampLocal",)),
        ),
        "duration_seconds": _as_int(
            _first(_get(obj, "durationInSeconds"), _get(obj, "sleepTimeSeconds"))
        ),
        "unmeasurable_seconds": _as_int(
            _first(_get(obj, "unmeasurableSleepInSeconds"), _get(obj, "unmeasurableSleepSeconds"))
        ),
        "deep_seconds": _as_int(
            _first(_get(obj, "deepSleepDurationInSeconds"), _get(obj, "deepSleepSeconds"))
        ),
        "light_seconds": _as_int(
            _first(_get(obj, "lightSleepDurationInSeconds"), _get(obj, "lightSleepSeconds"))
        ),
        "rem_seconds": _as_int(_first(_get(obj, "remSleepInSeconds"), _get(obj, "remSleepSeconds"))),
        "awake_seconds": _as_int(
            _first(_get(obj, "awakeDurationInSeconds"), _get(obj, "awakeSleepSeconds"))
        ),
        "total_nap_seconds": _as_int(
            _first(_get(obj, "totalNapDurationInSeconds"), _get(obj, "napTimeSeconds"))
        ),
        "overall_score_value": score_value,
        "overall_score_qualifier": score_qualifier,
        "avg_sleep_respiration": _first(
            avg_resp, _as_float(_get(obj, "averageRespirationValue"))
        ),  # DERIVED (mean of samples) or Garmin's average
        "avg_sleep_spo2": _first(
            avg_spo2, _as_float(_get(obj, "averageSpO2Value"))
        ),  # DERIVED (mean of samples) or Garmin's average
        "validation": _first(
            _get(obj, "validation"), _get(obj, "sleepWindowConfirmationType")
        ),
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
    if bb_level is None:
        body_battery = _get(obj, "bodyBattery")
        end_of_day = _get(body_battery, "endOfDayDynamicFeedbackEvent")
        bb_level = _first(
            _nested(obj, "bodyBattery", "latestValue"),
            _get(end_of_day, "bodyBatteryLevel"),
        )
    return {
        "summary_id": str(summary_id) if summary_id else f"stress-{calendar_date}",
        "calendar_date": calendar_date,
        "start_time_seconds": _timestamp_seconds(
            _first(_get(obj, "startTimeInSeconds"), _get(obj, "startTimeGMT"))
        ),
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
    baseline = _get(src, "baseline")
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
        "baseline_low_ms": _as_float(
            _first(
                _get(src, "baselineBalancedLow", "baselineLow"),
                _get(baseline, "balancedLow"),
            )
        ),
        "baseline_high_ms": _as_float(
            _first(
                _get(src, "baselineBalancedHigh", "baselineHigh"),
                _get(baseline, "balancedUpper"),
            )
        ),
        "status": _get(src, "status", "hrvStatus"),
    }
