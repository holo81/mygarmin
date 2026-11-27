"""Presentation helpers: convert stored rows into frontend-friendly dicts.

Principles:
  * We NEVER mutate stored source values. Conversions (e.g. m/s -> pace) happen
    here, at presentation time, and are clearly named.
  * NULL stays null in the JSON so the UI can distinguish "no data" from zero.
  * Local time is derived from the stored UTC epoch + device offset, so the
    frontend can show device-local time without us guessing a timezone.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC
from typing import Any


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def local_iso(start_time_seconds: int | None, offset_seconds: int | None) -> str | None:
    """Reconstruct device-local ISO-8601 (with offset) from UTC epoch + offset.

    Returns a string like '2026-02-08T07:30:00+02:00'. Returns None if no time.
    """
    if start_time_seconds is None:
        return None
    from datetime import datetime, timedelta, timezone

    off = offset_seconds or 0
    tz = timezone(timedelta(seconds=off))
    dt = datetime.fromtimestamp(start_time_seconds + 0, tz=UTC).astimezone(tz)
    return dt.isoformat()


def pace_from_speed(speed_mps: float | None) -> float | None:
    """Convert speed (m/s) to pace (min/km). None if not moving / no data."""
    if speed_mps is None or speed_mps <= 0:
        return None
    return (1000.0 / speed_mps) / 60.0


def activity_summary_view(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    return {
        "summaryId": d["summary_id"],
        "activityId": d.get("activity_id"),
        "activityType": d.get("activity_type"),
        "activityName": d.get("activity_name"),
        "startTimeSeconds": d.get("start_time_seconds"),
        "startTimeOffsetSeconds": d.get("start_time_offset_seconds"),
        "startLocalIso": local_iso(
            d.get("start_time_seconds"), d.get("start_time_offset_seconds")
        ),
        "durationSeconds": d.get("duration_seconds"),
        "distanceMeters": d.get("distance_meters"),
        "activeKilocalories": d.get("active_kilocalories"),
        "avgHrBpm": d.get("avg_hr_bpm"),
        "maxHrBpm": d.get("max_hr_bpm"),
        "avgSpeedMps": d.get("avg_speed_mps"),
        "maxSpeedMps": d.get("max_speed_mps"),
        # Prefer Garmin's own pace; otherwise derive from speed (documented as derived).
        "avgPaceMinPerKm": d.get("avg_pace_min_per_km")
        if d.get("avg_pace_min_per_km") is not None
        else pace_from_speed(d.get("avg_speed_mps")),
        "avgRunCadenceSpm": d.get("avg_run_cadence_spm"),
        "maxRunCadenceSpm": d.get("max_run_cadence_spm"),
        "avgBikeCadenceRpm": d.get("avg_bike_cadence_rpm"),
        "avgSwimCadenceSpm": d.get("avg_swim_cadence_spm"),
        "totalElevationGainM": d.get("total_elevation_gain_m"),
        "totalElevationLossM": d.get("total_elevation_loss_m"),
        "startingLatitude": d.get("starting_latitude"),
        "startingLongitude": d.get("starting_longitude"),
        "steps": d.get("steps"),
        "deviceName": d.get("device_name"),
        "manual": bool(d["manual"]) if d.get("manual") is not None else None,
        "hasDetails": bool(d.get("has_details")),
        "hasFit": bool(d.get("has_fit")),
    }


def daily_view(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    return {
        "calendarDate": d.get("calendar_date"),
        "steps": d.get("steps"),
        "stepsGoal": d.get("steps_goal"),
        "distanceMeters": d.get("distance_meters"),
        "floorsClimbed": d.get("floors_climbed"),
        "floorsClimbedGoal": d.get("floors_climbed_goal"),
        "activeKilocalories": d.get("active_kilocalories"),
        "bmrKilocalories": d.get("bmr_kilocalories"),
        "totalKilocalories": (
            (d.get("active_kilocalories") or 0) + (d.get("bmr_kilocalories") or 0)
            if d.get("active_kilocalories") is not None
            and d.get("bmr_kilocalories") is not None
            else None
        ),
        "activeTimeSeconds": d.get("active_time_seconds"),
        "moderateIntensitySeconds": d.get("moderate_intensity_seconds"),
        "vigorousIntensitySeconds": d.get("vigorous_intensity_seconds"),
        "intensityGoalSeconds": d.get("intensity_goal_seconds"),
        "intensityMinutes": (
            _intensity_minutes(
                d.get("moderate_intensity_seconds"), d.get("vigorous_intensity_seconds")
            )
        ),
        "minHrBpm": d.get("min_hr_bpm"),
        "maxHrBpm": d.get("max_hr_bpm"),
        "averageHrBpm": d.get("average_hr_bpm"),
        "restingHrBpm": d.get("resting_hr_bpm"),
        "avgStressLevel": _stress_or_none(d.get("avg_stress_level")),
        "maxStressLevel": d.get("max_stress_level"),
        "stressQualifier": d.get("stress_qualifier"),
    }


def _intensity_minutes(moderate_s: int | None, vigorous_s: int | None) -> int | None:
    """Garmin intensity minutes: vigorous counts double. DERIVED metric."""
    if moderate_s is None and vigorous_s is None:
        return None
    m = (moderate_s or 0) // 60
    v = (vigorous_s or 0) // 60
    return m + 2 * v


def _stress_or_none(v: int | None) -> int | None:
    """Preserve -1/-2 sentinels as null (they mean 'not enough data')."""
    if v is None or v < 0:
        return None
    return v


def sleep_view(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    return {
        "calendarDate": d.get("calendar_date"),
        "startTimeSeconds": d.get("start_time_seconds"),
        "startTimeOffsetSeconds": d.get("start_time_offset_seconds"),
        "startLocalIso": local_iso(
            d.get("start_time_seconds"), d.get("start_time_offset_seconds")
        ),
        "durationSeconds": d.get("duration_seconds"),
        "unmeasurableSeconds": d.get("unmeasurable_seconds"),
        "deepSeconds": d.get("deep_seconds"),
        "lightSeconds": d.get("light_seconds"),
        "remSeconds": d.get("rem_seconds"),
        "awakeSeconds": d.get("awake_seconds"),
        "totalNapSeconds": d.get("total_nap_seconds"),
        "overallScoreValue": d.get("overall_score_value"),
        "overallScoreQualifier": d.get("overall_score_qualifier"),
        "avgSleepRespiration": d.get("avg_sleep_respiration"),  # derived
        "avgSleepSpo2": d.get("avg_sleep_spo2"),  # derived
        "validation": d.get("validation"),
    }


def hrv_view(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    return {
        "calendarDate": d.get("calendar_date"),
        "lastNightAvgMs": d.get("last_night_avg_ms"),
        "lastNight5MinHighMs": d.get("last_night_5min_high_ms"),
        "weeklyAvgMs": d.get("weekly_avg_ms"),
        "baselineLowMs": d.get("baseline_low_ms"),
        "baselineHighMs": d.get("baseline_high_ms"),
        "status": d.get("status"),
    }


def sample_view(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    return {
        "index": d.get("sample_index"),
        "offsetSeconds": d.get("offset_seconds"),
        "clockTimeSeconds": d.get("clock_time_seconds"),
        "latitude": d.get("latitude"),
        "longitude": d.get("longitude"),
        "elevationMeters": d.get("elevation_meters"),
        "heartRateBpm": d.get("heart_rate_bpm"),
        "speedMps": d.get("speed_mps"),
        "paceMinPerKm": pace_from_speed(d.get("speed_mps")),
        "cadence": d.get("cadence"),
        "powerWatts": d.get("power_watts"),
        "distanceMeters": d.get("distance_meters"),
        "temperatureCelsius": d.get("temperature_celsius"),
    }
