"""FastAPI application: serves locally-stored Garmin data to the frontend.

Design:
  * Read endpoints serve ONLY from SQLite. They never call Garmin inline, so the
    dashboard stays responsive and usable even when Garmin is unavailable.
  * The single mutating endpoint (/api/sync) requires a bearer token
    (SYNC_API_TOKEN) so an exposed instance cannot be driven by anyone on the LAN.
  * Every response includes sync freshness so the UI can surface stale data.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .. import export
from ..config import get_settings
from ..db.database import connect, init_db
from ..db.repository import Repository
from ..sync import SyncEngine
from . import presenter as pv

_DAY = 86400


logger = logging.getLogger("mygarmin.autosync")


def _auto_sync() -> None:
    # Skip (don't queue) if a manual sync holds the lock.
    if not _sync_lock.acquire(blocking=False):
        return
    try:
        engine = SyncEngine(get_settings())
        try:
            outcome = engine.incremental(trigger="scheduled")
            engine.enrich_activity_details()
            logger.info("Auto sync: %s (%s)", outcome.status, outcome.message)
        finally:
            engine.close()
    except Exception:
        logger.exception("Auto sync raised")
    finally:
        _sync_lock.release()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    init_db(settings.database_file)
    scheduler = None
    if settings.auto_sync_minutes > 0 and settings.has_api_key:
        scheduler = BackgroundScheduler(timezone="UTC")
        scheduler.add_job(
            _auto_sync,
            "interval",
            minutes=settings.auto_sync_minutes,
            next_run_time=datetime.now(UTC),  # also sync right at startup
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
        logger.info("Auto sync every %d min", settings.auto_sync_minutes)
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="mygarmin", version="0.1.0", lifespan=lifespan)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Serialize sync runs so a manual trigger can't overlap a scheduled one.
_sync_lock = threading.Lock()


def get_repo() -> Any:
    settings = get_settings()
    conn = connect(settings.database_file)
    try:
        yield Repository(conn)
    finally:
        conn.close()


def require_sync_token(authorization: str | None = Header(default=None)) -> None:
    settings = get_settings()
    expected = settings.sync_api_token.strip()
    if not expected:
        # No token configured -> sync is unprotected. This is convenient for a
        # localhost-only deployment. If you expose the app on a network, set
        # SYNC_API_TOKEN to require a bearer token (see docs/SECURITY.md).
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    provided = authorization.split(" ", 1)[1].strip()
    # Constant-time comparison.
    import hmac

    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Invalid sync token.")


def _sync_meta(repo: Repository) -> dict[str, Any]:
    settings = get_settings()
    last = repo.last_sync_run()
    states = repo.all_sync_state()
    now = int(time.time())
    newest_through = max(
        (s["last_synced_through"] for s in states if s["last_synced_through"]),
        default=None,
    )
    stale = None
    if newest_through is not None:
        stale = (now - newest_through) > 2 * _DAY
    return {
        "dataSource": "mock" if not settings.is_production and _has_mock(last) else "garmin",
        "appEnv": settings.app_env,
        "lastSync": dict(last) if last else None,
        "syncState": [dict(s) for s in states],
        "isStale": stale,
        "displayTimezone": settings.display_timezone,
        "unitSystem": settings.unit_system,
    }


def _has_mock(last: sqlite3.Row | None) -> bool:
    return bool(last and last["trigger"] == "mock")


# --- health / meta ---------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "time": datetime.now(UTC).isoformat()}


@app.get("/api/meta")
def meta(repo: Repository = Depends(get_repo)) -> dict:
    return _sync_meta(repo)


# --- overview --------------------------------------------------------------


@app.get("/api/overview")
def overview(repo: Repository = Depends(get_repo)) -> dict:
    daily = repo.latest_daily()
    sleep = repo.latest_sleep()
    hrv = repo.latest_hrv()

    # 7-day activity summary window based on the latest daily record.
    seven: list[dict] = []
    if daily:
        end_date = daily["calendar_date"]
        try:
            ed = date.fromisoformat(end_date)
            sd = ed - timedelta(days=6)
            for r in repo.daily_range(sd.isoformat(), ed.isoformat()):
                seven.append(pv.daily_view(r))
        except ValueError:
            pass

    recent_activities = [pv.activity_summary_view(a) for a in repo.activities(limit=8)]

    body_battery = []
    bb_date = repo.latest_body_battery_date()
    if bb_date:
        bb = repo.body_battery_for_date(bb_date)
        body_battery = [
            {"offsetSeconds": r["offset_seconds"], "value": r["body_battery_value"]}
            for r in bb
        ]

    fitness_age = repo.latest_fitness_age()

    return {
        "meta": _sync_meta(repo),
        "today": {
            "daily": pv.daily_view(daily) if daily else None,
            "sleep": pv.sleep_view(sleep) if sleep else None,
            "hrv": pv.hrv_view(hrv) if hrv else None,
            "fitnessAge": pv.fitness_age_view(fitness_age) if fitness_age else None,
            "stress": (
                {
                    "calendarDate": bb_date,
                    "bodyBatteryLevel": body_battery[-1]["value"] if body_battery else None,
                    "bodyBattery": body_battery,
                }
                if bb_date
                else None
            ),
        },
        "sevenDay": seven,
        "recentActivities": recent_activities,
    }


# --- activities ------------------------------------------------------------


@app.get("/api/activities")
def list_activities(
    repo: Repository = Depends(get_repo),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    type: str | None = Query(default=None),
    start: str | None = Query(default=None, description="ISO date yyyy-mm-dd"),
    end: str | None = Query(default=None, description="ISO date yyyy-mm-dd"),
    search: str | None = Query(default=None),
) -> dict:
    start_s = _iso_date_to_epoch("start", start)
    end_s = _iso_date_to_epoch("end", end, end_of_day=True)
    rows = repo.activities(
        limit=limit,
        offset=offset,
        activity_type=type,
        start_date_s=start_s,
        end_date_s=end_s,
        search=search,
    )
    total = repo.count_activities(
        activity_type=type, start_date_s=start_s, end_date_s=end_s, search=search
    )
    return {
        "meta": _sync_meta(repo),
        "total": total,
        "limit": limit,
        "offset": offset,
        "activityTypes": repo.distinct_activity_types(),
        "items": [pv.activity_summary_view(r) for r in rows],
    }


@app.get("/api/hr-zones")
def hr_zones(repo: Repository = Depends(get_repo)) -> dict:
    return {"meta": _sync_meta(repo), "zones": pv.hr_zones_view(repo.hr_zones())}


@app.get("/api/export/health-snapshot")
def health_snapshot_export(repo: Repository = Depends(get_repo)) -> dict:
    """Self-contained JSON snapshot of the latest day's health, built for an AI coach."""
    settings = get_settings()
    daily = repo.latest_daily()
    sleep = repo.latest_sleep()
    hrv = repo.latest_hrv()

    anchor = None
    for row in (daily, sleep, hrv):
        if row is not None:
            anchor = row["calendar_date"]
            break
    if anchor is None:
        raise HTTPException(status_code=404, detail="No health data stored yet.")

    try:
        ed = date.fromisoformat(anchor)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Stored calendar date is malformed.") from None
    d7 = (ed - timedelta(days=6)).isoformat()
    d30 = (ed - timedelta(days=29)).isoformat()
    end = ed.isoformat()

    bb_date = repo.latest_body_battery_date()
    body_battery = repo.body_battery_for_date(bb_date) if bb_date else []

    return export.build_health_snapshot_export(
        daily=daily,
        sleep=sleep,
        hrv=hrv,
        body_battery=body_battery,
        body_battery_date=bb_date,
        fitness_age=repo.latest_fitness_age(),
        daily_7=repo.daily_range(d7, end),
        daily_30=repo.daily_range(d30, end),
        sleep_7=repo.sleep_range(d7, end),
        sleep_30=repo.sleep_range(d30, end),
        hrv_7=repo.hrv_range(d7, end),
        hrv_30=repo.hrv_range(d30, end),
        unit_system=settings.unit_system,
    )


