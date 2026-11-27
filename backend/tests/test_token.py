"""Token lifecycle tests: acquisition, caching, expiry, permanent-failure no-retry."""

from __future__ import annotations

import time

import httpx
import pytest
import respx

from app.config import Settings
from app.garmin.errors import GarminAuthError, GarminConfigError
from app.garmin.token import AccessToken, TokenManager
from tests import fixtures_api as fx


@respx.mock
def test_acquires_and_caches_token(settings: Settings):
    route = respx.post(settings.garmin_token_url).mock(
        return_value=httpx.Response(200, json=fx.TOKEN_RESPONSE)
    )
    tm = TokenManager(settings, cache_path=settings.database_file.parent / "tc.json")
    with httpx.Client() as client:
        tok1 = tm.get_token(client)
        assert tok1.token == "test-access-token-xyz"
        # Second call should use cache, not hit the network again.
        tok2 = tm.get_token(client)
        assert tok2.token == tok1.token
    assert route.call_count == 1


@respx.mock
def test_token_persisted_to_disk_and_reloaded(settings: Settings):
    respx.post(settings.garmin_token_url).mock(
        return_value=httpx.Response(200, json=fx.TOKEN_RESPONSE)
    )
    cache = settings.database_file.parent / "tc.json"
    tm1 = TokenManager(settings, cache_path=cache)
    with httpx.Client() as client:
        tm1.get_token(client)
    assert cache.exists()
    # A fresh manager reads the on-disk token without a network call.
    tm2 = TokenManager(settings, cache_path=cache)
    loaded = tm2._load_from_disk()
    assert loaded is not None and loaded.token == "test-access-token-xyz"


@respx.mock
def test_expired_token_triggers_refresh(settings: Settings):
    route = respx.post(settings.garmin_token_url).mock(
        return_value=httpx.Response(200, json=fx.TOKEN_RESPONSE)
    )
    cache = settings.database_file.parent / "tc.json"
    tm = TokenManager(settings, cache_path=cache)
    # Seed an already-expired cached token.
    tm._cached = AccessToken(token="old", expires_at=time.time() - 10)
    with httpx.Client() as client:
        tok = tm.get_token(client)
    assert tok.token == "test-access-token-xyz"
    assert route.call_count == 1


@respx.mock
def test_permanent_auth_failure_raises_and_does_not_retry(settings: Settings):
    route = respx.post(settings.garmin_token_url).mock(
        return_value=httpx.Response(401, text="unauthorized")
    )
    tm = TokenManager(settings, cache_path=settings.database_file.parent / "tc.json")
    with httpx.Client() as client:
        with pytest.raises(GarminAuthError):
            tm.get_token(client)
    # Exactly one attempt: no retry loop on a permanent failure.
    assert route.call_count == 1


def test_missing_api_key_raises_config_error(settings: Settings):
    settings.garmin_personal_api_key = ""
    settings.garmin_personal_api_key_file = ""  # ensure no file fallback
    tm = TokenManager(settings, cache_path=settings.database_file.parent / "tc.json")
    with httpx.Client() as client:
        with pytest.raises(GarminConfigError):
            tm.get_token(client)


def test_token_never_leaks_in_redacted():
    tok = AccessToken(token="super-secret", expires_at=time.time() + 100)
    red = tok.redacted()
    assert "super-secret" not in str(red)
    assert "seconds_remaining" in red
