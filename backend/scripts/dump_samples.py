"""Dump full real sample payloads for the working endpoints to local JSON files
under data/api_samples/ so we can design normalizers against the true schema.

These files contain YOUR real data — they are written under data/ which is
git-ignored. Run once, inspect, then they can be deleted.

Run:  python -m scripts.dump_samples
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

from app.config import get_settings
from app.garmin.token import TokenManager

TODAY = date.today()
YDAY = TODAY - timedelta(days=1)
WEEK_AGO = TODAY - timedelta(days=7)

PROBES = {
    "usersummary_daily": ("/usersummary-service/usersummary/daily", {"calendarDate": YDAY.isoformat()}),
    "sleep_dailySleep": ("/sleep-service/sleep/dailySleep", {"date": YDAY.isoformat()}),
    "hrv_daily": (f"/hrv-service/hrv/{YDAY}", {}),
    "hrv_range": (f"/hrv-service/hrv/daily/{WEEK_AGO}/{YDAY}", {}),
    "bodyBattery_reports": ("/wellness-service/wellness/bodyBattery/reports/daily", {"startDate": WEEK_AGO.isoformat(), "endDate": YDAY.isoformat()}),
    "dailyHeartRate": ("/wellness-service/wellness/dailyHeartRate", {"date": YDAY.isoformat()}),
    "stress_daily": (f"/usersummary-service/stats/stress/daily/{WEEK_AGO}/{YDAY}", {}),
    "steps_daily": (f"/usersummary-service/stats/steps/daily/{WEEK_AGO}/{YDAY}", {}),
    "activities_search": ("/activitylist-service/activities/search/activities", {"start": 0, "limit": 3}),
    "userprofile_settings": ("/userprofile-service/userprofile/settings", {}),
}


def main() -> int:
    settings = get_settings()
    out = settings.database_file.parent / "api_samples"
    out.mkdir(parents=True, exist_ok=True)
    base = settings.garmin_api_base_url.rstrip("/")
    activity_id = None
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        tok = TokenManager(settings).get_token(client)
        headers = {"Authorization": f"{tok.token_type} {tok.token}"}
        for name, (path, params) in PROBES.items():
            try:
                r = client.get(base + path, params=params, headers=headers)
                if r.status_code == 200:
                    (out / f"{name}.json").write_text(
                        json.dumps(r.json(), indent=2), encoding="utf-8"
                    )
                    print(f"saved {name} ({len(r.content)} bytes)")
                    if name == "activities_search":
                        arr = r.json()
                        if isinstance(arr, list) and arr:
                            activity_id = arr[0].get("activityId")
                else:
                    print(f"{name}: HTTP {r.status_code}")
            except httpx.HTTPError as exc:
                print(f"{name}: ERR {type(exc).__name__}")

        # Activity detail + workouts for one real activity.
        if activity_id is not None:
            for sub, p in [
                ("activity_detail", f"/activity-service/activity/{activity_id}"),
                ("activity_workouts", f"/activity-service/activity/{activity_id}/workouts"),
            ]:
                try:
                    r = client.get(base + p, headers=headers)
                    if r.status_code == 200:
                        (out / f"{sub}.json").write_text(
                            json.dumps(r.json(), indent=2), encoding="utf-8"
                        )
                        print(f"saved {sub} for activity {activity_id} ({len(r.content)} bytes)")
                    else:
                        print(f"{sub}: HTTP {r.status_code}")
                except httpx.HTTPError as exc:
                    print(f"{sub}: ERR {type(exc).__name__}")
            # Try the FIT download endpoint (just report status + size).
            try:
                r = client.get(base + f"/download-service/files/activity/{activity_id}", headers=headers)
                print(f"download activity file: HTTP {r.status_code} ({len(r.content)} bytes, ct={r.headers.get('content-type')})")
            except httpx.HTTPError as exc:
                print(f"download: ERR {type(exc).__name__}")
    print(f"\nSamples written to: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
