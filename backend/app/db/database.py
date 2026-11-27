"""SQLite connection management and migration runner.

A single-user, self-hosted app: SQLite in WAL mode is plenty. We keep schema
changes additive and versioned so historical data is never dropped during an
ordinary sync or upgrade.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

_SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"
_SCHEMA_VERSION = 3

# Additive column migrations applied on top of an existing v1 database so no
# historical data is dropped. Each entry: (table, column, column_def).
_ADDITIVE_COLUMNS: list[tuple[str, str, str]] = [
    ("daily_summaries", "total_kilocalories", "INTEGER"),
    ("daily_summaries", "resting_hr_7d_avg", "INTEGER"),
    ("daily_summaries", "body_battery_charged", "INTEGER"),
    ("daily_summaries", "body_battery_drained", "INTEGER"),
    ("daily_summaries", "body_battery_high", "INTEGER"),
    ("daily_summaries", "body_battery_low", "INTEGER"),
    ("daily_summaries", "body_battery_most_recent", "INTEGER"),
    ("daily_summaries", "avg_spo2", "REAL"),
    ("daily_summaries", "lowest_spo2", "INTEGER"),
    ("daily_summaries", "avg_waking_respiration", "REAL"),
    ("daily_summaries", "highest_respiration", "REAL"),
    ("daily_summaries", "lowest_respiration", "REAL"),
    ("daily_summaries", "sleeping_seconds", "INTEGER"),
    ("sleep_summaries", "lowest_spo2", "INTEGER"),
    ("sleep_summaries", "avg_sleep_stress", "REAL"),
    ("sleep_summaries", "avg_sleep_hr", "REAL"),
    ("sleep_summaries", "awake_count", "INTEGER"),
]


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with sane pragmas and row access by name."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: FastAPI serves sync endpoints from a threadpool,
    # so a connection may be created and used on different worker threads. Each
    # request opens its own connection (never shared concurrently), so this is
    # safe here.
    conn = sqlite3.connect(str(db_path), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    return conn


def init_db(db_path: Path) -> None:
    """Create the schema if needed and record the migration version.

    Idempotent: safe to call on every startup. Uses ``CREATE TABLE IF NOT
    EXISTS`` statements, so existing data is preserved.
    """
    schema_sql = _SCHEMA_FILE.read_text(encoding="utf-8")
    conn = connect(db_path)
    try:
        conn.executescript(schema_sql)
        # Apply additive column migrations for databases created before v2.
        for table, column, col_def in _ADDITIVE_COLUMNS:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
        row = conn.execute(
            "SELECT version FROM schema_migrations WHERE version = ?", (_SCHEMA_VERSION,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (_SCHEMA_VERSION, _utc_now_iso()),
            )
        conn.commit()
    finally:
        conn.close()


def current_version(db_path: Path) -> int:
    conn = connect(db_path)
    try:
        row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
        return int(row["v"]) if row and row["v"] is not None else 0
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()