def _zone_config(repo: Repository, row) -> tuple[list[int] | None, int | None]:
    """The athlete's configured (Z1..Z5 bpm floors, max HR) for this sport, when set."""
    zone_row = repo.hr_zones_for_sport((row["activity_type"] or "").upper())
    if zone_row is None:
        return None, None
    floors = [zone_row[f"zone{i}_floor"] for i in range(1, 6)]
    return (floors if all(f is not None for f in floors) else None), zone_row["max_hr_used"]


@app.get("/api/activities/{summary_id}/export")
def activity_export(summary_id: str, repo: Repository = Depends(get_repo)) -> dict:
    """Self-contained JSON summary of one activity, built for an AI coach."""
    row = repo.activity(summary_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    settings = get_settings()
    samples = repo.activity_samples(summary_id)
    zone_floors, max_hr_cfg = _zone_config(repo, row)
    return export.build_activity_coach_export(
        row, samples, settings.unit_system, zone_floors, max_hr_cfg
    )


@app.get("/api/activities/{summary_id}")
def activity_detail(summary_id: str, repo: Repository = Depends(get_repo)) -> dict:
    row = repo.activity(summary_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    raw_samples = repo.activity_samples(summary_id)
    samples = [pv.sample_view(s) for s in raw_samples]
    view = pv.activity_summary_view(row)
    derived: dict[str, Any] = {"hrZones": None, "splitsPerKm": None}
    if raw_samples:
        floors, max_hr_cfg = _zone_config(repo, row)
        max_hr, _ = export.estimate_max_hr(raw_samples, view.get("maxHrBpm"), max_hr_cfg)
        derived["hrZones"] = export.hr_zones(raw_samples, max_hr, floors)
        derived["splitsPerKm"] = export.splits(raw_samples, 1000)
    has_gps = any(s["latitude"] is not None and s["longitude"] is not None for s in samples)
    has_hr = any(s["heartRateBpm"] is not None for s in samples)
    has_elev = any(s["elevationMeters"] is not None for s in samples)
    has_power = any(s["powerWatts"] is not None for s in samples)
    has_cadence = any(s["cadence"] is not None for s in samples)
    return {
        "meta": _sync_meta(repo),
        "activity": view,
        "samples": samples,
        # Reused from the coach export so the UI and the export agree.
        "derived": derived,
        "available": {
            "gps": has_gps,
            "heartRate": has_hr,
            "elevation": has_elev,
            "power": has_power,
            "cadence": has_cadence,
            "samples": len(samples) > 0,
        },
    }


# --- health trends ---------------------------------------------------------


@app.get("/api/trends")
def trends(
    repo: Repository = Depends(get_repo),
    range: str = Query(default="30d", pattern=r"^(7d|30d|90d|all)$"),
) -> dict:
    end_date = _latest_calendar_date(repo)
    if end_date is None:
        return {"meta": _sync_meta(repo), "range": range, "series": {}}

    try:
        ed = date.fromisoformat(end_date)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Stored calendar date is malformed.") from None
    if range == "all":
        sd = date(2000, 1, 1)
    else:
        days = {"7d": 7, "30d": 30, "90d": 90}[range]
        sd = ed - timedelta(days=days - 1)
    start_date = sd.isoformat()

    dailies = [pv.daily_view(r) for r in repo.daily_range(start_date, end_date)]
    sleeps = [pv.sleep_view(r) for r in repo.sleep_range(start_date, end_date)]
    hrvs = [pv.hrv_view(r) for r in repo.hrv_range(start_date, end_date)]
    weights = repo.weight_range(start_date, end_date)

    return {
        "meta": _sync_meta(repo),
        "range": range,
        "startDate": start_date,
        "endDate": end_date,
        "series": {
            "restingHeartRate": [
                {"date": d["calendarDate"], "value": d["restingHrBpm"]} for d in dailies
            ],
            "steps": [{"date": d["calendarDate"], "value": d["steps"]} for d in dailies],
            "stress": [
                {"date": d["calendarDate"], "value": d["avgStressLevel"]} for d in dailies
            ],
            "intensityMinutes": [
                {"date": d["calendarDate"], "value": d["intensityMinutes"]} for d in dailies
            ],
            "sleepDuration": [
                {
                    "date": s["calendarDate"],
                    "value": s["durationSeconds"],
                    "deep": s["deepSeconds"],
                    "light": s["lightSeconds"],
                    "rem": s["remSeconds"],
                    "awake": s["awakeSeconds"],
                    "score": s["overallScoreValue"],
                }
                for s in sleeps
            ],
            "hrv": [
                {
                    "date": h["calendarDate"],
                    "value": h["lastNightAvgMs"],
                    "baselineLow": h["baselineLowMs"],
                    "baselineHigh": h["baselineHighMs"],
                    "status": h["status"],
                }
                for h in hrvs
            ],
            "weight": [
                {
                    # Convert grams -> kg for the chart; source stays in grams.
                    "date": w["calendar_date"],
                    "value": round(w["weight_grams"] / 1000, 2) if w["weight_grams"] is not None else None,
                    "bmi": w["bmi"],
                }
                for w in weights
            ],
        },
    }


# --- sync ------------------------------------------------------------------


@app.get("/api/sync/status")
def sync_status(repo: Repository = Depends(get_repo)) -> dict:
    runs = repo.recent_sync_runs(limit=10)
    out = []
    for r in runs:
        d = dict(r)
        d["categories"] = [dict(c) for c in repo.category_results(r["id"])]
        out.append(d)
    return {"meta": _sync_meta(repo), "runs": out}


@app.post("/api/sync", dependencies=[Depends(require_sync_token)])
def trigger_sync(
    days: int = Query(default=0, ge=0, le=3650),
    initial: bool = Query(default=False),
    enrich: bool = Query(default=False),
) -> JSONResponse:
    settings = get_settings()
    if not _sync_lock.acquire(blocking=False):
        return JSONResponse(
            status_code=409, content={"detail": "A sync is already running."}
        )
    try:
        engine = SyncEngine(settings)
        try:
            now = int(time.time())
            if initial:
                start = now - settings.initial_import_days * _DAY
                outcome = engine.run(start_time=start, end_time=now, trigger="initial")
            elif days:
                start = now - days * _DAY
                outcome = engine.run(start_time=start, end_time=now, trigger="manual")
            else:
                outcome = engine.incremental(trigger="manual")
            result = outcome.to_dict()
            if enrich:
                enrich_start = now - (days or settings.initial_import_days) * _DAY
                result["enrich"] = engine.enrich_activity_details(
                    start_time=enrich_start, end_time=now
                )
            if outcome.status == "skipped":  # another process holds the sync file lock
                return JSONResponse(
                    status_code=409, content={"detail": "A sync is already running elsewhere."}
                )
            status_code = 200 if outcome.status in ("success", "partial") else 502
            return JSONResponse(status_code=status_code, content=result)
        finally:
            engine.close()
    finally:
        _sync_lock.release()


# --- helpers ---------------------------------------------------------------


def _iso_date_to_epoch(name: str, d: str | None, *, end_of_day: bool = False) -> int | None:
    """Local-midnight epoch (display timezone) of `d`; end_of_day gives the last second of that day."""
    if not d:
        return None
    try:
        dt = date.fromisoformat(d)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid {name}: expected yyyy-mm-dd.") from None
    try:
        tz = ZoneInfo(get_settings().display_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        tz = UTC
    if end_of_day:
        nxt = dt + timedelta(days=1)
        return int(datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz).timestamp()) - 1
    return int(datetime(dt.year, dt.month, dt.day, tzinfo=tz).timestamp())


def _latest_calendar_date(repo: Repository) -> str | None:
    row = repo.latest_daily()
    return row["calendar_date"] if row else None
