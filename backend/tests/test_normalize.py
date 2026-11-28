"""Normalization tests against the real Personal API schemas."""

from __future__ import annotations

from app import normalize as norm
from tests import fixtures_api as fx


def test_daily_maps_real_fields():
    row = norm.normalize_daily(fx.DAILY)
    assert row is not None
    assert row["summary_id"] == "daily-2026-10-21"
    assert row["steps"] == 4433
    assert row["resting_hr_bpm"] == 52
    assert row["total_kilocalories"] == 2391
    assert row["body_battery_high"] == 100
    assert row["avg_spo2"] == 97.0
    # device offset derived from GMT vs Local (+3h = 10800s)
    assert row["start_time_offset_seconds"] == 10800


def test_daily_null_vs_zero():
    row = norm.normalize_daily(fx.DAILY_NO_DATA)
    assert row["steps"] == 0  # measured zero kept
    assert row["resting_hr_bpm"] is None  # missing -> null, not zero
    assert row["avg_stress_level"] == -1  # sentinel preserved


def test_daily_intensity_minutes_to_seconds():
    row = norm.normalize_daily(fx.DAILY)
    # API gives minutes; we store seconds.
    assert row["moderate_intensity_seconds"] == 0
    assert row["intensity_goal_seconds"] == 150 * 60


def test_daily_hr_samples_pairs_and_gaps():
    samples = norm.normalize_daily_hr_samples(fx.DAILY_HEART_RATE)
    # 4 input pairs, one with null bpm -> 3 rows, gap skipped (not zeroed).
    assert len(samples) == 3
    assert samples[0]["offset_seconds"] == 0
    assert samples[0]["heart_rate_bpm"] == 55
    assert samples[-1]["heart_rate_bpm"] == 58


def test_sleep_real_schema():
    row = norm.normalize_sleep(fx.SLEEP)
    assert row["summary_id"] == "sleep-2026-10-21"
    assert row["duration_seconds"] == 27591
    assert row["deep_seconds"] == 3960
    assert row["overall_score_value"] == 87
    assert row["overall_score_qualifier"] == "GOOD"
    assert row["avg_sleep_spo2"] == 97.0
    assert row["validation"] == "enhanced_confirmed_final"


def test_hrv_single_and_range():
    row = norm.normalize_hrv(fx.HRV)
    assert row["summary_id"] == "hrv-2026-10-21"
    assert row["last_night_avg_ms"] == 63.0
    assert row["weekly_avg_ms"] == 54.0
    assert row["baseline_low_ms"] == 50.0
    assert row["baseline_high_ms"] == 73.0
    assert row["status"] == "BALANCED"

    rows = norm.normalize_hrv_range(fx.HRV_RANGE)
    assert len(rows) == 2
    assert {r["calendar_date"] for r in rows} == {"2026-10-20", "2026-10-21"}


def test_body_battery_report_array():
    cal, samples = norm.normalize_body_battery_report(fx.BODY_BATTERY_REPORT[0], "UTC")
    assert cal == "2026-10-20"
    assert len(samples) == 3
    # offsets are relative to the day start (UTC midnight 2026-10-20 = 1792454400)
    assert samples[0]["offset_seconds"] == 1792011600 - 1792454400
    assert samples[0]["body_battery_value"] == 27
    assert samples[1]["body_battery_value"] == 91


def test_stress_range():
    rows = norm.normalize_stress_range(fx.STRESS_RANGE)
    assert rows[0]["calendar_date"] == "2026-10-20"
    assert rows[0]["_overall_stress"] == 29


def test_activity_strength_no_gps():
    row = norm.normalize_activity(fx.ACTIVITY)
    assert row["summary_id"] == "24734466614"
    assert row["activity_type"] == "strength_training"
    assert row["active_kilocalories"] is None  # "calories" is total energy
    assert row["avg_hr_bpm"] == 112
    assert row["starting_latitude"] is None  # no GPS for strength
    # avg speed 0 -> no pace (not a divide-by-zero)
    assert row["avg_pace_min_per_km"] is None


def test_activity_run_has_gps_and_pace():
    row = norm.normalize_activity(fx.ACTIVITY_RUN)
    assert row["activity_type"] == "running"
    assert row["distance_meters"] == 10000.0
    assert row["starting_latitude"] == 60.17
    assert row["avg_pace_min_per_km"] is not None
    assert row["start_time_offset_seconds"] == 10800


def test_activity_without_id_returns_none():
    assert norm.normalize_activity({"activityName": "x"}) is None


def test_hr_zones_normalize():
    items = [
        {
            "sport": "RUNNING",
            "trainingMethod": "HR_MAX",
            "restingHeartRateUsed": 55,
            "lactateThresholdHeartRateUsed": 171,
            "maxHeartRateUsed": 197,
            "zone1Floor": 99,
            "zone2Floor": 118,
            "zone3Floor": 138,
            "zone4Floor": 158,
            "zone5Floor": 177,
        }
    ]
    rows = norm.normalize_hr_zones(items)
    assert len(rows) == 1
    assert rows[0]["sport"] == "RUNNING"
    assert rows[0]["zone5_floor"] == 177
    assert rows[0]["max_hr_used"] == 197


def test_fitness_age_normalize():
    obj = {
        "chronologicalAge": 45,
        "fitnessAge": 46.76,
        "achievableFitnessAge": 38.9,
        "previousFitnessAge": 45.8,
        "components": {
            "rhr": {"value": 53},
            "bmi": {"value": 34.3, "targetValue": 21.5},
            "vigorousDaysAvg": {"value": 0.8, "targetValue": 3},
            "vigorousMinutesAvg": {"value": 50.0, "targetValue": 75},
        },
        "lastUpdated": "2026-10-22T00:00:00.0",
    }
    row = norm.normalize_fitness_age(obj)
    assert row["calendar_date"] == "2026-10-22"
    assert row["fitness_age"] == 46.76
    assert row["rhr_value"] == 53
    assert row["bmi_value"] == 34.3
    assert row["bmi_target"] == 21.5
    assert row["components_json"] is not None


def test_fitness_age_without_date_returns_none():
    assert norm.normalize_fitness_age({"fitnessAge": 40}) is None


def test_weight_range_normalize():
    obj = {
        "dailyWeightSummaries": [
            {
                "summaryDate": "2026-10-06",
                "latestWeight": {"weight": 98900.0, "bmi": None, "sourceType": "MANUAL"},
            },
            {
                "summaryDate": "2026-10-08",
                "latestWeight": {"weight": 98100.0, "bmi": 30.1, "sourceType": "INDEX_SCALE"},
            },
        ]
    }
    rows = norm.normalize_weight_range(obj)
    assert len(rows) == 2
    assert rows[0]["calendar_date"] == "2026-10-06"
    assert rows[0]["weight_grams"] == 98900.0  # grams preserved (source unit)
    assert rows[1]["bmi"] == 30.1


def test_weight_range_empty():
    assert norm.normalize_weight_range({"dailyWeightSummaries": []}) == []
