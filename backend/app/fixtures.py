"""Development-only mock data loader (schema-aligned with the real API).

Produces clearly-labelled MOCK data for local UI development without real
credentials. Refused when APP_ENV=production. The API reports dataSource=mock so
the frontend shows a prominent banner; production never shows these values.
"""

from __future__ import annotations

import math
import random
import time
from datetime import UTC, datetime, timedelta

from .config import Settings
from .db.database import connect
from .db.repository import Repository

_DAY = 86400


def _dates(days: int):
    today = datetime.now(UTC).date()
    for i in range(days):
        d = today - timedelta(days=i)
        start = int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp())
        yield d.isoformat(), start


def load_mock_fixtures(settings: Settings, days: int = 45) -> int:
    rng = random.Random(42)
    conn = connect(settings.database_file)
    repo = Repository(conn)
    count = 0
    offset = 10800  # +3h approx Europe/Helsinki
    try:
        run_id = repo.start_sync_run("mock", int(time.time()) - days * _DAY, int(time.time()))
        for idx, (cal, start) in enumerate(_dates(days)):
            steps = max(0, 6000 + int(3000 * math.sin(idx / 4)) + rng.randint(-800, 800))
            rhr = 50 + int(4 * math.sin(idx / 7)) + rng.randint(-2, 2)
            repo.upsert_daily(
                {
                    "summary_id": f"daily-{cal}",
                    "calendar_date": cal,
                    "start_time_seconds": start,
                    "start_time_offset_seconds": offset,
                    "duration_seconds": 86400,
                    "steps": steps,
                    "steps_goal": 9000,
                    "distance_meters": steps * 0.78,
                    "floors_climbed": rng.randint(2, 18),
                    "floors_climbed_goal": 10,
                    "active_kilocalories": 300 + rng.randint(0, 500),
                    "bmr_kilocalories": 1600,
                    "total_kilocalories": 1900 + rng.randint(0, 600),
                    "active_time_seconds": rng.randint(1800, 7200),
                    "sleeping_seconds": rng.randint(20000, 30000),
                    "moderate_intensity_seconds": rng.randint(0, 2400),
                    "vigorous_intensity_seconds": rng.randint(0, 1800),
                    "intensity_goal_seconds": 9000,
                    "min_hr_bpm": rhr - 4,
                    "max_hr_bpm": 140 + rng.randint(0, 40),
                    "average_hr_bpm": 68 + rng.randint(-4, 6),
                    "resting_hr_bpm": rhr,
                    "resting_hr_7d_avg": rhr + 2,
                    "avg_stress_level": 30 + rng.randint(-10, 25),
                    "max_stress_level": 70 + rng.randint(0, 25),
                    "stress_duration_seconds": rng.randint(3600, 20000),
                    "rest_stress_duration_seconds": rng.randint(3600, 20000),
                    "activity_stress_duration_seconds": rng.randint(1800, 10000),
                    "low_stress_duration_seconds": rng.randint(1800, 9000),
                    "medium_stress_duration_seconds": rng.randint(600, 6000),
                    "high_stress_duration_seconds": rng.randint(0, 2400),
                    "stress_qualifier": rng.choice(["CALM", "BALANCED", "STRESSFUL"]),
                    "body_battery_charged": rng.randint(40, 90),
                    "body_battery_drained": rng.randint(40, 90),
                    "body_battery_high": rng.randint(70, 100),
                    "body_battery_low": rng.randint(5, 30),
                    "body_battery_most_recent": rng.randint(20, 80),
                    "avg_spo2": round(95 + rng.uniform(-2, 2), 1),
                    "lowest_spo2": rng.randint(85, 92),
                    "avg_waking_respiration": round(14 + rng.uniform(-1, 2), 1),
                    "highest_respiration": round(20 + rng.uniform(0, 4), 1),
                    "lowest_respiration": round(8 + rng.uniform(-2, 2), 1),
                }
            )
            count += 1

            total = rng.randint(6 * 3600, 8 * 3600)
            deep = int(total * rng.uniform(0.12, 0.2))
            rem = int(total * rng.uniform(0.18, 0.25))
            repo.upsert_sleep(
                {
                    "summary_id": f"sleep-{cal}",
                    "calendar_date": cal,
                    "start_time_seconds": start - 6 * 3600,
                    "start_time_offset_seconds": offset,
                    "duration_seconds": total,
                    "unmeasurable_seconds": 0,
                    "deep_seconds": deep,
                    "light_seconds": total - deep - rem,
                    "rem_seconds": rem,
                    "awake_seconds": rng.randint(300, 2400),
                    "total_nap_seconds": 0,
                    "overall_score_value": 65 + rng.randint(0, 30),
                    "overall_score_qualifier": rng.choice(["FAIR", "GOOD", "EXCELLENT"]),
                    "avg_sleep_respiration": round(13 + rng.uniform(-1, 2), 1),
                    "avg_sleep_spo2": round(95 + rng.uniform(-2, 2), 1),
                    "lowest_spo2": rng.randint(85, 92),
                    "avg_sleep_stress": round(15 + rng.uniform(-5, 10), 1),
                    "avg_sleep_hr": round(52 + rng.uniform(-4, 6), 1),
                    "awake_count": rng.randint(0, 3),
                    "validation": "enhanced_confirmed_final",
                }
            )
            count += 1

            base = 42 + int(6 * math.sin(idx / 9))
            repo.upsert_hrv(
                {
                    "summary_id": f"hrv-{cal}",
                    "calendar_date": cal,
                    "start_time_seconds": start - 6 * 3600,
                    "start_time_offset_seconds": offset,
                    "duration_seconds": total,
                    "last_night_avg_ms": base + rng.randint(-6, 6),
                    "last_night_5min_high_ms": base + rng.randint(10, 25),
                    "weekly_avg_ms": base,
                    "baseline_low_ms": base - 8,
                    "baseline_high_ms": base + 10,
                    "status": rng.choice(["BALANCED", "BALANCED", "UNBALANCED", "LOW"]),
                }
            )
            count += 1

            bb = []
            level = rng.randint(30, 60)
            for h in range(24):
                level += (4 if h < 7 else -2) + rng.randint(-3, 3)
                level = max(5, min(100, level))
                bb.append({"calendar_date": cal, "offset_seconds": h * 3600, "body_battery_value": level})
            repo.replace_body_battery_samples(cal, bb)
            count += 1

        types = ["running", "cycling", "walking", "lap_swimming", "strength_training"]
        for i in range(12):
            start = int(time.time()) - i * 2 * _DAY - rng.randint(0, _DAY)
            atype = types[i % len(types)]
            dur = rng.randint(1200, 5400)
            dist = dur * rng.uniform(2.2, 4.5) if atype != "strength_training" else None
            sid = f"mock-activity-{i}"
            repo.upsert_activity(
                {
                    "summary_id": sid,
                    "activity_id": str(100000 + i),
                    "activity_type": atype,
                    "activity_name": f"{atype.replace('_', ' ').title()} session",
                    "start_time_seconds": start,
                    "start_time_offset_seconds": offset,
                    "duration_seconds": dur,
                    "distance_meters": dist,
                    "active_kilocalories": rng.randint(150, 900),
                    "avg_hr_bpm": rng.randint(120, 160),
                    "max_hr_bpm": rng.randint(160, 185),
                    "avg_speed_mps": (dist / dur) if dist else None,
                    "max_speed_mps": (dist / dur * 1.4) if dist else None,
                    "avg_pace_min_per_km": (dur / 60) / (dist / 1000) if dist else None,
                    "avg_run_cadence_spm": rng.randint(150, 180) if atype == "running" else None,
                    "max_run_cadence_spm": rng.randint(180, 195) if atype == "running" else None,
                    "avg_bike_cadence_rpm": rng.randint(70, 95) if atype == "cycling" else None,
                    "avg_swim_cadence_spm": None,
                    "total_elevation_gain_m": rng.randint(0, 300) if dist else None,
                    "total_elevation_loss_m": rng.randint(0, 300) if dist else None,
                    "starting_latitude": 60.17 + rng.uniform(-0.05, 0.05) if dist else None,
                    "starting_longitude": 24.94 + rng.uniform(-0.05, 0.05) if dist else None,
                    "steps": rng.randint(3000, 9000) if atype in ("running", "walking") else None,
                    "device_name": "Mock Forerunner",
                    "is_parent": 0,
                    "parent_summary_id": None,
                    "manual": 0,
                }
            )
            if dist:
                samples = []
                lat, lon = 60.17, 24.94
                for s in range(0, dur, 10):
                    frac = s / dur
                    lat += rng.uniform(-0.0003, 0.0004)
                    lon += rng.uniform(-0.0003, 0.0004)
                    samples.append(
                        {
                            "sample_index": s // 10,
                            "offset_seconds": s,
                            "clock_time_seconds": start + s,
                            "latitude": lat,
                            "longitude": lon,
                            "elevation_meters": 20 + 15 * math.sin(frac * 6) + rng.uniform(-2, 2),
                            "heart_rate_bpm": int(120 + 30 * frac + rng.randint(-5, 5)),
                            "speed_mps": (dist / dur) * (0.8 + 0.4 * rng.random()),
                            "cadence": rng.randint(150, 180) if atype == "running" else rng.randint(70, 95),
                            "power_watts": rng.randint(150, 320) if atype == "cycling" else None,
                            "distance_meters": dist * frac,
                            "temperature_celsius": round(12 + rng.uniform(-2, 3), 1),
                            "source": "fit",
                        }
                    )
                repo.replace_activity_samples(sid, samples)
            count += 1

        for c in ("daily", "sleep", "hrv", "body_battery", "activities", "daily_heart_rate"):
            repo.update_sync_state(c, int(time.time()))
        repo.finish_sync_run(run_id, "success", count, "MOCK DATA (development fixtures)")
        repo.commit()
        return count
    finally:
        conn.close()
