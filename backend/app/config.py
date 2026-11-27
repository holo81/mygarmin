"""Application configuration loaded from environment / .env.

All secrets come from the environment. Nothing here is logged or returned to the
frontend. See `.env.example` for documentation of each setting.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
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
    # The key may be provided either inline via GARMIN_PERSONAL_API_KEY or, more
    # securely, via a file whose path is GARMIN_PERSONAL_API_KEY_FILE (the file's
    # contents are read at runtime and never logged). The inline env var takes
    # precedence if both are set.
    garmin_personal_api_key: str = Field(default="", alias="GARMIN_PERSONAL_API_KEY")
    garmin_personal_api_key_file: str = Field(
        default="", alias="GARMIN_PERSONAL_API_KEY_FILE"
    )
    garmin_token_url: str = Field(
        default="https://personal.connectapi.garmin.com/personalapitoken-service/personal-api/personal-api-key/token",
        alias="GARMIN_TOKEN_URL",
    )
    garmin_api_base_url: str = Field(
        default="https://personal.connectapi.garmin.com", alias="GARMIN_API_BASE_URL"
    )

    # Path templates for the real Personal API (from the official Swagger).
    # Placeholders: {date}, {fromDate}, {toDate} (yyyy-mm-dd), {activityId}.
    # Date-range endpoints are fetched once per range; per-day endpoints once per day.
    garmin_path_daily: str = Field(
        default="/usersummary-service/usersummary/daily", alias="GARMIN_PATH_DAILY"
    )  # ?calendarDate=
    garmin_path_sleep: str = Field(
        default="/sleep-service/sleep/dailySleep", alias="GARMIN_PATH_SLEEP"
    )  # ?date=
    garmin_path_hrv: str = Field(
        default="/hrv-service/hrv/{date}", alias="GARMIN_PATH_HRV"
    )
    garmin_path_hrv_range: str = Field(
        default="/hrv-service/hrv/daily/{fromDate}/{toDate}", alias="GARMIN_PATH_HRV_RANGE"
    )
    garmin_path_stress_range: str = Field(
        default="/usersummary-service/stats/stress/daily/{fromDate}/{toDate}",
        alias="GARMIN_PATH_STRESS_RANGE",
    )
    garmin_path_steps_range: str = Field(
        default="/usersummary-service/stats/steps/daily/{fromDate}/{toDate}",
        alias="GARMIN_PATH_STEPS_RANGE",
    )
    garmin_path_body_battery: str = Field(
        default="/wellness-service/wellness/bodyBattery/reports/daily",
        alias="GARMIN_PATH_BODY_BATTERY",
    )  # ?startDate=&endDate=
    garmin_path_daily_heart_rate: str = Field(
        default="/wellness-service/wellness/dailyHeartRate",
        alias="GARMIN_PATH_DAILY_HEART_RATE",
    )  # ?date=
    garmin_path_activities_search: str = Field(
        default="/activitylist-service/activities/search/activities",
        alias="GARMIN_PATH_ACTIVITIES_SEARCH",
    )  # ?start=&limit=
    garmin_path_activity_detail: str = Field(
        default="/activity-service/activity/{activityId}",
        alias="GARMIN_PATH_ACTIVITY_DETAIL",
    )
    garmin_path_activity_file: str = Field(
        default="/download-service/files/activity/{activityId}",
        alias="GARMIN_PATH_ACTIVITY_FILE",
    )  # returns a zip containing the .FIT
    garmin_path_userprofile_settings: str = Field(
        default="/userprofile-service/userprofile/settings",
        alias="GARMIN_PATH_USERPROFILE_SETTINGS",
    )
    garmin_path_hr_zones: str = Field(
        default="/biometric-service/heartRateZones/v2", alias="GARMIN_PATH_HR_ZONES"
    )
    garmin_path_fitnessage: str = Field(
        default="/fitnessage-service/fitnessage/v2/{date}", alias="GARMIN_PATH_FITNESSAGE"
    )
    garmin_path_weight_range: str = Field(
        default="/weight-service/weight/range/{fromDate}/{toDate}",
        alias="GARMIN_PATH_WEIGHT_RANGE",
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
    sync_window_days: int = Field(default=1, alias="SYNC_WINDOW_DAYS")
    # Background sync inside the web server; 0 disables it.
    auto_sync_minutes: int = Field(default=15, ge=0, alias="AUTO_SYNC_MINUTES")

    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173", alias="CORS_ORIGINS"
    )

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

    def resolve_api_key(self) -> str:
        """Return the Personal API key, from the env var or the key file.

        Precedence: GARMIN_PERSONAL_API_KEY (inline) wins; otherwise read the
        file at GARMIN_PERSONAL_API_KEY_FILE. The file's contents are stripped of
        surrounding whitespace/newlines. Raises FileNotFoundError if a file path
        is configured but missing. The key value is never logged.
        """
        inline = self.garmin_personal_api_key.strip()
        if inline:
            return inline
        key_file = self.garmin_personal_api_key_file.strip()
        if key_file:
            path = _resolve(key_file)
            return path.read_text(encoding="utf-8").strip()
        return ""

    @property
    def has_api_key(self) -> bool:
        if self.garmin_personal_api_key.strip():
            return True
        key_file = self.garmin_personal_api_key_file.strip()
        if key_file:
            try:
                return bool(_resolve(key_file).read_text(encoding="utf-8").strip())
            except OSError:
                return False
        return False

    def ensure_dirs(self) -> None:
        self.database_file.parent.mkdir(parents=True, exist_ok=True)
        self.raw_payload_path.mkdir(parents=True, exist_ok=True)
        self.fit_file_path.mkdir(parents=True, exist_ok=True)

    def resource_paths(self) -> dict[str, str]:
        """Map of logical data category -> configured relative path template."""
        return {
            "daily": self.garmin_path_daily,
            "sleep": self.garmin_path_sleep,
            "hrv": self.garmin_path_hrv,
            "hrv_range": self.garmin_path_hrv_range,
            "stress_range": self.garmin_path_stress_range,
            "steps_range": self.garmin_path_steps_range,
            "body_battery": self.garmin_path_body_battery,
            "daily_heart_rate": self.garmin_path_daily_heart_rate,
            "activities_search": self.garmin_path_activities_search,
            "activity_detail": self.garmin_path_activity_detail,
            "activity_file": self.garmin_path_activity_file,
            "userprofile_settings": self.garmin_path_userprofile_settings,
            "hr_zones": self.garmin_path_hr_zones,
            "fitnessage": self.garmin_path_fitnessage,
            "weight_range": self.garmin_path_weight_range,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
