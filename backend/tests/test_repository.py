"""Persistence tests: idempotent upserts, no duplicates, child-row replacement."""

from __future__ import annotations

from app import normalize as norm
from app.db.repository import Repository
from tests import fixtures_api as fx


def test_daily_upsert_idempotent(repo: Repository):
    row = norm.normalize_daily(fx.DAILY)
    repo.upsert_daily(row)
    repo.upsert_daily(row)
    repo.commit()
    rows = repo.daily_range("2026-10-01", "2026-10-31")
    assert len(rows) == 1
    assert rows[0]["steps"] == 4433


def test_daily_upsert_updates(repo: Repository):
    row = norm.normalize_daily(fx.DAILY)
    repo.upsert_daily(row)
    repo.commit()
    updated = dict(row)
    updated["steps"] = 9999
    repo.upsert_daily(updated)
    repo.commit()
    rows = repo.daily_range("2026-10-01", "2026-10-31")
    assert len(rows) == 1 and rows[0]["steps"] == 9999
    assert rows[0]["first_seen_at"] is not None


def test_activity_upsert_idempotent(repo: Repository):
    row = norm.normalize_activity(fx.ACTIVITY)
    repo.upsert_activity(row)
    repo.upsert_activity(row)
    repo.commit()
    assert repo.count_activities() == 1
    got = repo.activity("24734466614")
    assert got["activity_type"] == "strength_training"


def test_activity_samples_replace_not_append(repo: Repository):
    repo.upsert_activity(norm.normalize_activity(fx.ACTIVITY))
    samples = [
        {
            "sample_index": 0,
            "offset_seconds": 0,
            "clock_time_seconds": 1000,
            "latitude": None,
            "longitude": None,
            "elevation_meters": None,
            "heart_rate_bpm": 100,
            "speed_mps": None,
            "cadence": None,
            "power_watts": None,
            "distance_meters": None,
            "temperature_celsius": None,
            "source": "fit",
        }
    ]
    repo.replace_activity_samples("24734466614", samples)
    repo.replace_activity_samples("24734466614", samples)
    repo.commit()
    stored = repo.activity_samples("24734466614")
    assert len(stored) == 1
    assert repo.activity("24734466614")["has_details"] == 1


def test_body_battery_samples_round_trip(repo: Repository):
    cal, samples = norm.normalize_body_battery_report(fx.BODY_BATTERY_REPORT[0])
    repo.replace_body_battery_samples(cal, samples)
    repo.commit()
    rows = repo.body_battery_for_date(cal)
    assert [r["body_battery_value"] for r in rows] == [27, 91, 86]
    assert repo.latest_body_battery_date() == "2026-10-20"


def test_daily_hr_samples_round_trip(repo: Repository):
    samples = norm.normalize_daily_hr_samples(fx.DAILY_HEART_RATE)
    repo.replace_daily_hr_samples("2026-10-21", samples)
    repo.commit()
    n = repo.conn.execute(
        "SELECT COUNT(*) AS c FROM daily_hr_samples WHERE calendar_date='2026-10-21'"
    ).fetchone()["c"]
    assert n == 3


def test_hrv_upsert(repo: Repository):
    repo.upsert_hrv(norm.normalize_hrv(fx.HRV))
    repo.commit()
    h = repo.latest_hrv()
    assert h["status"] == "BALANCED"
    assert h["last_night_avg_ms"] == 63.0


def test_sync_state(repo: Repository):
    repo.update_sync_state("daily", 1792000000)
    repo.commit()
    st = repo.get_sync_state("daily")
    assert st["last_synced_through"] == 1792000000
