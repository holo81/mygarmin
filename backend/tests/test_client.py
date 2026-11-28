"""Client tests against the real request model (path/query, FIT zip)."""

from __future__ import annotations

import io
import zipfile

import httpx
import pytest
import respx

from app.config import Settings
from app.garmin.client import GarminClient
from app.garmin.errors import GarminAuthError, GarminNotFoundError, GarminServerError
from tests import fixtures_api as fx


def _token(settings: Settings):
    return respx.post(settings.garmin_token_url).mock(
        return_value=httpx.Response(200, json=fx.TOKEN_RESPONSE)
    )


@respx.mock
def test_pull_daily_with_query(settings: Settings):
    _token(settings)
    url = settings.garmin_api_base_url.rstrip("/") + settings.garmin_path_daily
    route = respx.get(url).mock(return_value=httpx.Response(200, json=fx.DAILY))
    with GarminClient(settings) as c:
        res = c.pull("daily", query={"calendarDate": "2026-10-21"})
    assert res.status_code == 200
    assert res.data["totalSteps"] == 4433
    assert route.called


@respx.mock
def test_pull_hrv_with_path_param(settings: Settings):
    _token(settings)
    url = settings.garmin_api_base_url.rstrip("/") + "/hrv-service/hrv/2026-10-21"
    respx.get(url).mock(return_value=httpx.Response(200, json=fx.HRV))
    with GarminClient(settings) as c:
        res = c.pull("hrv", path_params={"date": "2026-10-21"})
    assert res.data["hrvSummary"]["status"] == "BALANCED"


@respx.mock
def test_pull_404(settings: Settings):
    _token(settings)
    url = settings.garmin_api_base_url.rstrip("/") + settings.garmin_path_sleep
    respx.get(url).mock(return_value=httpx.Response(404))
    with GarminClient(settings) as c, pytest.raises(GarminNotFoundError):
        c.pull("sleep", query={"date": "2026-10-21"})


@respx.mock
def test_pull_retries_5xx(settings: Settings, monkeypatch):
    _token(settings)
    monkeypatch.setattr("app.garmin.client.time.sleep", lambda *_: None)
    url = settings.garmin_api_base_url.rstrip("/") + settings.garmin_path_daily
    route = respx.get(url).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json=fx.DAILY)]
    )
    with GarminClient(settings) as c:
        res = c.pull("daily", query={"calendarDate": "2026-10-21"})
    assert res.status_code == 200 and route.call_count == 2


@respx.mock
def test_pull_persistent_5xx_raises(settings: Settings, monkeypatch):
    _token(settings)
    monkeypatch.setattr("app.garmin.client.time.sleep", lambda *_: None)
    url = settings.garmin_api_base_url.rstrip("/") + settings.garmin_path_daily
    respx.get(url).mock(return_value=httpx.Response(500))
    with GarminClient(settings) as c, pytest.raises(GarminServerError):
        c.pull("daily", query={"calendarDate": "2026-10-21"})


@respx.mock
def test_auth_refresh_once_then_fail(settings: Settings):
    respx.post(settings.garmin_token_url).mock(
        return_value=httpx.Response(200, json=fx.TOKEN_RESPONSE)
    )
    url = settings.garmin_api_base_url.rstrip("/") + settings.garmin_path_daily
    route = respx.get(url).mock(return_value=httpx.Response(401))
    with GarminClient(settings) as c, pytest.raises(GarminAuthError):
        c.pull("daily", query={"calendarDate": "2026-10-21"})
    assert route.call_count == 2


@respx.mock
def test_download_activity_file_returns_bytes(settings: Settings):
    _token(settings)
    # Build a zip containing a dummy .fit entry.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("123.fit", b"\x0e\x10dummy-fit")
    zip_bytes = buf.getvalue()
    url = settings.garmin_api_base_url.rstrip("/") + "/download-service/files/activity/123"
    respx.get(url).mock(
        return_value=httpx.Response(200, content=zip_bytes, headers={"content-type": "application/x-zip-compressed"})
    )
    with GarminClient(settings) as c:
        data = c.download_activity_file("123")
    assert data[:2] == b"PK"  # it's the zip
