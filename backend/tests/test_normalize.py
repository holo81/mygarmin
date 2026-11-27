"""Normalization tests: field mapping, null vs zero, sentinels, derived values."""

from __future__ import annotations

from app import normalize as norm
from tests import fixtures_api as fx


def test_daily_maps_documented_fields():
    row = norm.normalize_daily(fx.DAILY)
    assert row is not None
    assert row["summary_id"] == "x111-daily-1"
    assert row["steps"] == 12543
    assert row["resting_hr_bpm"] == 52
    assert row["active_kilocalories"] == 856
    assert row["moderate_intensity_seconds"] == 1800
    assert row["stress_qualifier"] == "balanced"


def test_daily_null_vs_zero_preserved():
    row = norm.normalize_daily(fx.DAILY_NO_DATA)
    assert row is not None
    # steps measured zero stays zero
    assert row["steps"] == 0
    # resting HR absent -> None (NOT zero)
    assert row["resting_hr_bpm"] is None
    # avg stress sentinel -1 is preserved as-is for the presenter to hide
    assert row["avg_stress_level"] == -1


def test_daily_hr_samples_expand():
    samples = norm.normalize_daily_hr_samples(fx.DAILY)
    assert {"calendar_date": "2026-02-08", "offset_seconds": 0, "heart_rate_bpm": 75} in samples
    assert len(samples) == 3


def test_case_insensitive_field_lookup():
    # PascalCase (export-doc style) must also work.
    pascal = {"CalendarDate": "2026-02-08", "Steps": 100, "SummaryId": "p1"}
    row = norm.normalize_daily(pascal)
    assert row["steps"] == 100
    assert row["calendar_date"] == "2026-02-08"


def test_sleep_stages_and_derived_means():
    row = norm.normalize_sleep(fx.SLEEP)
    assert row["deep_seconds"] == 7200
    assert row["overall_score_value"] == 85
    assert row["overall_score_qualifier"] == "GOOD"
    # derived mean respiration = (14 + 16) / 2
    assert row["avg_sleep_respiration"] == 15.0
    assert row["avg_sleep_spo2"] == 96.0

    stages = norm.normalize_sleep_stages(fx.SLEEP)
    assert {"stage": "deep", "start_time_seconds": 1675810000, "end_time_seconds": 1675817200} in stages
    assert len(stages) == 3


def test_stress_samples_keep_sentinels():
    samples = norm.normalize_stress_samples(fx.STRESS)
    values = {s["offset_seconds"]: s["stress_value"] for s in samples}
    assert values[0] == 20
    # -2 (large motion) sentinel preserved, not dropped or zeroed
    assert values[180] == -2
    bb = norm.normalize_body_battery_samples(fx.STRESS)
    assert bb[0]["body_battery_value"] == 60


def test_stress_body_battery_level():
    row = norm.normalize_stress(fx.STRESS)
    assert row["body_battery_level"] == "MODERATE"


def test_hrv_nested_summary():
    row = norm.normalize_hrv(fx.HRV)
    assert row["last_night_avg_ms"] == 45
    assert row["weekly_avg_ms"] == 42
    assert row["status"] == "BALANCED"
    assert row["baseline_low_ms"] == 38


def test_activity_normalizes_and_keys_on_summary_id():
    row = norm.normalize_activity(fx.ACTIVITY)
    assert row["summary_id"] == "x111-act-1"
    assert row["activity_type"] == "RUNNING"
    assert row["distance_meters"] == 10000.0
    assert row["avg_hr_bpm"] == 152
    assert row["manual"] == 0


def test_activity_samples_compute_offsets():
    samples = norm.normalize_activity_samples(fx.ACTIVITY_DETAILS)
    assert len(samples) == 2
    assert samples[0]["offset_seconds"] == 0
    assert samples[1]["offset_seconds"] == 10
    assert samples[1]["heart_rate_bpm"] == 150
    assert samples[0]["cadence"] == 160.0


def test_activity_without_id_returns_none():
    assert norm.normalize_activity({"activityType": "RUNNING"}) is None
