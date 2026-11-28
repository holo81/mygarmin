"""Garmin Personal API HTTP client.

Responsibilities:
  * Obtain & attach a valid OAuth2 access token (via TokenManager).
  * Issue pull requests to the configured Personal API resource paths using
    the endpoint-specific calendar-date range parameters.
  * Download ``.FIT`` activity files.
  * Classify responses into typed errors and retry only transient failures.

Design notes:
  * Delivery is PULL-only for the Personal API, so this client only issues GET
    requests for data (plus the POST for the token).
  * All credentials stay server-side. Nothing here is exposed to the frontend.
  * The sync engine uses Unix-second windows internally and converts them to
    local calendar dates for the Personal API.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from ..config import Settings
from .errors import (
    GarminAuthError,
    GarminNetworkError,
    GarminNotFoundError,
    GarminRateLimitError,
    GarminResponseError,
    GarminServerError,
)
from .token import AccessToken, TokenManager

logger = logging.getLogger("mygarmin.garmin.client")

_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)
_MAX_RETRIES = 3
_BACKOFF_BASE_S = 1.5


@dataclass
class PullResult:
    """Outcome of a single resource pull."""

    category: str
    path: str
    start_time: int
    end_time: int
    status_code: int
    data: Any  # parsed JSON (list or dict), or None
    raw_bytes: bytes | None  # original response body for raw archival


class GarminClient:
    """Thin, typed client over the Personal API pull endpoints."""

    def __init__(
        self,
        settings: Settings,
        token_manager: TokenManager | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._settings = settings
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(
            timeout=_DEFAULT_TIMEOUT,
            headers={"User-Agent": "mygarmin/0.1 (+personal-dashboard)"},
            follow_redirects=True,
        )
        self._tokens = token_manager or TokenManager(settings)

    def __enter__(self) -> GarminClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    # -- auth ---------------------------------------------------------------

    def _auth_header(self, *, force_refresh: bool = False) -> dict[str, str]:
        tok: AccessToken = self._tokens.get_token(self._http, force_refresh=force_refresh)
        return {"Authorization": f"{tok.token_type} {tok.token}"}

    def verify_auth(self) -> dict:
        """Acquire a token and return redacted diagnostics. Raises on failure."""
        tok = self._tokens.get_token(self._http, force_refresh=False)
        return tok.redacted()

    # -- resource pulls -----------------------------------------------------

    def pull(
        self,
        category: str,
        start_time: int,
        end_time: int,
        *,
        extra_params: dict[str, Any] | None = None,
    ) -> PullResult:
        """Pull one data category for a UTC time window [start_time, end_time).

        ``category`` is a key from ``settings.resource_paths()`` (e.g. "dailies").
        """
        paths = self._settings.resource_paths()
        if category not in paths:
            raise GarminResponseError(f"Unknown resource category: {category}")
        path = paths[category]
        try:
            local_tz = ZoneInfo(self._settings.display_timezone)
        except ZoneInfoNotFoundError:
            local_tz = UTC
        start_date = datetime.fromtimestamp(int(start_time), local_tz).date().isoformat()
        end_date = datetime.fromtimestamp(max(int(start_time), int(end_time) - 1), local_tz)
        end_date = end_date.date().isoformat()

        base_url = self._settings.garmin_api_base_url.rstrip("/")
        params: dict[str, Any]
        if category in ("stress", "hrv"):
            url = f"{base_url}{path.rstrip('/')}/{start_date}/{end_date}"
            params = {}
        elif category in ("dailies", "sleeps"):
            url = base_url + path
            params = {"startDate": start_date, "endDate": end_date}
        elif category == "activities":
            url = base_url + path
            params = {
                "start": 0,
                "limit": 1000,
                "startDate": start_date,
                "endDate": end_date,
            }
        else:
            url = base_url + path
            params = {
                "uploadStartTimeInSeconds": int(start_time),
                "uploadEndTimeInSeconds": int(end_time),
            }
        if extra_params:
            params.update(extra_params)

        resp = self._get_with_retry(url, params=params)
        data = self._parse_json(resp) if resp.content else None
        return PullResult(
            category=category,
            path=path,
            start_time=int(start_time),
            end_time=int(end_time),
            status_code=resp.status_code,
            data=data,
            raw_bytes=resp.content or None,
        )

    def download_activity_file(self, file_id: str, token: str | None = None) -> bytes:
        """Download a .FIT activity file by its id (+ optional per-file token).

        The activityFile callback URL documented by Garmin is of the form
        ``.../activityFile?id=XXX&token=YYY``. The per-file ``token`` here is the
        Garmin-provided file token from the activity summary, NOT the OAuth token.
        """
        url = self._settings.garmin_api_base_url.rstrip("/") + self._settings.garmin_path_activity_file
        params: dict[str, Any] = {"id": file_id}
        if token:
            params["token"] = token
        resp = self._get_with_retry(url, params=params, expect_binary=True)
        return resp.content

    # -- HTTP with retry/backoff -------------------------------------------

    def _get_with_retry(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        expect_binary: bool = False,
    ) -> httpx.Response:
        attempt = 0
        refreshed_once = False
        while True:
            attempt += 1
            headers = self._auth_header(force_refresh=refreshed_once and attempt == 2)
            try:
                resp = self._http.get(url, params=params, headers=headers)
            except httpx.TimeoutException as exc:
                if attempt > _MAX_RETRIES:
                    raise GarminNetworkError(f"Request timed out after {attempt} attempts") from exc
                self._sleep_backoff(attempt)
                continue
            except httpx.HTTPError as exc:
                if attempt > _MAX_RETRIES:
                    raise GarminNetworkError("Network error during request") from exc
                self._sleep_backoff(attempt)
                continue

            # Classify status.
            if resp.status_code == 200:
                return resp
            if resp.status_code in (401, 403):
                # Token may have expired mid-window. Refresh ONCE, then give up.
                if not refreshed_once:
                    logger.info("Got HTTP %d; refreshing token once", resp.status_code)
                    self._tokens.invalidate()
                    refreshed_once = True
                    # Next loop will force a brand-new token.
                    continue
                raise GarminAuthError(
                    f"Authentication rejected (HTTP {resp.status_code}) after token refresh. "
                    "The Personal API key may be expired or revoked."
                )
            if resp.status_code == 404:
                raise GarminNotFoundError(
                    f"Resource not found (HTTP 404) for {url}. The configured path may "
                    "not match the live Personal API; check GARMIN_PATH_* in .env."
                )
            if resp.status_code == 429:
                retry_after = self._parse_retry_after(resp)
                if attempt > _MAX_RETRIES:
                    raise GarminRateLimitError(
                        "Rate limited (HTTP 429); retries exhausted", retry_after=retry_after
                    )
                wait = retry_after if retry_after is not None else self._backoff_seconds(attempt)
                logger.warning("Rate limited; waiting %.1fs before retry", wait)
                time.sleep(wait)
                continue
            if resp.status_code >= 500:
                if attempt > _MAX_RETRIES:
                    raise GarminServerError(
                        f"Server error (HTTP {resp.status_code}); retries exhausted"
                    )
                self._sleep_backoff(attempt)
                continue
            # Other 4xx: not retryable.
            raise GarminResponseError(f"Unexpected HTTP {resp.status_code} for {url}")

    @staticmethod
    def _parse_retry_after(resp: httpx.Response) -> float | None:
        val = resp.headers.get("Retry-After")
        if not val:
            return None
        try:
            return float(val)
        except ValueError:
            return None

    @staticmethod
    def _backoff_seconds(attempt: int) -> float:
        return _BACKOFF_BASE_S * (2 ** (attempt - 1))

    def _sleep_backoff(self, attempt: int) -> None:
        time.sleep(self._backoff_seconds(attempt))

    @staticmethod
    def _parse_json(resp: httpx.Response) -> Any:
        try:
            return resp.json()
        except (ValueError, httpx.DecodingError) as exc:
            raise GarminResponseError("Response body was not valid JSON") from exc
