"""Sync engine tests: end-to-end pull->store, idempotency, partial failure, auth fail."""

from __future__ import annotations

import httpx
import respx

from app.config import Settings
from app.db.database import connect
from app.db.repository import Repository
from app.garmin.client import GarminClient
from app.sync import SyncEngine
from tests import fixtures_api as fx


def _mock_all_ok(settings: Settings):
    respx.post(settings.garmin_token_url).mock(
        return_value=httpx.Response(200, json=fx.TOKEN_RESPONSE)
    )
    base = settings.garmin_api_base_url.rstrip("/")
    respx.get(base + settings.garmin_path_dailies).mock(
        return_value=httpx.Response(200, json=[fx.DAILY])
    )
    respx.get(base + settings.garmin_path_sleeps).mock(
        return_value=httpx.Response(200, json=[fx.SLEEP])
    )
    respx.get(base + settings.garmin_path_stress).mock(
        return_value=httpx.Response(200, json=[fx.STRESS])
    )
    respx.get(base + settings.garmin_path_hrv).mock(
        return_value=httpx.Response(200, json=[fx.HRV])
    )
    respx.get(base + settings.garmin_path_activities).mock(
        return_value=httpx.Response(200, json=[fx.ACTIVITY])
    )


@respx.mock
def test_full_sync_stores_all_categories(settings: Settings):
    _mock_all_ok(settings)
    engine = SyncEngine(settings, client=GarminClient(settings))
    try:
        outcome = engine.run(start_time=1675832400, end_time=1675918800, trigger="test")
    finally:
        engine.close()
    assert outcome.status == "success"
    assert outcome.total_records == 5  # 1 per category

    conn = connect(settings.database_file)
    repo = Repository(conn)
    try:
        assert repo.count_activities() == 1
        assert repo.latest_daily()["steps"] == 12543
        assert repo.latest_sleep()["deep_seconds"] == 7200
        assert repo.latest_hrv()["status"] == "BALANCED"
        # raw payloads archived
        n = conn.execute("SELECT COUNT(*) AS c FROM raw_payloads").fetchone()["c"]
        assert n >= 5
    finally:
        conn.close()


@respx.mock
def test_repeated_sync_no_duplicates(settings: Settings):
    _mock_all_ok(settings)
    for _ in range(2):
        engine = SyncEngine(settings, client=GarminClient(settings))
        try:
            engine.run(start_time=1675832400, end_time=1675918800, trigger="test")
        finally:
            engine.close()

    conn = connect(settings.database_file)
    try:
        assert conn.execute("SELECT COUNT(*) AS c FROM activities").fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) AS c FROM daily_summaries").fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) AS c FROM sleep_summaries").fetchone()["c"] == 1
    finally:
        conn.close()


@respx.mock
def test_partial_failure_preserves_other_categories(settings: Settings, monkeypatch):
    monkeypatch.setattr("app.garmin.client.time.sleep", lambda *_: None)
    respx.post(settings.garmin_token_url).mock(
        return_value=httpx.Response(200, json=fx.TOKEN_RESPONSE)
    )
    base = settings.garmin_api_base_url.rstrip("/")
    respx.get(base + settings.garmin_path_dailies).mock(
        return_value=httpx.Response(200, json=[fx.DAILY])
    )
    # sleeps fails persistently
    respx.get(base + settings.garmin_path_sleeps).mock(
        return_value=httpx.Response(500, text="down")
    )
    respx.get(base + settings.garmin_path_stress).mock(
        return_value=httpx.Response(200, json=[fx.STRESS])
    )
    respx.get(base + settings.garmin_path_hrv).mock(
        return_value=httpx.Response(200, json=[fx.HRV])
    )
    respx.get(base + settings.garmin_path_activities).mock(
        return_value=httpx.Response(200, json=[fx.ACTIVITY])
    )

    engine = SyncEngine(settings, client=GarminClient(settings))
    try:
        outcome = engine.run(start_time=1675832400, end_time=1675918800, trigger="test")
    finally:
        engine.close()

    assert outcome.status == "partial"
    statuses = {c.category: c.status for c in outcome.categories}
    assert statuses["sleeps"] == "failed"
    assert statuses["dailies"] == "success"

    conn = connect(settings.database_file)
    try:
        # dailies still written despite the sleeps failure
        assert conn.execute("SELECT COUNT(*) AS c FROM daily_summaries").fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) AS c FROM sleep_summaries").fetchone()["c"] == 0
    finally:
        conn.close()


@respx.mock
def test_auth_failure_aborts_run_cleanly(settings: Settings):
    respx.post(settings.garmin_token_url).mock(
        return_value=httpx.Response(401, text="bad key")
    )
    engine = SyncEngine(settings, client=GarminClient(settings))
    try:
        outcome = engine.run(start_time=1, end_time=2, trigger="test")
    finally:
        engine.close()
    assert outcome.status == "failed"
    assert "key" in (outcome.message or "").lower()


@respx.mock
def test_historical_data_survives_restart(settings: Settings):
    _mock_all_ok(settings)
    engine = SyncEngine(settings, client=GarminClient(settings))
    try:
        engine.run(start_time=1675832400, end_time=1675918800, trigger="test")
    finally:
        engine.close()

    # Simulate restart: brand-new connection reads persisted data.
    conn = connect(settings.database_file)
    repo = Repository(conn)
    try:
        assert repo.latest_daily() is not None
        assert repo.count_activities() == 1
    finally:
        conn.close()
