"""Typed exceptions for the Garmin Personal API client.

These let the sync engine and API layer distinguish between:
  * permanent auth failures (do NOT retry) vs
  * transient server/network errors (safe to retry) vs
  * rate limiting (retry after a delay).

No exception message ever includes the API key or access token.
"""

from __future__ import annotations


class GarminError(Exception):
    """Base class for all Garmin client errors."""


class GarminConfigError(GarminError):
    """Missing or invalid configuration (e.g. no API key set)."""


class GarminAuthError(GarminError):
    """Permanent authentication failure (invalid/expired/revoked key or token).

    The caller MUST NOT retry automatically on this error.
    """


class GarminRateLimitError(GarminError):
    """HTTP 429 - too many requests.

    ``retry_after`` is seconds to wait before retrying, if the server provided it.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class GarminServerError(GarminError):
    """Transient server-side error (HTTP 5xx). Safe to retry with backoff."""


class GarminNetworkError(GarminError):
    """Network-level failure (timeout, connection reset). Safe to retry."""


class GarminNotFoundError(GarminError):
    """Requested resource / path returned 404.

    Often indicates a configured resource path does not match the live API.
    """


class GarminResponseError(GarminError):
    """The response was received but could not be parsed as expected."""
