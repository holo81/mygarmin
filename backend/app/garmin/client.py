"""Garmin Personal API HTTP client.

Responsibilities:
  * Obtain & attach a valid OAuth2 access token (via TokenManager).
  * Issue pull requests to the configured Health/Activity resource paths using
    the documented ``uploadStartTimeInSeconds`` / ``uploadEndTimeInSeconds`` window.
  * Download ``.FIT`` activity files.
  * Classify responses into typed errors and retry only transient failures.

Design notes:
  * Delivery is PULL-only for the Personal API, so this client only issues GET
    requests for data (plus the POST for the token).
  * All credentials stay server-side. Nothing here is exposed to the frontend.
  * Time windows use Unix seconds (UTC), matching the documented API contract.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

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

    def _resolve_path(self, category: str, path_params: dict[str, Any] | None) -> str:
        paths = self._settings.resource_paths()
        if category not in paths:
            raise GarminResponseError(f"Unknown resource category: {category}")
        template = paths[category]
        if path_params:
            try:
                return template.format(**path_params)
            except KeyError as exc:
                raise GarminResponseError(
                    f"Missing path parameter {exc} for category {category}"
                ) from exc
        return template

    def pull(
        self,
        category: str,
        *,
        path_params: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> PullResult:
        """Pull one data category from the real Personal API.

        Date selection is expressed via ``path_params`` (for templated paths like
        ``/hrv-service/hrv/{date}``) and/or ``query`` (for endpoints that take
        ?calendarDate=, ?date=, ?startDate=&endDate=, ?start=&limit=). ``category``
        is a key from ``settings.resource_paths()``.
        """
        path = self._resolve_path(category, path_params)
        url = self._settings.garmin_api_base_url.rstrip("/") + path
        resp = self._get_with_retry(url, params=query or {})
        data = self._parse_json(resp) if resp.content else None
        return PullResult(
            category=category,
            path=path,
            start_time=0,
            end_time=0,
            status_code=resp.status_code,
            data=data,
            raw_bytes=resp.content or None,
        )

    def download_activity_file(self, activity_id: str) -> bytes:
        """Download an activity's file via the download-service.

        The Personal API returns a ZIP archive containing the ``.FIT`` file
        (content-type application/x-zip-compressed). Callers unzip it before
        decoding. The URL is ``/download-service/files/activity/{activityId}``.
        """
        path = self._resolve_path("activity_file", {"activityId": activity_id})
        url = self._settings.garmin_api_base_url.rstrip("/") + path
        resp = self._get_with_retry(url, params={}, expect_binary=True)
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
