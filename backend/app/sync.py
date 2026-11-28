"""Synchronization engine.

Pipeline per sync run:
  1. Obtain a valid access token (via the client/token manager).
  2. For each enabled data category, pull the requested UTC time window in
     API-sized sub-windows (SYNC_WINDOW_DAYS).
  3. Archive the raw response bytes to disk and index them (recoverable raw).
  4. Normalize the payload into DB rows.
  5. UPSERT idempotently on stable keys.
  6. Record per-category + overall results and advance sync_state.

Partial-failure safety: each category is wrapped in its own try/except and its
own DB transaction (commit per category). A failure in one category does not
roll back or corrupt previously-written categories, and the overall run is
marked ``partial`` rather than ``failed`` when at least one category succeeded.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field

from . import normalize as norm
from .config import Settings
from .db.database import connect
from .db.repository import Repository
from .garmin.client import GarminClient, PullResult
from .garmin.errors import GarminAuthError, GarminConfigError, GarminError

logger = logging.getLogger("mygarmin.sync")

# Health categories indexed by calendar_date in their payloads.
HEALTH_CATEGORIES = ["dailies", "sleeps", "stress", "hrv"]
ACTIVITY_CATEGORIES = ["activities"]
DEFAULT_CATEGORIES = HEALTH_CATEGORIES + ACTIVITY_CATEGORIES

_DAY_SECONDS = 86400


@dataclass
class CategoryOutcome:
    category: str
    status: str = "skipped"
    records: int = 0
    message: str | None = None


@dataclass
class SyncOutcome:
    run_id: int | None = None
    status: str = "unknown"
    total_records: int = 0
    categories: list[CategoryOutcome] = field(default_factory=list)
    message: str | None = None

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "total_records": self.total_records,
            "message": self.message,
            "categories": [
                {
                    "category": c.category,
                    "status": c.status,
                    "records": c.records,
                    "message": c.message,
                }
                for c in self.categories
            ],
        }


def _utc_now() -> int:
    return int(time.time())


def _windows(start: int, end: int, window_days: int) -> list[tuple[int, int]]:
    step = max(1, window_days) * _DAY_SECONDS
    out: list[tuple[int, int]] = []
    s = start
    while s < end:
        e = min(s + step, end)
        out.append((s, e))
        s = e
    return out


def _archive_raw(
    settings: Settings,
    repo: Repository,
    result: PullResult,
    sync_run_id: int | None,
) -> int | None:
    """Write the raw response bytes to disk and index them. Best-effort."""
    if not result.raw_bytes:
        return None
    try:
        sha = hashlib.sha256(result.raw_bytes).hexdigest()
        subdir = settings.raw_payload_path / result.category
        subdir.mkdir(parents=True, exist_ok=True)
        fname = f"{result.start_time}_{result.end_time}_{sha[:12]}.json"
        fpath = subdir / fname
        if not fpath.exists():
            fpath.write_bytes(result.raw_bytes)
        return repo.insert_raw_payload(
            category=result.category,
            start_time=result.start_time,
            end_time=result.end_time,
            file_path=str(fpath),
            sha256=sha,
            byte_size=len(result.raw_bytes),
            sync_run_id=sync_run_id,
        )
    except OSError:
        logger.warning("Failed to archive raw payload for %s", result.category)
        return None


def _as_list(data) -> list:
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # Some endpoints wrap results; accept a few common shapes.
        for key in ("items", "results", "data", "hrvSummaries"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    return []


class SyncEngine:
    def __init__(self, settings: Settings, client: GarminClient | None = None) -> None:
        self.settings = settings
        self._client = client
        self._owns_client = client is None

    def _get_client(self) -> GarminClient:
        if self._client is None:
            self._client = GarminClient(self.settings)
        return self._client

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()

    # -- public entry points ------------------------------------------------

    def run(
        self,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
        categories: list[str] | None = None,
        trigger: str = "manual",
    ) -> SyncOutcome:
        """Run a sync over [start_time, end_time) for the given categories."""
        self.settings.ensure_dirs()
        end_time = end_time or _utc_now()
        if start_time is None:
            start_time = end_time - self.settings.initial_import_days * _DAY_SECONDS
        categories = categories or DEFAULT_CATEGORIES

        conn = connect(self.settings.database_file)
        repo = Repository(conn)
        outcome = SyncOutcome()
        try:
            run_id = repo.start_sync_run(trigger, start_time, end_time)
            repo.commit()
            outcome.run_id = run_id

            # Validate auth up front so a bad key fails fast and clearly.
            try:
                self._get_client().verify_auth()
            except GarminConfigError as exc:
                outcome.status = "failed"
                outcome.message = str(exc)
                repo.finish_sync_run(run_id, "failed", 0, outcome.message)
                repo.commit()
                return outcome
            except GarminAuthError as exc:
                # Permanent: do not attempt category pulls.
                outcome.status = "failed"
                outcome.message = str(exc)
                repo.finish_sync_run(run_id, "failed", 0, outcome.message)
                repo.commit()
                return outcome

            succeeded = 0
            for category in categories:
                co = self._sync_category(repo, category, start_time, end_time, run_id)
                outcome.categories.append(co)
                outcome.total_records += co.records
                repo.record_category_result(
                    run_id, category, co.status, co.records, co.message
                )
                if co.status == "success":
                    succeeded += 1
                    repo.update_sync_state(category, end_time)
                repo.commit()  # commit per category -> partial-failure safe

            if succeeded == len(categories):
                outcome.status = "success"
            elif succeeded > 0:
                outcome.status = "partial"
            else:
                outcome.status = "failed"
            outcome.message = (
                f"{succeeded}/{len(categories)} categories succeeded, "
                f"{outcome.total_records} records written"
            )
            repo.finish_sync_run(
                run_id, outcome.status, outcome.total_records, outcome.message
            )
            repo.commit()
            return outcome
        finally:
            conn.close()

    def enrich_activity_details(
        self,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
        max_activities: int = 50,
    ) -> dict:
        """Fetch activityDetails + .FIT time-series for recently stored activities.

        Pulls the activityDetails window and, where a FIT file is available,
        downloads and decodes it for richer per-second samples. Degrades
        gracefully: activities without details/FIT keep their summary only.
        """
        self.settings.ensure_dirs()
        end_time = end_time or _utc_now()
        if start_time is None:
            start_time = end_time - self.settings.initial_import_days * _DAY_SECONDS

        conn = connect(self.settings.database_file)
        repo = Repository(conn)
        enriched = 0
        fit_count = 0
        errors: list[str] = []
        try:
            client = self._get_client()
            for ws, we in _windows(start_time, end_time, self.settings.sync_window_days):
                try:
                    result = client.pull("activity_details", ws, we)
                except GarminError as exc:
                    errors.append(f"details {ws}: {type(exc).__name__}")
                    continue
                for obj in _as_list(result.data):
                    summary = obj.get("summary") if isinstance(obj, dict) else None
                    key = None
                    if isinstance(summary, dict):
                        key = summary.get("summaryId") or summary.get("activityId")
                    key = key or (obj.get("summaryId") if isinstance(obj, dict) else None)
                    if key is None:
                        continue
                    samples = norm.normalize_activity_samples(obj)
                    if samples:
                        repo.replace_activity_samples(str(key), samples)
                        enriched += 1
                    # Try FIT if the summary advertises a file id + token.
                    file_id = obj.get("fileId") or obj.get("activityFileId") if isinstance(obj, dict) else None
                    file_token = obj.get("fileToken") if isinstance(obj, dict) else None
                    if file_id:
                        try:
                            fit_bytes = client.download_activity_file(str(file_id), file_token)
                            if fit_bytes:
                                from .garmin.fit import parse_fit_records

                                fpath = self.settings.fit_file_path / f"{key}.fit"
                                fpath.write_bytes(fit_bytes)
                                fit_samples = parse_fit_records(fit_bytes)
                                if fit_samples:
                                    repo.replace_activity_samples(str(key), fit_samples)
                                repo.set_activity_fit(str(key), str(fpath))
                                fit_count += 1
                        except (GarminError, OSError, RuntimeError) as exc:
                            errors.append(f"fit {key}: {type(exc).__name__}")
                repo.commit()
            return {
                "enriched_activities": enriched,
                "fit_files": fit_count,
                "errors": errors,
            }
        finally:
            conn.close()

    def incremental(self, trigger: str = "scheduled") -> SyncOutcome:
        """Sync from the earliest category's last-synced point up to now.

        Overlaps the previous window by one day to catch late-arriving/updated
        summaries. Idempotent upserts make the overlap harmless.
        """
        conn = connect(self.settings.database_file)
        repo = Repository(conn)
        try:
            states = {s["category"]: s for s in repo.all_sync_state()}
        finally:
            conn.close()
        now = _utc_now()
        synced_points = [
            s["last_synced_through"]
            for s in states.values()
            if s["last_synced_through"] is not None
        ]
        missing_categories = any(
            category not in states or states[category]["last_synced_through"] is None
            for category in DEFAULT_CATEGORIES
        )
        if missing_categories:
            initial_start = now - self.settings.initial_import_days * _DAY_SECONDS
            start = min(initial_start, min(synced_points) - _DAY_SECONDS) if synced_points else initial_start
        elif synced_points:
            start = min(synced_points) - _DAY_SECONDS
        else:
            start = now - self.settings.initial_import_days * _DAY_SECONDS
        return self.run(start_time=start, end_time=now, trigger=trigger)

    # -- per-category sync --------------------------------------------------

    def _sync_category(
        self, repo: Repository, category: str, start: int, end: int, run_id: int
    ) -> CategoryOutcome:
        co = CategoryOutcome(category=category)
        try:
            client = self._get_client()
            records = 0
            for ws, we in _windows(start, end, self.settings.sync_window_days):
                result = client.pull(category, ws, we)
                raw_id = _archive_raw(self.settings, repo, result, run_id)
                records += self._persist(repo, category, result, raw_id)
            co.status = "success"
            co.records = records
            co.message = f"{records} records"
            return co
        except GarminAuthError:
            # Propagate up: a permanent auth failure should abort further work.
            raise
        except GarminError as exc:
            co.status = "failed"
            co.message = f"{type(exc).__name__}: {exc}"
            logger.warning("Category %s failed: %s", category, co.message)
            return co
        except Exception as exc:
            co.status = "failed"
            co.message = f"Unexpected error: {type(exc).__name__}: {exc}"
            logger.exception("Unexpected error syncing %s", category)
            return co

    def _persist(
        self, repo: Repository, category: str, result: PullResult, raw_id: int | None
    ) -> int:
        items = _as_list(result.data)
        count = 0
        if category == "dailies":
            for obj in items:
                row = norm.normalize_daily(obj)
                if not row:
                    continue
                repo.upsert_daily(row, raw_id)
                hr = norm.normalize_daily_hr_samples(obj)
                if row["calendar_date"] and hr:
                    repo.replace_daily_hr_samples(row["calendar_date"], hr)
                stress_row = norm.normalize_stress(obj)
                if stress_row and stress_row["body_battery_level"] is not None:
                    repo.upsert_stress(stress_row, raw_id)
                count += 1
        elif category == "sleeps":
            for obj in items:
                row = norm.normalize_sleep(obj)
                if not row:
                    continue
                repo.upsert_sleep(row, raw_id)
                stages = norm.normalize_sleep_stages(obj)
                if stages:
                    repo.replace_sleep_stages(row["summary_id"], stages)
                count += 1
        elif category == "stress":
            for obj in items:
                row = norm.normalize_stress(obj)
                if not row:
                    continue
                if row["body_battery_level"] is not None:
                    repo.upsert_stress(row, raw_id)
                if row["calendar_date"]:
                    ss = norm.normalize_stress_samples(obj)
                    if ss:
                        repo.replace_stress_samples(row["calendar_date"], ss)
                    bb = norm.normalize_body_battery_samples(obj)
                    if bb:
                        repo.replace_body_battery_samples(row["calendar_date"], bb)
                count += 1
        elif category == "hrv":
            for obj in items:
                row = norm.normalize_hrv(obj)
                if not row:
                    continue
                repo.upsert_hrv(row, raw_id)
                count += 1
        elif category == "activities":
            for obj in items:
                row = norm.normalize_activity(obj)
                if not row:
                    continue
                repo.upsert_activity(row, raw_id)
                count += 1
        else:
            logger.info("No persister for category %s; raw archived only", category)
        return count
