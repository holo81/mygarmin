"""Synchronization engine (real Personal API).

Pulls data from the modern Garmin Connect services the Personal API exposes.
Date selection differs per endpoint:
  * daily summary, sleep, HRV, daily heart rate: one call PER DAY (path/query date)
  * HRV range, stress range, steps range, body battery: one call PER RANGE
  * activities: a single paginated search
  * activity detail + FIT: per activity, on demand (enrich)

Per-day/per-range results are archived raw, normalized, and UPSERTed idempotently
on stable keys (calendar date or activityId). Each category runs in its own
try/except with a commit per category, so one failure never corrupts others.
"""

from __future__ import annotations

import fcntl
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import normalize as norm
from .config import Settings
from .db.database import connect
from .db.repository import Repository
from .garmin.client import GarminClient, PullResult
from .garmin.errors import (
    GarminAuthError,
    GarminError,
    GarminNotFoundError,
    GarminRateLimitError,
)

logger = logging.getLogger("mygarmin.sync")

# Per-day categories (one API call per calendar date).
PER_DAY = ["daily", "sleep", "hrv", "daily_heart_rate"]
# Per-range categories (one API call for the whole window).
PER_RANGE = ["body_battery", "weight"]
# Snapshot categories: current config / latest value (one call, date = latest day).
SNAPSHOT = ["hr_zones", "fitnessage"]
# Activities handled separately (paginated search).
DEFAULT_CATEGORIES = PER_DAY + PER_RANGE + SNAPSHOT + ["activities"]

_DAY_SECONDS = 86400
_MAX_RANGE_DAYS = 28  # Garmin rejects longer ranges (HTTP 400 seen at 37 days)


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


def _local_date(settings: Settings, ts: int) -> date:
    """Calendar date of epoch ``ts`` in the display timezone (not the server's)."""
    return datetime.fromtimestamp(ts, ZoneInfo(settings.display_timezone)).date()


def _local_midnight(settings: Settings, d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=ZoneInfo(settings.display_timezone)).timestamp())


def _chunks(start: date, end: date, days: int = _MAX_RANGE_DAYS) -> list[tuple[date, date]]:
    out = []
    s = start
    while s <= end:
        e = min(s + timedelta(days=days - 1), end)
        out.append((s, e))
        s = e + timedelta(days=1)
    return out


def _dates(start_date: date, end_date: date) -> list[date]:
    out = []
    d = start_date
    while d <= end_date:
        out.append(d)
        d += timedelta(days=1)
    return out


