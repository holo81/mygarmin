"""Application configuration loaded from environment / .env.

All secrets come from the environment. Nothing here is logged or returned to the
frontend. See `.env.example` for documentation of each setting.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = parent of the `backend` directory (so default relative paths
# like ./data resolve next to the repo, regardless of CWD).
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent


def _resolve(path_str: str) -> Path:
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = (_PROJECT_ROOT / p).resolve()
    return p


class Settings(BaseSettings):
    """Typed application settings."""

    model_config = SettingsConfigDict(
        env_file=(_PROJECT_ROOT / ".env", _BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Garmin Personal API ---
    garmin_personal_api_key: str = Field(default="", alias="GARMIN_PERSONAL_API_KEY")
    garmin_personal_api_key_file: str = Field(
        default="garmin_accesss.key", alias="GARMIN_PERSONAL_API_KEY_FILE"
    )
    garmin_token_url: str = Field(
        default="https://personal.connectapi.garmin.com/personalapitoken-service/personal-api/personal-api-key/token",
        alias="GARMIN_TOKEN_URL",
    )
    garmin_api_base_url: str = Field(
        default="https://personal.connectapi.garmin.com", alias="GARMIN_API_BASE_URL"
    )

    garmin_path_dailies: str = Field(
        default="/usersummary-service/v2/dailysummaries", alias="GARMIN_PATH_DAILIES"
    )
    garmin_path_sleeps: str = Field(
        default="/sleep-service/sleep/dailySleepSummariesByDate", alias="GARMIN_PATH_SLEEPS"
    )
    garmin_path_stress: str = Field(
        default="/usersummary-service/stats/stress/daily", alias="GARMIN_PATH_STRESS"
    )
    garmin_path_hrv: str = Field(
        default="/hrv-service/hrv/daily", alias="GARMIN_PATH_HRV"
    )
    garmin_path_respiration: str = Field(
        default="/wellness-api/rest/respiration", alias="GARMIN_PATH_RESPIRATION"
    )
    garmin_path_pulseox: str = Field(
        default="/wellness-api/rest/pulseOx", alias="GARMIN_PATH_PULSEOX"
    )
    garmin_path_activities: str = Field(
        default="/activitylist-service/activities/search/activities",
        alias="GARMIN_PATH_ACTIVITIES",
    )
    garmin_path_activity_details: str = Field(
        default="/wellness-api/rest/activityDetails", alias="GARMIN_PATH_ACTIVITY_DETAILS"
    )
    garmin_path_activity_file: str = Field(
        default="/wellness-api/rest/activityFile", alias="GARMIN_PATH_ACTIVITY_FILE"
    )

    # --- Application ---
    database_path: str = Field(default="./data/mygarmin.db", alias="DATABASE_PATH")
    raw_payload_dir: str = Field(default="./data/raw_payloads", alias="RAW_PAYLOAD_DIR")
    fit_file_dir: str = Field(default="./data/fit_files", alias="FIT_FILE_DIR")

    host: str = Field(default="127.0.0.1", alias="HOST")
    port: int = Field(default=8787, alias="PORT")

    sync_api_token: str = Field(default="", alias="SYNC_API_TOKEN")
    display_timezone: str = Field(default="Europe/Helsinki", alias="DISPLAY_TIMEZONE")
    unit_system: str = Field(default="metric", alias="UNIT_SYSTEM")
    app_env: str = Field(default="production", alias="APP_ENV")

    initial_import_days: int = Field(default=90, alias="INITIAL_IMPORT_DAYS")
    sync_window_days: int = Field(default=27, alias="SYNC_WINDOW_DAYS")

    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173", alias="CORS_ORIGINS"
    )

    @model_validator(mode="after")
    def load_personal_api_key_file(self) -> "Settings":
        if self.garmin_personal_api_key.strip():
            return self

        key_path = Path(self.garmin_personal_api_key_file).expanduser()
        if not key_path.is_absolute():
            key_path = _PROJECT_ROOT / key_path
        if not key_path.is_file() and self.garmin_personal_api_key_file == "garmin_accesss.key":
            key_path = _PROJECT_ROOT / "garmin_access.key"
        if key_path.is_file():
            self.garmin_personal_api_key = key_path.read_text(encoding="utf-8").strip()
        return self

    # --- Derived helpers ---
    @property
    def database_file(self) -> Path:
        return _resolve(self.database_path)

    @property
    def raw_payload_path(self) -> Path:
        return _resolve(self.raw_payload_dir)

    @property
    def fit_file_path(self) -> Path:
        return _resolve(self.fit_file_dir)

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def has_api_key(self) -> bool:
        return bool(self.garmin_personal_api_key.strip())

    def ensure_dirs(self) -> None:
        self.database_file.parent.mkdir(parents=True, exist_ok=True)
        self.raw_payload_path.mkdir(parents=True, exist_ok=True)
        self.fit_file_path.mkdir(parents=True, exist_ok=True)

    def resource_paths(self) -> dict[str, str]:
        """Map of logical data category -> configured relative path."""
        return {
            "dailies": self.garmin_path_dailies,
            "sleeps": self.garmin_path_sleeps,
            "stress": self.garmin_path_stress,
            "hrv": self.garmin_path_hrv,
            "respiration": self.garmin_path_respiration,
            "pulseox": self.garmin_path_pulseox,
            "activities": self.garmin_path_activities,
            "activity_details": self.garmin_path_activity_details,
            "activity_file": self.garmin_path_activity_file,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
