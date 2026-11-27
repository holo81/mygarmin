"""Persistence layer: idempotent upserts + read queries.

All writes UPSERT on Garmin's stable natural keys (summaryId / calendar_date)
so repeated syncs never create duplicates. Historical rows are never deleted by
these operations. Time-series child rows are replaced per-parent to stay in sync
with the latest payload while remaining idempotent.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Repository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # -- generic upsert helper ---------------------------------------------

    def _upsert(
        self,
        table: str,
        row: dict[str, Any],
        *,
        key_cols: list[str],
        timestamps: bool = True,
    ) -> None:
        """Insert or update ``row`` keyed on ``key_cols``.

        Sets first_seen_at on insert and updated_at on every write when
        ``timestamps`` is True and the table has those columns.
        """
        data = dict(row)
        now = _utc_now_iso()
        has_first_seen = timestamps and self._has_column(table, "first_seen_at")
        has_updated = timestamps and self._has_column(table, "updated_at")
        if has_updated:
            data["updated_at"] = now

        cols = list(data.keys())
        placeholders = ", ".join(["?"] * len(cols))
        col_list = ", ".join(cols)

        insert_cols = cols[:]
        insert_vals: list[Any] = [data[c] for c in cols]
        if has_first_seen:
            insert_cols.append("first_seen_at")
            insert_vals.append(now)
            col_list = ", ".join(insert_cols)
            placeholders = ", ".join(["?"] * len(insert_cols))

        update_cols = [c for c in cols if c not in key_cols]
        update_clause = ", ".join(f"{c}=excluded.{c}" for c in update_cols)
        conflict_cols = ", ".join(key_cols)

        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT({conflict_cols}) DO UPDATE SET {update_clause}"
        )
        self.conn.execute(sql, insert_vals)

    def _has_column(self, table: str, column: str) -> bool:
        rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r["name"] == column for r in rows)

    # -- raw payloads ------------------------------------------------------

    def insert_raw_payload(
        self,
        *,
        category: str,
        start_time: int | None,
        end_time: int | None,
        file_path: str,
        sha256: str,
        byte_size: int,
        sync_run_id: int | None,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO raw_payloads
                (category, start_time, end_time, fetched_at, file_path, sha256, byte_size, sync_run_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                category,
                start_time,
                end_time,
                _utc_now_iso(),
                file_path,
                sha256,
                byte_size,
                sync_run_id,
            ),
        )
        return int(cur.lastrowid)

    # -- domain upserts ----------------------------------------------------

    def upsert_activity(self, row: dict[str, Any], raw_payload_id: int | None = None) -> None:
        data = dict(row)
        if raw_payload_id is not None:
            data["raw_payload_id"] = raw_payload_id
        self._upsert("activities", data, key_cols=["summary_id"])

    def replace_activity_samples(
        self, activity_summary_id: str, samples: list[dict[str, Any]]
    ) -> None:
        self.conn.execute(
            "DELETE FROM activity_samples WHERE activity_summary_id = ?",
            (activity_summary_id,),
        )
        self.conn.executemany(
            """
            INSERT INTO activity_samples
                (activity_summary_id, sample_index, offset_seconds, clock_time_seconds,
                 latitude, longitude, elevation_meters, heart_rate_bpm, speed_mps,
                 cadence, power_watts, distance_meters, temperature_celsius, source)
            VALUES
                (:activity_summary_id, :sample_index, :offset_seconds, :clock_time_seconds,
                 :latitude, :longitude, :elevation_meters, :heart_rate_bpm, :speed_mps,
                 :cadence, :power_watts, :distance_meters, :temperature_celsius, :source)
            """,
            [{**s, "activity_summary_id": activity_summary_id} for s in samples],
        )
        if samples:
            self.conn.execute(
                "UPDATE activities SET has_details = 1 WHERE summary_id = ?",
                (activity_summary_id,),
            )

    def set_activity_fit(self, summary_id: str, fit_file_path: str) -> None:
        self.conn.execute(
            "UPDATE activities SET has_fit = 1, fit_file_path = ? WHERE summary_id = ?",
            (fit_file_path, summary_id),
        )

    def upsert_daily(self, row: dict[str, Any], raw_payload_id: int | None = None) -> None:
        data = dict(row)
        if raw_payload_id is not None:
            data["raw_payload_id"] = raw_payload_id
        self._upsert("daily_summaries", data, key_cols=["summary_id"])

    def replace_daily_hr_samples(self, calendar_date: str, samples: list[dict[str, Any]]) -> None:
        self.conn.execute(
            "DELETE FROM daily_hr_samples WHERE calendar_date = ?", (calendar_date,)
        )
        self.conn.executemany(
            "INSERT OR REPLACE INTO daily_hr_samples (calendar_date, offset_seconds, heart_rate_bpm)"
            " VALUES (:calendar_date, :offset_seconds, :heart_rate_bpm)",
            samples,
        )

    def upsert_sleep(self, row: dict[str, Any], raw_payload_id: int | None = None) -> None:
        data = dict(row)
        if raw_payload_id is not None:
            data["raw_payload_id"] = raw_payload_id
        self._upsert("sleep_summaries", data, key_cols=["summary_id"])

    def replace_sleep_stages(self, sleep_summary_id: str, stages: list[dict[str, Any]]) -> None:
        self.conn.execute(
            "DELETE FROM sleep_stages WHERE sleep_summary_id = ?", (sleep_summary_id,)
        )
        self.conn.executemany(
            "INSERT INTO sleep_stages (sleep_summary_id, stage, start_time_seconds, end_time_seconds)"
            " VALUES (:sleep_summary_id, :stage, :start_time_seconds, :end_time_seconds)",
            [{**s, "sleep_summary_id": sleep_summary_id} for s in stages],
        )

    def upsert_stress(self, row: dict[str, Any], raw_payload_id: int | None = None) -> None:
        data = dict(row)
        if raw_payload_id is not None:
            data["raw_payload_id"] = raw_payload_id
        self._upsert("stress_summaries", data, key_cols=["summary_id"])

    def replace_stress_samples(self, calendar_date: str, samples: list[dict[str, Any]]) -> None:
        self.conn.execute(
            "DELETE FROM stress_samples WHERE calendar_date = ?", (calendar_date,)
        )
        self.conn.executemany(
            "INSERT OR REPLACE INTO stress_samples (calendar_date, offset_seconds, stress_value)"
            " VALUES (:calendar_date, :offset_seconds, :stress_value)",
            samples,
        )

    def replace_body_battery_samples(
        self, calendar_date: str, samples: list[dict[str, Any]]
    ) -> None:
        self.conn.execute(
            "DELETE FROM body_battery_samples WHERE calendar_date = ?", (calendar_date,)
        )
        self.conn.executemany(
            "INSERT OR REPLACE INTO body_battery_samples (calendar_date, offset_seconds, body_battery_value)"
            " VALUES (:calendar_date, :offset_seconds, :body_battery_value)",
            samples,
        )

    def upsert_hrv(self, row: dict[str, Any], raw_payload_id: int | None = None) -> None:
        data = dict(row)
        if raw_payload_id is not None:
            data["raw_payload_id"] = raw_payload_id
        self._upsert("hrv_summaries", data, key_cols=["summary_id"])

    def replace_hr_zones(self, zones: list[dict[str, Any]]) -> None:
        """HR zones are current configuration; replace the whole set each sync."""
        self.conn.execute("DELETE FROM heart_rate_zones")
        now = _utc_now_iso()
        self.conn.executemany(
            """
            INSERT INTO heart_rate_zones
                (sport, training_method, resting_hr_used, lactate_threshold_hr_used,
                 max_hr_used, zone1_floor, zone2_floor, zone3_floor, zone4_floor,
                 zone5_floor, updated_at)
            VALUES
                (:sport, :training_method, :resting_hr_used, :lactate_threshold_hr_used,
                 :max_hr_used, :zone1_floor, :zone2_floor, :zone3_floor, :zone4_floor,
                 :zone5_floor, :updated_at)
            """,
            [{**z, "updated_at": now} for z in zones],
        )

    def hr_zones(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM heart_rate_zones ORDER BY sport").fetchall()

    def hr_zones_for_sport(self, sport: str) -> sqlite3.Row | None:
        row = self.conn.execute(
            "SELECT * FROM heart_rate_zones WHERE sport = ?", (sport,)
        ).fetchone()
        if row is None:
            row = self.conn.execute(
                "SELECT * FROM heart_rate_zones WHERE sport = 'DEFAULT'"
            ).fetchone()
        return row

    def upsert_fitness_age(self, row: dict[str, Any], raw_payload_id: int | None = None) -> None:
        data = dict(row)
        if raw_payload_id is not None:
            data["raw_payload_id"] = raw_payload_id
        self._upsert("fitness_age", data, key_cols=["calendar_date"])

    def latest_fitness_age(self) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM fitness_age ORDER BY calendar_date DESC LIMIT 1"
        ).fetchone()

    def upsert_weight(self, row: dict[str, Any]) -> None:
        self._upsert("weight_measurements", row, key_cols=["calendar_date"])

    def weight_range(self, start_date: str, end_date: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM weight_measurements WHERE calendar_date BETWEEN ? AND ?"
            " ORDER BY calendar_date ASC",
            (start_date, end_date),
        ).fetchall()

    def latest_weight(self) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM weight_measurements ORDER BY calendar_date DESC LIMIT 1"
        ).fetchone()

    # -- sync bookkeeping --------------------------------------------------

    def start_sync_run(self, trigger: str, window_start: int, window_end: int) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO sync_runs (started_at, status, trigger, window_start, window_end)
            VALUES (?, 'running', ?, ?, ?)
            """,
            (_utc_now_iso(), trigger, window_start, window_end),
        )
        return int(cur.lastrowid)

    def finish_sync_run(
        self, run_id: int, status: str, records_written: int, message: str | None
    ) -> None:
        self.conn.execute(
            "UPDATE sync_runs SET finished_at = ?, status = ?, records_written = ?, message = ?"
            " WHERE id = ?",
            (_utc_now_iso(), status, records_written, message, run_id),
        )

    def record_category_result(
        self,
        run_id: int,
        category: str,
        status: str,
        records_written: int,
        message: str | None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO sync_category_results (sync_run_id, category, status, records_written, message)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(sync_run_id, category) DO UPDATE SET
                status=excluded.status,
                records_written=excluded.records_written,
                message=excluded.message
            """,
            (run_id, category, status, records_written, message),
        )

    def update_sync_state(self, category: str, synced_through: int) -> None:
        self.conn.execute(
            """
            INSERT INTO sync_state (category, last_success_at, last_synced_through)
            VALUES (?, ?, ?)
            ON CONFLICT(category) DO UPDATE SET
                last_success_at=excluded.last_success_at,
                last_synced_through=excluded.last_synced_through
            """,
            (category, _utc_now_iso(), synced_through),
        )

    def get_sync_state(self, category: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM sync_state WHERE category = ?", (category,)
        ).fetchone()

    # -- read queries (used by API) ----------------------------------------

    def latest_daily(self) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM daily_summaries ORDER BY calendar_date DESC LIMIT 1"
        ).fetchone()

    def daily_range(self, start_date: str, end_date: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM daily_summaries WHERE calendar_date BETWEEN ? AND ?"
            " ORDER BY calendar_date ASC",
            (start_date, end_date),
        ).fetchall()

    def latest_sleep(self) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM sleep_summaries ORDER BY calendar_date DESC LIMIT 1"
        ).fetchone()

    def sleep_range(self, start_date: str, end_date: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM sleep_summaries WHERE calendar_date BETWEEN ? AND ?"
            " ORDER BY calendar_date ASC",
            (start_date, end_date),
        ).fetchall()

    def latest_hrv(self) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM hrv_summaries ORDER BY calendar_date DESC LIMIT 1"
        ).fetchone()

    def hrv_range(self, start_date: str, end_date: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM hrv_summaries WHERE calendar_date BETWEEN ? AND ?"
            " ORDER BY calendar_date ASC",
            (start_date, end_date),
        ).fetchall()

    def latest_stress(self) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM stress_summaries ORDER BY calendar_date DESC LIMIT 1"
        ).fetchone()

    def latest_body_battery_date(self) -> str | None:
        row = self.conn.execute(
            "SELECT calendar_date FROM body_battery_samples ORDER BY calendar_date DESC LIMIT 1"
        ).fetchone()
        return row["calendar_date"] if row else None

    def body_battery_for_date(self, calendar_date: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT offset_seconds, body_battery_value FROM body_battery_samples"
            " WHERE calendar_date = ? ORDER BY offset_seconds ASC",
            (calendar_date,),
        ).fetchall()

    def stress_samples_for_date(self, calendar_date: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT offset_seconds, stress_value FROM stress_samples"
            " WHERE calendar_date = ? ORDER BY offset_seconds ASC",
            (calendar_date,),
        ).fetchall()

    def activities(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        activity_type: str | None = None,
        start_date_s: int | None = None,
        end_date_s: int | None = None,
        search: str | None = None,
    ) -> list[sqlite3.Row]:
        clauses = ["(is_parent IS NULL OR is_parent = 0 OR is_parent = 1)"]
        params: list[Any] = []
        if activity_type:
            clauses.append("activity_type = ?")
            params.append(activity_type)
        if start_date_s is not None:
            clauses.append("start_time_seconds >= ?")
            params.append(start_date_s)
        if end_date_s is not None:
            clauses.append("start_time_seconds <= ?")
            params.append(end_date_s)
        if search:
            clauses.append("(activity_name LIKE ? OR activity_type LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])
        where = " AND ".join(clauses)
        params.extend([limit, offset])
        return self.conn.execute(
            f"SELECT * FROM activities WHERE {where} ORDER BY start_time_seconds DESC"
            " LIMIT ? OFFSET ?",
            params,
        ).fetchall()

    def count_activities(
        self,
        *,
        activity_type: str | None = None,
        start_date_s: int | None = None,
        end_date_s: int | None = None,
        search: str | None = None,
    ) -> int:
        clauses = ["1=1"]
        params: list[Any] = []
        if activity_type:
            clauses.append("activity_type = ?")
            params.append(activity_type)
        if start_date_s is not None:
            clauses.append("start_time_seconds >= ?")
            params.append(start_date_s)
        if end_date_s is not None:
            clauses.append("start_time_seconds <= ?")
            params.append(end_date_s)
        if search:
            clauses.append("(activity_name LIKE ? OR activity_type LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])
        where = " AND ".join(clauses)
        row = self.conn.execute(
            f"SELECT COUNT(*) AS c FROM activities WHERE {where}", params
        ).fetchone()
        return int(row["c"]) if row else 0

    def activity(self, summary_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM activities WHERE summary_id = ?", (summary_id,)
        ).fetchone()

    def activity_samples(self, summary_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM activity_samples WHERE activity_summary_id = ?"
            " ORDER BY sample_index ASC",
            (summary_id,),
        ).fetchall()

    def distinct_activity_types(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT activity_type FROM activities WHERE activity_type IS NOT NULL"
            " ORDER BY activity_type"
        ).fetchall()
        return [r["activity_type"] for r in rows]

    def last_sync_run(self) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()

    def recent_sync_runs(self, limit: int = 10) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM sync_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()

    def category_results(self, run_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM sync_category_results WHERE sync_run_id = ? ORDER BY category",
            (run_id,),
        ).fetchall()

    def all_sync_state(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM sync_state ORDER BY category").fetchall()

    def commit(self) -> None:
        self.conn.commit()
