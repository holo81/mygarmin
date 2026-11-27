"""Personal API token acquisition and caching.

Flow (documented by Garmin):
    POST {GARMIN_TOKEN_URL}
    Header: Authorization: ApiKey <PERSONAL_API_KEY>
    -> returns an OAuth2 access token, valid for 24h, no refresh token.

We cache the access token on disk (with restrictive file permissions) so we do
not request a new token on every sync. When the cached token is missing or
within a safety margin of expiry, we request a new one.

Security:
  * The API key is read from config (env) and never written to the cache file.
  * The cache file stores only the access token + computed expiry.
  * Tokens / keys are never logged.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..config import Settings
from .errors import (
    GarminAuthError,
    GarminConfigError,
    GarminNetworkError,
    GarminResponseError,
    GarminServerError,
)

logger = logging.getLogger("mygarmin.garmin.token")

# Refresh the token when it has this many seconds or fewer left, to avoid
# using a token that expires mid-request.
_EXPIRY_SAFETY_MARGIN_S = 300
# If the response omits an explicit expiry, assume the documented 24h lifetime.
_DEFAULT_TOKEN_TTL_S = 24 * 60 * 60


@dataclass
class AccessToken:
    token: str
    expires_at: float  # epoch seconds
    token_type: str = "Bearer"

    def is_valid(self, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        return bool(self.token) and (self.expires_at - _EXPIRY_SAFETY_MARGIN_S) > now

    def redacted(self) -> dict:
        """Safe representation for diagnostics (never includes the token)."""
        return {
            "token_type": self.token_type,
            "expires_at": self.expires_at,
            "seconds_remaining": max(0, int(self.expires_at - time.time())),
        }


class TokenManager:
    """Acquires and caches Personal API access tokens."""

    def __init__(self, settings: Settings, cache_path: Path | None = None) -> None:
        self._settings = settings
        self._cache_path = cache_path or (settings.database_file.parent / "token_cache.json")
        self._cached: AccessToken | None = None

    # -- public API ---------------------------------------------------------

    def get_token(self, client: httpx.Client, *, force_refresh: bool = False) -> AccessToken:
        """Return a valid access token, requesting a new one if needed."""
        if not force_refresh:
            tok = self._cached or self._load_from_disk()
            if tok and tok.is_valid():
                self._cached = tok
                return tok
        tok = self._request_new_token(client)
        self._cached = tok
        self._save_to_disk(tok)
        return tok

    def invalidate(self) -> None:
        """Drop the cached token (e.g. after a 401 mid-request)."""
        self._cached = None
        try:
            if self._cache_path.exists():
                self._cache_path.unlink()
        except OSError:
            logger.warning("Could not remove token cache file")

    # -- token request ------------------------------------------------------

    def _request_new_token(self, client: httpx.Client) -> AccessToken:
        if not self._settings.has_api_key:
            raise GarminConfigError(
                "No Garmin Personal API key configured. Set GARMIN_PERSONAL_API_KEY in .env."
            )
        api_key = self._settings.garmin_personal_api_key.strip()
        logger.info("Requesting new Garmin Personal API access token")
        try:
            resp = client.post(
                self._settings.garmin_token_url,
                headers={"Authorization": f"ApiKey {api_key}"},
            )
        except httpx.TimeoutException as exc:
            raise GarminNetworkError("Timed out requesting access token") from exc
        except httpx.HTTPError as exc:
            raise GarminNetworkError("Network error requesting access token") from exc

        if resp.status_code in (401, 403):
            # Permanent: bad / expired / revoked key. Do NOT retry.
            raise GarminAuthError(
                "Authentication failed obtaining access token "
                f"(HTTP {resp.status_code}). The Personal API key may be invalid, "
                "expired, or revoked. Create a new key in Garmin Connect and update "
                "GARMIN_PERSONAL_API_KEY."
            )
        if resp.status_code >= 500:
            raise GarminServerError(
                f"Garmin token service returned HTTP {resp.status_code} (transient)."
            )
        if resp.status_code != 200:
            raise GarminAuthError(
                f"Unexpected HTTP {resp.status_code} from token service."
            )

        return self._parse_token_response(resp)

    def _parse_token_response(self, resp: httpx.Response) -> AccessToken:
        now = time.time()
        # The documented response is JSON. Be tolerant of field naming because the
        # exact schema is only fully visible in the login-gated Swagger. We accept
        # the common OAuth2 shapes and a plain-string fallback.
        token_str: str | None = None
        expires_at = now + _DEFAULT_TOKEN_TTL_S
        token_type = "Bearer"

        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type or resp.text.strip().startswith("{"):
            try:
                data = resp.json()
            except (json.JSONDecodeError, ValueError) as exc:
                raise GarminResponseError("Token response was not valid JSON") from exc
            token_str = (
                data.get("access_token")
                or data.get("accessToken")
                or data.get("token")
            )
            token_type = data.get("token_type") or data.get("tokenType") or "Bearer"
            # Expiry may be given as seconds-to-live or absolute.
            expires_in = data.get("expires_in") or data.get("expiresIn")
            if isinstance(expires_in, (int, float)) and expires_in > 0:
                expires_at = now + float(expires_in)
        else:
            # Some deployments return the raw token string.
            stripped = resp.text.strip().strip('"')
            if stripped:
                token_str = stripped

        if not token_str:
            raise GarminResponseError(
                "Token service response did not contain an access token field."
            )
        logger.info(
            "Obtained access token (expires in ~%d min)",
            int((expires_at - now) / 60),
        )
        return AccessToken(token=token_str, expires_at=expires_at, token_type=token_type)

    # -- disk cache ---------------------------------------------------------

    def _load_from_disk(self) -> AccessToken | None:
        try:
            if not self._cache_path.exists():
                return None
            raw = json.loads(self._cache_path.read_text(encoding="utf-8"))
            return AccessToken(
                token=raw["token"],
                expires_at=float(raw["expires_at"]),
                token_type=raw.get("token_type", "Bearer"),
            )
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            logger.warning("Ignoring unreadable token cache file")
            return None

    def _save_to_disk(self, tok: AccessToken) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "token": tok.token,
                        "expires_at": tok.expires_at,
                        "token_type": tok.token_type,
                    }
                ),
                encoding="utf-8",
            )
            # Restrict to owner read/write only before moving into place.
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
            tmp.replace(self._cache_path)
        except OSError:
            # Caching is best-effort; a failure here must not break sync.
            logger.warning("Could not persist token cache")
