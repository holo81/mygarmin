"""Client tests: pull success, retry on 5xx, no-retry on permanent auth, 404 hint."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.config import Settings
from app.garmin.client import GarminClient
from app.garmin.errors import GarminAuthError, GarminNotFoundError, GarminServerError
from tests import fixtures_api as fx


def _token_route(settings: Settings):
    return respx.post(settings.garmin_token_url).mock(
        return_value=httpx.Response(200, json=fx.TOKEN_RESPONSE)
    )


@respx.mock
def test_pull_returns_parsed_json(settings: Settings):
    _token_route(settings)
    url = settings.garmin_api_base_url.rstrip("/") + settings.garmin_path_dailies
    respx.get(url).mock(return_value=httpx.Response(200, json=[fx.DAILY]))
    with GarminClient(settings) as client:
        result = client.pull("dailies", 1675832400, 1675918800)
    assert result.status_code == 200
    assert isinstance(result.data, list)
    assert result.data[0]["summaryId"] == "x111-daily-1"
    assert result.raw_bytes is not None


@respx.mock
def test_pull_retries_on_server_error_then_succeeds(settings: Settings, monkeypatch):
    _token_route(settings)
    monkeypatch.setattr("app.garmin.client.time.sleep", lambda *_: None)
    url = settings.garmin_api_base_url.rstrip("/") + settings.garmin_path_dailies
    route = respx.get(url).mock(
        side_effect=[
            httpx.Response(503, text="try later"),
            httpx.Response(200, json=[fx.DAILY]),
        ]
    )
    with GarminClient(settings) as client:
        result = client.pull("dailies", 1, 2)
    assert result.status_code == 200
    assert route.call_count == 2


@respx.mock
def test_pull_gives_up_on_persistent_server_error(settings: Settings, monkeypatch):
    _token_route(settings)
    monkeypatch.setattr("app.garmin.client.time.sleep", lambda *_: None)
    url = settings.garmin_api_base_url.rstrip("/") + settings.garmin_path_dailies
    respx.get(url).mock(return_value=httpx.Response(500, text="boom"))
    with GarminClient(settings) as client:
        with pytest.raises(GarminServerError):
            client.pull("dailies", 1, 2)


@respx.mock
def test_pull_404_hints_at_path_config(settings: Settings):
    _token_route(settings)
    url = settings.garmin_api_base_url.rstrip("/") + settings.garmin_path_sleeps
    respx.get(url).mock(return_value=httpx.Response(404, text="nope"))
    with GarminClient(settings) as client:
        with pytest.raises(GarminNotFoundError) as exc:
            client.pull("sleeps", 1, 2)
    assert "GARMIN_PATH" in str(exc.value)


@respx.mock
def test_pull_refreshes_token_once_on_401_then_fails(settings: Settings):
    # Token endpoint returns a valid token twice (initial + refresh).
    respx.post(settings.garmin_token_url).mock(
        return_value=httpx.Response(200, json=fx.TOKEN_RESPONSE)
    )
    url = settings.garmin_api_base_url.rstrip("/") + settings.garmin_path_activities
    route = respx.get(url).mock(return_value=httpx.Response(401, text="expired"))
    with GarminClient(settings) as client:
        with pytest.raises(GarminAuthError):
            client.pull("activities", 1, 2)
    # One original + one after refresh = 2 data calls, then give up.
    assert route.call_count == 2
