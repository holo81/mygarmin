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
_SCHEMA_VERSION = 1


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with sane pragmas and row access by name."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0)
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
