"""Tests for the single-activity coach export builder."""

from __future__ import annotations

from app import normalize as norm
from app.db.repository import Repository
from app.export import build_activity_coach_export
from tests import fixtures_api as fx


def _seed_run_with_samples(repo: Repository):
    repo.upsert_activity(norm.normalize_activity(fx.ACTIVITY_RUN))
    # Build a simple 300s run: steady distance, HR rising (drift), some elevation.
    samples = []
    for i in range(0, 300, 5):
        frac = i / 300
        samples.append(
            {
                "sample_index": i // 5,
                "offset_seconds": i,
                "clock_time_seconds": 1000 + i,
                "latitude": 60.17 + i * 1e-5,
                "longitude": 24.94 + i * 1e-5,
                "elevation_meters": 10 + 5 * frac,
                "heart_rate_bpm": int(140 + 30 * frac),  # 140 -> 170
                "speed_mps": 3.0,  # steady pace
                "cadence": 82.0,
                "power_watts": 250.0,
                "distance_meters": 3.0 * i,  # 3 m/s
                "temperature_celsius": 12.0,
                "source": "fit",
            }
        )
    repo.replace_activity_samples("111", samples)
    repo.commit()


def test_export_structure_and_derived(repo: Repository):
    _seed_run_with_samples(repo)
    row = repo.activity("111")
    samples = repo.activity_samples("111")
    out = build_activity_coach_export(row, samples, "metric")

    assert out["meta"]["schema"] == "coach-export/1"
    assert out["activity"]["activityType"] == "running"
    d = out["derived"]
    assert d["sampleCount"] == len(samples)
    # HR zones present (maxHR from activity summary = 178)
    assert d["hrZones"] is not None
    assert sum(z["seconds"] for z in d["hrZones"]["zones"]) > 0
    # splits: 300s * 3 m/s = 900m < 1000m, so no full km split
    assert d["splitsPerKm"] is None
    # decoupling computed (HR rose at steady pace -> positive drift)
    assert d["aerobicDecoupling"] is not None
    assert d["aerobicDecoupling"]["decouplingPercent"] > 0
    # elevation profile
    assert d["elevationProfile"]["gainMeters"] >= 4
    # series downsampled, capabilities flagged
    assert out["capabilities"]["gps"] is True
    assert len(out["series"]["points"]) <= 120


def test_export_handles_no_samples(repo: Repository):
    repo.upsert_activity(norm.normalize_activity(fx.ACTIVITY))  # strength, no samples
    repo.commit()
    row = repo.activity("24734466614")
    out = build_activity_coach_export(row, [], "metric")
    assert out["derived"]["sampleCount"] == 0
    assert out["derived"]["hrZones"] is None
    assert out["series"]["points"] == []
    assert out["capabilities"]["gps"] is False


def test_splits_for_longer_run(repo: Repository):
    repo.upsert_activity(norm.normalize_activity(fx.ACTIVITY_RUN))
    # 2500m run over 600s -> at least 2 full-km splits.
    samples = []
    for i in range(0, 600, 5):
        samples.append(
            {
                "sample_index": i // 5,
                "offset_seconds": i,
                "clock_time_seconds": 1000 + i,
                "latitude": None,
                "longitude": None,
                "elevation_meters": 10.0,
                "heart_rate_bpm": 150,
                "speed_mps": 4.1667,
                "cadence": 85.0,
                "power_watts": None,
                "distance_meters": 4.1667 * i,
                "temperature_celsius": None,
                "source": "fit",
            }
        )
    repo.replace_activity_samples("111", samples)
    repo.commit()
    out = build_activity_coach_export(repo.activity("111"), repo.activity_samples("111"), "metric")
    splits = out["derived"]["splitsPerKm"]
    assert splits is not None and len(splits) >= 2
    assert all(s["distanceMeters"] == 1000 for s in splits)


def _seed_week_of_health(repo: Repository):
    """Seed 8 days so the latest day has a 7-day prior baseline."""
    from datetime import date, timedelta

    base = date(2026, 10, 15)
    for i in range(8):
        d = (base + timedelta(days=i)).isoformat()
        rhr = 50 + (5 if i == 7 else 0)  # last day elevated
        repo.upsert_daily(
            {
                "summary_id": f"daily-{d}",
                "calendar_date": d,
                "steps": 8000 + i * 100,
                "resting_hr_bpm": rhr,
                "avg_stress_level": 30,
                "body_battery_high": 90,
                "body_battery_low": 20,
            }
        )
        repo.upsert_sleep(
            {
                "summary_id": f"sleep-{d}",
                "calendar_date": d,
                "duration_seconds": 27000,
                "overall_score_value": 80,
            }
        )
        repo.upsert_hrv(
            {
                "summary_id": f"hrv-{d}",
                "calendar_date": d,
                "last_night_avg_ms": 50,
                "status": "BALANCED",
            }
        )
    repo.commit()


def test_health_snapshot_structure_and_baseline(repo: Repository):
    from app.export import build_health_snapshot_export

    _seed_week_of_health(repo)
    daily = repo.latest_daily()
    sleep = repo.latest_sleep()
    hrv = repo.latest_hrv()
    anchor = daily["calendar_date"]
    out = build_health_snapshot_export(
        daily=daily,
        sleep=sleep,
        hrv=hrv,
        body_battery=[],
        daily_7=repo.daily_range("2026-10-16", anchor),
        daily_30=repo.daily_range("2026-09-16", anchor),
        sleep_7=repo.sleep_range("2026-10-16", anchor),
        sleep_30=repo.sleep_range("2026-09-16", anchor),
        hrv_7=repo.hrv_range("2026-10-16", anchor),
        hrv_30=repo.hrv_range("2026-09-16", anchor),
        unit_system="metric",
    )
    assert out["meta"]["schema"] == "health-snapshot/1"
    assert out["available"]["daily"] is True
    rhr = out["comparisons"]["restingHeartRateBpm"]["7d"]
    assert rhr["today"] == 55  # elevated last day
    assert rhr["delta"] > 0  # above the prior baseline of 50
    assert rhr["vsBaseline"] in ("above_typical", "typical")
    # trends present and chronological
    assert len(out["trends"]["restingHeartRateBpm"]) >= 7


def test_health_snapshot_negative_stress_nulled(repo: Repository):
    from app.export import build_health_snapshot_export

    repo.upsert_daily(
        {"summary_id": "daily-2026-10-20", "calendar_date": "2026-10-20",
         "resting_hr_bpm": 52, "avg_stress_level": -1, "steps": 100}
    )
    repo.commit()
    daily = repo.latest_daily()
    out = build_health_snapshot_export(
        daily=daily, sleep=None, hrv=None, body_battery=[],
        daily_7=[daily], daily_30=[daily], sleep_7=[], sleep_30=[],
        hrv_7=[], hrv_30=[], unit_system="metric",
    )
    # -1 sentinel must not appear as a stress value.
    assert out["comparisons"]["stressLevel"]["7d"] is None
