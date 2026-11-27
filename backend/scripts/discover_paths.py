"""Probe the REAL Personal API paths (from the official Swagger) and print the
status + a compact shape of each response, so we can confirm the live contract
for this account before finalizing the client. Prints NO secrets and truncates
response bodies.

Run:  python -m scripts.discover_paths
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta

import httpx

from app.config import get_settings
from app.garmin.token import TokenManager

TODAY = date.today()
YDAY = TODAY - timedelta(days=1)
WEEK_AGO = TODAY - timedelta(days=7)
MONTH_AGO = TODAY - timedelta(days=30)

# (label, path, query-params) using the official Swagger routes.
PROBES: list[tuple[str, str, dict]] = [
    ("usersummary.daily", "/usersummary-service/usersummary/daily", {"calendarDate": YDAY.isoformat()}),
    ("usersummary.v2", "/usersummary-service/v2/dailysummaries", {"fromDate": WEEK_AGO.isoformat(), "untilDate": YDAY.isoformat()}),
    ("steps.daily", f"/usersummary-service/stats/steps/daily/{WEEK_AGO}/{YDAY}", {}),
    ("stress.daily", f"/usersummary-service/stats/stress/daily/{WEEK_AGO}/{YDAY}", {}),
    ("hydration.daily", f"/usersummary-service/stats/hydration/daily/{WEEK_AGO}/{YDAY}", {}),
    ("sleep.dailySleep", "/sleep-service/sleep/dailySleep", {"date": YDAY.isoformat()}),
    ("sleep.byDate", "/sleep-service/sleep/dailySleepSummariesByDate", {"fromDate": WEEK_AGO.isoformat(), "untilDate": YDAY.isoformat()}),
    ("hrv.daily", f"/hrv-service/hrv/{YDAY}", {}),
    ("hrv.range", f"/hrv-service/hrv/daily/{WEEK_AGO}/{YDAY}", {}),
    ("bodyBattery.reports", "/wellness-service/wellness/bodyBattery/reports/daily", {"startDate": WEEK_AGO.isoformat(), "endDate": YDAY.isoformat()}),
    ("dailyHeartRate", "/wellness-service/wellness/dailyHeartRate", {"date": YDAY.isoformat()}),
    ("hrZones", "/biometric-service/heartRateZones/v2", {}),
    ("fitnessage", f"/fitnessage-service/fitnessage/v2/{YDAY}", {}),
    ("weight.range", f"/weight-service/weight/range/{WEEK_AGO}/{YDAY}", {}),
    ("activities.search", "/activitylist-service/activities/search/activities", {"start": 0, "limit": 5}),
    ("wellnessactivity.range", f"/wellnessactivity-service/activity/summary/range/{MONTH_AGO}/{YDAY}", {}),
    ("userprofile.settings", "/userprofile-service/userprofile/settings", {}),
]


def _shape(data, depth: int = 0) -> str:
    """Compact structural summary of a JSON value (keys / list length), no values."""
    if isinstance(data, dict):
        keys = list(data.keys())
        return "{" + ", ".join(keys[:25]) + ("…" if len(keys) > 25 else "") + "}"
    if isinstance(data, list):
        inner = _shape(data[0], depth + 1) if data else ""
        return f"[{len(data)} x {inner}]"
    return type(data).__name__


def main() -> int:
    settings = get_settings()
    if not settings.has_api_key:
        print("No API key configured.", file=sys.stderr)
        return 2
    base = settings.garmin_api_base_url.rstrip("/")
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        tok = TokenManager(settings).get_token(client)
        headers = {"Authorization": f"{tok.token_type} {tok.token}"}
        for label, path, params in PROBES:
            try:
                r = client.get(base + path, params=params, headers=headers)
            except httpx.HTTPError as exc:
                print(f"{label:28s} ERR {type(exc).__name__}")
                continue
            line = f"{label:28s} {r.status_code}"
            if r.status_code == 200 and r.content:
                try:
                    line += "  " + _shape(r.json())
                except (ValueError, json.JSONDecodeError):
                    line += f"  <{len(r.content)} bytes non-json>"
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
