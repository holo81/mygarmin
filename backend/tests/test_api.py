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

    # Seed some data.
    conn = connect(settings.database_file)
    repo = Repository(conn)
    repo.upsert_daily(norm.normalize_daily(fx.DAILY))
    repo.upsert_sleep(norm.normalize_sleep(fx.SLEEP))
    repo.upsert_hrv(norm.normalize_hrv(fx.HRV))
    repo.upsert_stress(norm.normalize_stress(fx.STRESS))
    repo.upsert_activity(norm.normalize_activity(fx.ACTIVITY))
    repo.replace_activity_samples(
        "x111-act-1", norm.normalize_activity_samples(fx.ACTIVITY_DETAILS)
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
    assert body["today"]["daily"]["steps"] == 12543
    assert body["meta"]["dataSource"] == "garmin"  # prod never reports mock


def test_activities_list_and_detail(client):
    r = client.get("/api/activities")
    assert r.status_code == 200
    assert r.json()["total"] == 1

    r2 = client.get("/api/activities/x111-act-1")
    assert r2.status_code == 200
    detail = r2.json()
    assert detail["available"]["gps"] is True
    assert detail["available"]["heartRate"] is True
    assert len(detail["samples"]) == 2


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
    r = client.get("/api/activities/does-not-exist")
    assert r.status_code == 404
