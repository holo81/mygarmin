"""FastAPI application: serves locally-stored Garmin data to the frontend.

Design:
  * Read endpoints serve ONLY from SQLite. They never call Garmin inline, so the
    dashboard stays responsive and usable even when Garmin is unavailable.
  * The single mutating endpoint (/api/sync) requires a bearer token
    (SYNC_API_TOKEN) so an exposed instance cannot be driven by anyone on the LAN.
  * Every response includes sync freshness so the UI can surface stale data.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..config import get_settings
from ..db.database import connect, init_db
from ..db.repository import Repository
from ..sync import SyncEngine
from . import presenter as pv

_DAY = 86400


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    init_db(settings.database_file)
    yield


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
    stress = repo.latest_stress()

    # 7-day activity summary window based on the latest daily record.
    seven: list[dict] = []
    if daily:
        end_date = daily["calendar_date"]
        from datetime import date, timedelta

        try:
            ed = date.fromisoformat(end_date)
            sd = ed - timedelta(days=6)
            for r in repo.daily_range(sd.isoformat(), ed.isoformat()):
                seven.append(pv.daily_view(r))
        except ValueError:
            pass

    recent_activities = [pv.activity_summary_view(a) for a in repo.activities(limit=8)]

    body_battery = []
    if stress:
        bb = repo.body_battery_for_date(stress["calendar_date"])
        body_battery = [
            {"offsetSeconds": r["offset_seconds"], "value": r["body_battery_value"]}
            for r in bb
        ]

    return {
        "meta": _sync_meta(repo),
        "today": {
            "daily": pv.daily_view(daily) if daily else None,
            "sleep": pv.sleep_view(sleep) if sleep else None,
            "hrv": pv.hrv_view(hrv) if hrv else None,
            "stress": (
                {
                    "calendarDate": stress["calendar_date"],
                    "bodyBatteryLevel": stress["body_battery_level"],
                    "bodyBattery": body_battery,
                }
                if stress
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
    start_s = _iso_date_to_epoch(start)
    end_s = _iso_date_to_epoch(end, end_of_day=True)
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


@app.get("/api/activities/{summary_id}")
def activity_detail(summary_id: str, repo: Repository = Depends(get_repo)) -> dict:
    row = repo.activity(summary_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    samples = [pv.sample_view(s) for s in repo.activity_samples(summary_id)]
    has_gps = any(s["latitude"] is not None and s["longitude"] is not None for s in samples)
    has_hr = any(s["heartRateBpm"] is not None for s in samples)
    has_elev = any(s["elevationMeters"] is not None for s in samples)
    has_power = any(s["powerWatts"] is not None for s in samples)
    has_cadence = any(s["cadence"] is not None for s in samples)
    return {
        "meta": _sync_meta(repo),
        "activity": pv.activity_summary_view(row),
        "samples": samples,
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

    from datetime import date, timedelta

    ed = date.fromisoformat(end_date)
    if range == "all":
        sd = date(2000, 1, 1)
    else:
        days = {"7d": 7, "30d": 30, "90d": 90}[range]
        sd = ed - timedelta(days=days - 1)
    start_date = sd.isoformat()

    dailies = [pv.daily_view(r) for r in repo.daily_range(start_date, end_date)]
    sleeps = [pv.sleep_view(r) for r in repo.sleep_range(start_date, end_date)]
    hrvs = [pv.hrv_view(r) for r in repo.hrv_range(start_date, end_date)]

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
            status_code = 200 if outcome.status in ("success", "partial") else 502
            return JSONResponse(status_code=status_code, content=result)
        finally:
            engine.close()
    finally:
        _sync_lock.release()


# --- helpers ---------------------------------------------------------------


def _iso_date_to_epoch(d: str | None, *, end_of_day: bool = False) -> int | None:
    if not d:
        return None
    try:
        from datetime import date

        dt = date.fromisoformat(d)
        base = int(
            datetime(dt.year, dt.month, dt.day, tzinfo=UTC).timestamp()
        )
        return base + (_DAY - 1 if end_of_day else 0)
    except ValueError:
        return None


def _latest_calendar_date(repo: Repository) -> str | None:
    row = repo.latest_daily()
    return row["calendar_date"] if row else None
