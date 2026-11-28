"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.db.database import connect, init_db
from app.db.repository import Repository


@pytest.fixture
def settings(tmp_path) -> Settings:
    s = Settings(
        GARMIN_PERSONAL_API_KEY="test-key-123",
        DATABASE_PATH=str(tmp_path / "test.db"),
        RAW_PAYLOAD_DIR=str(tmp_path / "raw"),
        FIT_FILE_DIR=str(tmp_path / "fit"),
        APP_ENV="production",
        SYNC_API_TOKEN="test-sync-token",
        INITIAL_IMPORT_DAYS=7,
        SYNC_DAY_DELAY_SECONDS=0,
    )
    s.ensure_dirs()
    init_db(s.database_file)
    return s


@pytest.fixture
def repo(settings: Settings):
    conn = connect(settings.database_file)
    try:
        yield Repository(conn)
    finally:
        conn.close()