def _archive_raw(
    settings: Settings, repo: Repository, result: PullResult, label: str, run_id: int | None
) -> int | None:
    if not result.raw_bytes:
        return None
    try:
        sha = hashlib.sha256(result.raw_bytes).hexdigest()
        subdir = settings.raw_payload_path / result.category
        subdir.mkdir(parents=True, exist_ok=True)
        fpath = subdir / f"{label}_{sha[:12]}.json"
        if not fpath.exists():
            fpath.write_bytes(result.raw_bytes)
        return repo.insert_raw_payload(
            category=result.category,
            start_time=None,
            end_time=None,
            file_path=str(fpath),
            sha256=sha,
            byte_size=len(result.raw_bytes),
            sync_run_id=run_id,
        )
    except OSError:
        logger.warning("Failed to archive raw payload for %s", result.category)
        return None


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

    def _pace(self) -> None:
        if self.settings.sync_day_delay_seconds > 0:
            time.sleep(self.settings.sync_day_delay_seconds)

    # -- public entry points ------------------------------------------------

    def run(
        self,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
        categories: list[str] | None = None,
        trigger: str = "manual",
        category_starts: dict[str, int] | None = None,
    ) -> SyncOutcome:
        """Run a sync. ``category_starts`` gives each category its own window start
        (epoch s); categories not listed use ``start_time``.

        A non-blocking lock file next to the DB keeps two syncers (in-app auto-sync,
        ``python -m app.scheduler``, manual) from overlapping.
        """
        self.settings.ensure_dirs()
        lock_path = self.settings.database_file.with_suffix(".sync.lock")
        with open(lock_path, "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                logger.warning("Another sync is already running; skipping")
                return SyncOutcome(status="skipped", message="Another sync is already running")
            try:
                return self._run_locked(start_time, end_time, categories, trigger, category_starts)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _run_locked(
        self,
        start_time: int | None,
        end_time: int | None,
        categories: list[str] | None,
        trigger: str,
        category_starts: dict[str, int] | None,
    ) -> SyncOutcome:
        end_time = end_time or _utc_now()
        if start_time is None:
            start_time = end_time - self.settings.initial_import_days * _DAY_SECONDS
        categories = categories or DEFAULT_CATEGORIES
        starts = {c: (category_starts or {}).get(c, start_time) for c in categories}
        end_date = _local_date(self.settings, end_time)

        conn = connect(self.settings.database_file)
        repo = Repository(conn)
        outcome = SyncOutcome()
        run_id: int | None = None
        try:
            run_id = repo.start_sync_run(trigger, min(starts.values()), end_time)
            repo.commit()
            outcome.run_id = run_id

            try:
                self._get_client().verify_auth()
            except GarminError as exc:
                outcome.status = "failed"
                outcome.message = f"{type(exc).__name__}: {exc}"
                repo.finish_sync_run(run_id, "failed", 0, outcome.message)
                repo.commit()
                return outcome

            succeeded = 0
            stopped: GarminError | None = None
            for category in categories:
                start_date = _local_date(self.settings, starts[category])
                try:
                    co = self._run_category(repo, category, start_date, end_date, run_id)
                except (GarminAuthError, GarminRateLimitError) as exc:
                    stopped = exc
                    co = CategoryOutcome(category, "failed", 0, f"{type(exc).__name__}: {exc}")
                if co.status != "success" and (stopped or category not in PER_DAY):
                    repo.rollback()  # drop a half-done category; per-day keeps finished days
                outcome.categories.append(co)
                outcome.total_records += co.records
                repo.record_category_result(run_id, category, co.status, co.records, co.message)
                if co.status == "success":
                    succeeded += 1
                    repo.update_sync_state(category, end_time)
                repo.commit()
                if stopped:
                    break

            if stopped is None and succeeded == len(categories):
                outcome.status = "success"
            elif succeeded > 0:
                outcome.status = "partial"
            else:
                outcome.status = "failed"
            outcome.message = (
                f"{succeeded}/{len(categories)} categories succeeded, "
                f"{outcome.total_records} records written"
            )
            if stopped:
                outcome.message = (
                    f"Stopped early ({type(stopped).__name__}: {stopped}); " + outcome.message
                )
            repo.finish_sync_run(run_id, outcome.status, outcome.total_records, outcome.message)
            repo.commit()
            return outcome
        except Exception as exc:  # never leave the run row 'running'
            logger.exception("Sync run crashed")
            outcome.status = "failed"
            outcome.message = f"Unexpected error: {type(exc).__name__}: {exc}"
            try:
                repo.rollback()
                if run_id is not None:
                    repo.finish_sync_run(run_id, "failed", outcome.total_records, outcome.message)
                    repo.commit()
            except Exception:
                logger.exception("Could not finish sync run %s", run_id)
            return outcome
        finally:
            conn.close()

    def _run_category(
        self, repo: Repository, category: str, start_date: date, end_date: date, run_id: int
    ) -> CategoryOutcome:
        if category in PER_DAY:
            return self._sync_per_day(repo, category, start_date, end_date, run_id)
        if category in PER_RANGE:
            return self._sync_per_range(repo, category, start_date, end_date, run_id)
        if category == "activities":
            return self._sync_activities(repo, start_date, end_date, run_id)
        if category in SNAPSHOT:
            return self._sync_snapshot(repo, category, end_date, run_id)
        return CategoryOutcome(category=category, status="skipped")

    def incremental(self, trigger: str = "scheduled") -> SyncOutcome:
        conn = connect(self.settings.database_file)
        repo = Repository(conn)
        try:
            states = {s["category"]: s for s in repo.all_sync_state()}
        finally:
            conn.close()
        now = _utc_now()
        initial = now - self.settings.initial_import_days * _DAY_SECONDS
        # Each category has its own window; retired names in sync_state are ignored.
        starts = {}
        for c in DEFAULT_CATEGORIES:
            through = states[c]["last_synced_through"] if c in states else None
            starts[c] = (through - _DAY_SECONDS) if through else initial
        return self.run(
            start_time=min(starts.values()),
            end_time=now,
            trigger=trigger,
            category_starts=starts,
        )

    @staticmethod
    def _failed(co: CategoryOutcome, exc: Exception) -> CategoryOutcome:
        co.status = "failed"
        if isinstance(exc, GarminError):
            co.message = f"{type(exc).__name__}: {exc}"
        else:
            co.message = f"Unexpected error: {type(exc).__name__}: {exc}"
            logger.error("Unexpected error syncing %s", co.category, exc_info=exc)
        return co

    # -- per-day sync -------------------------------------------------------

    def _sync_per_day(
        self, repo: Repository, category: str, start_date: date, end_date: date, run_id: int
    ) -> CategoryOutcome:
        co = CategoryOutcome(category=category)
        client = self._get_client()
        records = 0
        failure: Exception | None = None
        for i, d in enumerate(_dates(start_date, end_date)):
            if i:
                self._pace()
            ds = d.isoformat()
            try:
                result = self._pull_for_day(client, category, ds)
                if result is None or result.data is None:
                    continue  # 204 / empty: no data that day
                raw_id = _archive_raw(self.settings, repo, result, ds, run_id)
                records += self._persist_day(repo, category, result, raw_id)
            except GarminNotFoundError:
                continue  # no data that day
            except (GarminAuthError, GarminRateLimitError):
                raise
            except Exception as exc:  # noqa: BLE001
                # Keep the days already stored; fail the category at the end so the
                # watermark does not advance past the gap.
                failure = failure or exc
        co.records = records
        if failure is not None:
            self._failed(co, failure)
            co.message = f"{co.message} ({records} records stored)"
        else:
            co.status = "success"
            co.message = f"{records} records"
        return co

    def _pull_for_day(self, client: GarminClient, category: str, ds: str) -> PullResult | None:
        if category == "daily":
            return client.pull("daily", query={"calendarDate": ds})
        if category == "sleep":
            return client.pull("sleep", query={"date": ds})
        if category == "hrv":
            return client.pull("hrv", path_params={"date": ds})
        if category == "daily_heart_rate":
            return client.pull("daily_heart_rate", query={"date": ds})
        return None

    def _persist_day(
        self, repo: Repository, category: str, result: PullResult, raw_id: int | None
    ) -> int:
        data = result.data
        if data is None:
            return 0
        if category == "daily":
            row = norm.normalize_daily(data)
            if not row:
                return 0
            repo.upsert_daily(row, raw_id)
            return 1
        if category == "sleep":
            row = norm.normalize_sleep(data)
            if not row:
                return 0
            repo.upsert_sleep(row, raw_id)
            return 1
        if category == "hrv":
            row = norm.normalize_hrv(data)
            if not row:
                return 0
            repo.upsert_hrv(row, raw_id)
            return 1
        if category == "daily_heart_rate":
            samples = norm.normalize_daily_hr_samples(data, self.settings.display_timezone)
            cal = data.get("calendarDate") if isinstance(data, dict) else None
            if cal and samples:
                repo.replace_daily_hr_samples(cal, samples)
                return 1
            return 0
        return 0

    # -- per-range sync -----------------------------------------------------

    def _sync_per_range(
        self, repo: Repository, category: str, start_date: date, end_date: date, run_id: int
    ) -> CategoryOutcome:
        co = CategoryOutcome(category=category)
        client = self._get_client()
        records = 0
        try:
            for i, (s, e) in enumerate(_chunks(start_date, end_date)):
                if i:
                    self._pace()
                label = f"{s}_{e}"
                if category == "body_battery":
                    result = client.pull(
                        "body_battery", query={"startDate": s.isoformat(), "endDate": e.isoformat()}
                    )
                    # body battery samples are keyed by date, not by raw_payload_id
                    _archive_raw(self.settings, repo, result, label, run_id)
                    for item in result.data or []:
                        cal, samples = norm.normalize_body_battery_report(
                            item, self.settings.display_timezone
                        )
                        if cal and samples:
                            repo.replace_body_battery_samples(cal, samples)
                            records += 1
                elif category == "weight":
                    result = client.pull(
                        "weight_range",
                        path_params={"fromDate": s.isoformat(), "toDate": e.isoformat()},
                    )
                    _archive_raw(self.settings, repo, result, label, run_id)
                    for wrow in norm.normalize_weight_range(result.data or {}):
                        repo.upsert_weight(wrow)
                        records += 1
                else:
                    co.status = "skipped"
                    return co
            co.status = "success"
            co.records = records
            co.message = f"{records} days"
            return co
        except (GarminAuthError, GarminRateLimitError):
            raise
        except Exception as exc:  # noqa: BLE001
            return self._failed(co, exc)

    # -- snapshot categories (config / latest value) ------------------------

    def _sync_snapshot(
        self, repo: Repository, category: str, end_date: date, run_id: int
    ) -> CategoryOutcome:
        co = CategoryOutcome(category=category)
        client = self._get_client()
        try:
            if category == "hr_zones":
                result = client.pull("hr_zones")
                _archive_raw(self.settings, repo, result, "zones", run_id)
                zones = norm.normalize_hr_zones(result.data if isinstance(result.data, list) else [])
                if zones:
                    repo.replace_hr_zones(zones)
                co.status = "success"
                co.records = len(zones)
                co.message = f"{len(zones)} sport zone sets"
                return co
            if category == "fitnessage":
                result = client.pull("fitnessage", path_params={"date": end_date.isoformat()})
                raw_id = _archive_raw(self.settings, repo, result, end_date.isoformat(), run_id)
                row = norm.normalize_fitness_age(result.data)
                if row:
                    repo.upsert_fitness_age(row, raw_id)
                    co.records = 1
                co.status = "success"
                co.message = "1 record" if row else "no data"
                return co
            co.status = "skipped"
            return co
        except (GarminAuthError, GarminRateLimitError):
            raise
        except Exception as exc:  # noqa: BLE001
            return self._failed(co, exc)

    # -- activities ---------------------------------------------------------

    def _sync_activities(
        self, repo: Repository, start_date: date, end_date: date, run_id: int
    ) -> CategoryOutcome:
        co = CategoryOutcome(category="activities")
        client = self._get_client()
        start_s = _local_midnight(self.settings, start_date)
        records = 0
        skipped = 0
        try:
            page = 0
            page_size = 50
            while True:
                if page:
                    self._pace()
                result = client.pull(
                    "activities_search",
                    query={"start": page * page_size, "limit": page_size},
                )
                raw_id = _archive_raw(self.settings, repo, result, f"page{page}", run_id)
                items = result.data if isinstance(result.data, list) else []
                if not items:
                    break
                stop = False
                for obj in items:
                    row = norm.normalize_activity(obj)
                    if not row:
                        continue
                    if row["start_time_seconds"] is None:
                        skipped += 1  # start_time is NOT NULL; skip just this one
                        continue
                    # Stop paging once we go older than the requested window.
                    if row["start_time_seconds"] < start_s:
                        stop = True
                        continue
                    repo.upsert_activity(row, raw_id)
                    records += 1
                if stop or len(items) < page_size:
                    break
                page += 1
                if page > 100:  # safety bound
                    break
            co.status = "success"
            co.records = records
            co.message = f"{records} activities" + (
                f", {skipped} skipped (no start time)" if skipped else ""
            )
            return co
        except (GarminAuthError, GarminRateLimitError):
            raise
        except Exception as exc:  # noqa: BLE001
            return self._failed(co, exc)

    # -- activity detail + FIT enrichment -----------------------------------

    def enrich_activity_details(
        self,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
        max_activities: int = 50,
    ) -> dict:
        """Download + decode the FIT file for stored activities to get per-second
        time-series (HR, speed, GPS, elevation, cadence, power).

        Only activities still needing a FIT (and not marked permanently unavailable)
        inside the optional ``start_time``/``end_time`` window are tried.
        """
        from .garmin.fit import parse_fit_records

        self.settings.ensure_dirs()
        conn = connect(self.settings.database_file)
        repo = Repository(conn)
        enriched = 0
        errors: list[str] = []
        try:
            client = self._get_client()
            rows = repo.activities_needing_fit(
                limit=max_activities, start_time=start_time, end_time=end_time
            )
            for n, a in enumerate(rows):
                aid = a["activity_id"] or a["summary_id"]
                if n:
                    self._pace()
                try:
                    raw = client.download_activity_file(str(aid))
                    if not raw:
                        repo.mark_fit_unavailable(a["summary_id"])
                        repo.commit()
                        continue
                    samples = parse_fit_records(raw, a["activity_type"])
                    # Only write to disk once the bytes are known to parse.
                    fpath = self.settings.fit_file_path / f"{aid}.fit.zip"
                    fpath.write_bytes(raw)
                    if samples:
                        repo.replace_activity_samples(a["summary_id"], samples)
                        enriched += 1
                    repo.set_activity_fit(a["summary_id"], str(fpath))
                    repo.commit()
                except (GarminAuthError, GarminRateLimitError) as exc:
                    repo.rollback()
                    errors.append(f"{aid}: {type(exc).__name__} (stopped)")
                    break
                except GarminNotFoundError:
                    repo.rollback()
                    repo.mark_fit_unavailable(a["summary_id"])
                    repo.commit()
                    errors.append(f"{aid}: GarminNotFoundError")
                except GarminError as exc:  # transient: retry on a later call
                    repo.rollback()
                    errors.append(f"{aid}: {type(exc).__name__}")
                except RuntimeError as exc:  # FIT SDK missing: nothing to retry per file
                    repo.rollback()
                    errors.append(f"{aid}: {exc}")
                    break
                except Exception as exc:  # noqa: BLE001 - corrupt zip / FIT: permanent, never retry
                    repo.rollback()
                    repo.mark_fit_unavailable(a["summary_id"])
                    repo.commit()
                    errors.append(f"{aid}: {type(exc).__name__}")
            return {"enriched_activities": enriched, "errors": errors}
        finally:
            conn.close()
