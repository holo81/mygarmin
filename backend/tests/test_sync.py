"""Sync engine tests against the real per-day/range endpoint model."""

from __future__ import annotations

import re

import httpx
import respx

from app.config import Settings
from app.db.database import connect
from app.db.repository import Repository
from app.garmin.client import GarminClient
from app.sync import SyncEngine
from tests import fixtures_api as fx


def _mock_ok(settings: Settings):
    respx.post(settings.garmin_token_url).mock(
        return_value=httpx.Response(200, json=fx.TOKEN_RESPONSE)
    )
    base = settings.garmin_api_base_url.rstrip("/")
    # Per-day endpoints respond with the fixture regardless of the date param.
    respx.get(base + settings.garmin_path_daily).mock(
        return_value=httpx.Response(200, json=fx.DAILY)
    )
    respx.get(base + settings.garmin_path_sleep).mock(
        return_value=httpx.Response(200, json=fx.SLEEP)
    )
    respx.get(url__regex=re.escape(base) + r"/hrv-service/hrv/\d{4}-\d{2}-\d{2}$").mock(
        return_value=httpx.Response(200, json=fx.HRV)
    )
    respx.get(base + settings.garmin_path_daily_heart_rate).mock(
        return_value=httpx.Response(200, json=fx.DAILY_HEART_RATE)
    )
    respx.get(base + settings.garmin_path_body_battery).mock(
        return_value=httpx.Response(200, json=fx.BODY_BATTERY_REPORT)
    )
    respx.get(base + settings.garmin_path_activities_search).mock(
        return_value=httpx.Response(200, json=[fx.ACTIVITY, fx.ACTIVITY_RUN])
    )
    respx.get(base + settings.garmin_path_hr_zones).mock(
        return_value=httpx.Response(200, json=fx.HR_ZONES)
    )
    respx.get(url__regex=re.escape(base) + r"/fitnessage-service/.+").mock(
        return_value=httpx.Response(200, json=fx.FITNESS_AGE)
    )
    respx.get(url__regex=re.escape(base) + r"/weight-service/weight/range/.+").mock(
        return_value=httpx.Response(200, json=fx.WEIGHT_RANGE)
    )


@respx.mock
def test_full_sync_all_categories(settings: Settings):
    _mock_ok(settings)
    engine = SyncEngine(settings, client=GarminClient(settings))
    try:
        # 2-day window to keep per-day calls small.
        now = 1792656000  # ~2026-10-21
        outcome = engine.run(start_time=now - 30*86400, end_time=now, trigger="test")
    finally:
        engine.close()
    assert outcome.status == "success"

    conn = connect(settings.database_file)
    repo = Repository(conn)
    try:
        assert repo.latest_daily()["steps"] == 4433
        assert repo.latest_sleep()["overall_score_value"] == 87
        assert repo.latest_hrv()["status"] == "BALANCED"
        assert repo.count_activities() == 2
        assert repo.latest_body_battery_date() is not None
    finally:
        conn.close()


@respx.mock
def test_repeated_sync_no_duplicates(settings: Settings):
    _mock_ok(settings)
    now = 1792656000
    for _ in range(2):
        engine = SyncEngine(settings, client=GarminClient(settings))
        try:
            engine.run(start_time=now - 30*86400, end_time=now, trigger="test")
        finally:
            engine.close()
    conn = connect(settings.database_file)
    try:
        assert conn.execute("SELECT COUNT(*) c FROM activities").fetchone()["c"] == 2
        # daily keyed by calendar date; fixture always same date -> 1 row
        assert conn.execute("SELECT COUNT(*) c FROM daily_summaries").fetchone()["c"] == 1
    finally:
        conn.close()


@respx.mock
def test_partial_failure_isolates(settings: Settings, monkeypatch):
    monkeypatch.setattr("app.garmin.client.time.sleep", lambda *_: None)
    respx.post(settings.garmin_token_url).mock(
        return_value=httpx.Response(200, json=fx.TOKEN_RESPONSE)
    )
    base = settings.garmin_api_base_url.rstrip("/")
    respx.get(base + settings.garmin_path_daily).mock(
        return_value=httpx.Response(200, json=fx.DAILY)
    )
    respx.get(base + settings.garmin_path_sleep).mock(return_value=httpx.Response(500))
    respx.get(url__regex=re.escape(base) + r"/hrv-service/hrv/\d{4}-\d{2}-\d{2}$").mock(
        return_value=httpx.Response(200, json=fx.HRV)
    )
    respx.get(base + settings.garmin_path_daily_heart_rate).mock(
        return_value=httpx.Response(200, json=fx.DAILY_HEART_RATE)
    )
    respx.get(base + settings.garmin_path_body_battery).mock(
        return_value=httpx.Response(200, json=fx.BODY_BATTERY_REPORT)
    )
    respx.get(base + settings.garmin_path_activities_search).mock(
        return_value=httpx.Response(200, json=[])
    )

    engine = SyncEngine(settings, client=GarminClient(settings))
    try:
        now = 1792656000
        outcome = engine.run(start_time=now - 30*86400, end_time=now, trigger="test")
    finally:
        engine.close()

    assert outcome.status == "partial"
    statuses = {c.category: c.status for c in outcome.categories}
    assert statuses["sleep"] == "failed"
    assert statuses["daily"] == "success"
    conn = connect(settings.database_file)
    try:
        assert conn.execute("SELECT COUNT(*) c FROM daily_summaries").fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) c FROM sleep_summaries").fetchone()["c"] == 0
    finally:
        conn.close()


@respx.mock
def test_auth_failure_aborts(settings: Settings):
    respx.post(settings.garmin_token_url).mock(return_value=httpx.Response(401))
    engine = SyncEngine(settings, client=GarminClient(settings))
    try:
        outcome = engine.run(start_time=1, end_time=2, trigger="test")
    finally:
        engine.close()
    assert outcome.status == "failed"


@respx.mock
def test_data_survives_restart(settings: Settings):
    _mock_ok(settings)
    now = 1792656000
    engine = SyncEngine(settings, client=GarminClient(settings))
    try:
        engine.run(start_time=now - 30*86400, end_time=now, trigger="test")
    finally:
        engine.close()
    conn = connect(settings.database_file)
    repo = Repository(conn)
    try:
        assert repo.latest_daily() is not None
        assert repo.count_activities() == 2
    finally:
        conn.close()


def test_incremental_window_ignores_retired_categories(settings: Settings, monkeypatch):
    conn = connect(settings.database_file)
    repo = Repository(conn)
    repo.update_sync_state("dailies", 1_000_000)  # retired name, must not pin the window
    repo.update_sync_state("daily", 2_000_000)
    repo.commit()
    conn.close()
    seen = {}
    engine = SyncEngine(settings)
    monkeypatch.setattr(engine, "run", lambda **kw: seen.update(kw))
    engine.incremental()
    assert seen["start_time"] == 2_000_000 - 86400
