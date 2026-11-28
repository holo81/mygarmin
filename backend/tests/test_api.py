"""API tests: endpoints serve stored data, sync token guard, mock-data flag off in prod."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from app import normalize as norm
from app.config import Settings, get_settings
from app.db.database import connect
from app.db.repository import Repository
from tests import fixtures_api as fx


@pytest.fixture
def client(settings: Settings, monkeypatch):
    # Point the app's settings at the test database.
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", str(settings.database_file))
    monkeypatch.setenv("RAW_PAYLOAD_DIR", settings.raw_payload_dir)
    monkeypatch.setenv("FIT_FILE_DIR", settings.fit_file_dir)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SYNC_API_TOKEN", "test-sync-token")
    monkeypatch.setenv("AUTO_SYNC_MINUTES", "0")  # never hit Garmin from tests

    # Seed some data.
    conn = connect(settings.database_file)
    repo = Repository(conn)
    repo.upsert_daily(norm.normalize_daily(fx.DAILY))
    repo.upsert_sleep(norm.normalize_sleep(fx.SLEEP))
    repo.upsert_hrv(norm.normalize_hrv(fx.HRV))
    repo.upsert_activity(norm.normalize_activity(fx.ACTIVITY_RUN))
    cal, bb = norm.normalize_body_battery_report(fx.BODY_BATTERY_REPORT[0])
    repo.replace_body_battery_samples(cal, bb)
    repo.replace_activity_samples(
        "111",
        [
            {
                "sample_index": 0, "offset_seconds": 0, "clock_time_seconds": 1000,
                "latitude": 60.17, "longitude": 24.94, "elevation_meters": 10.0,
                "heart_rate_bpm": 140, "speed_mps": 2.5, "cadence": 160.0,
                "power_watts": None, "distance_meters": 0.0, "temperature_celsius": 12.0,
                "source": "fit",
            }
        ],
    )
    repo.commit()
    conn.close()

    from app.api import app as app_module

    importlib.reload(app_module)
    with TestClient(app_module.app) as c:
        yield c
    get_settings.cache_clear()


def test_overview_serves_stored_data(client):
    r = client.get("/api/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["today"]["daily"]["steps"] == 4433
    assert body["meta"]["dataSource"] == "garmin"  # prod never reports mock
    assert len(body["today"]["stress"]["bodyBattery"]) == 3


def test_activities_list_and_detail(client):
    r = client.get("/api/activities")
    assert r.status_code == 200
    assert r.json()["total"] == 1

    r2 = client.get("/api/activities/111")
    assert r2.status_code == 200
    detail = r2.json()
    assert detail["available"]["gps"] is True
    assert detail["available"]["heartRate"] is True
    assert len(detail["samples"]) == 1
    # Zones/splits are reused from the coach export; keys always present (null when not derivable).
    assert set(detail["derived"]) == {"hrZones", "splitsPerKm"}
    zones = detail["derived"]["hrZones"]
    assert zones is None or len(zones["zones"]) == 5


def test_trends_endpoint(client):
    r = client.get("/api/trends?range=30d")
    assert r.status_code == 200
    series = r.json()["series"]
    assert any(p["value"] == 52 for p in series["restingHeartRate"])


def test_sync_requires_token(client):
    # No auth header -> 401.
    r = client.post("/api/sync")
    assert r.status_code == 401
    # Wrong token -> 403.
    r2 = client.post("/api/sync", headers={"Authorization": "Bearer wrong"})
    assert r2.status_code == 403


def test_missing_activity_404(client):
    r = client.get("/api/activities/does-not-exist-999")
    assert r.status_code == 404


def test_sync_guard_open_when_no_token(monkeypatch):
    """When SYNC_API_TOKEN is unset, the guard allows sync without a token."""
    from app.api import app as app_module
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SYNC_API_TOKEN", "")
    # Should not raise (returns None) regardless of the Authorization header.
    assert app_module.require_sync_token(authorization=None) is None
    get_settings.cache_clear()


def test_sync_guard_requires_token_when_set(monkeypatch):
    from fastapi import HTTPException

    from app.api import app as app_module
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SYNC_API_TOKEN", "secret-token")
    # No header -> 401
    try:
        app_module.require_sync_token(authorization=None)
        raised = None
    except HTTPException as exc:
        raised = exc.status_code
    assert raised == 401
    # Correct token -> allowed
    assert app_module.require_sync_token(authorization="Bearer secret-token") is None
    get_settings.cache_clear()
