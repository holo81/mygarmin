"""Persistence tests: idempotent upserts, no duplicates, child-row replacement."""

from __future__ import annotations

from app import normalize as norm
from app.db.repository import Repository
from tests import fixtures_api as fx


def test_daily_upsert_is_idempotent(repo: Repository):
    row = norm.normalize_daily(fx.DAILY)
    repo.upsert_daily(row)
    repo.upsert_daily(row)  # second time must not duplicate
    repo.commit()
    rows = repo.daily_range("2026-02-01", "2026-02-28")
    assert len(rows) == 1
    assert rows[0]["steps"] == 12543


def test_daily_upsert_updates_changed_values(repo: Repository):
    row = norm.normalize_daily(fx.DAILY)
    repo.upsert_daily(row)
    repo.commit()
    updated = dict(row)
    updated["steps"] = 13000
    repo.upsert_daily(updated)
    repo.commit()
    rows = repo.daily_range("2026-02-01", "2026-02-28")
    assert len(rows) == 1
    assert rows[0]["steps"] == 13000
    # first_seen_at preserved, updated_at advanced
    assert rows[0]["first_seen_at"] is not None


def test_activity_upsert_idempotent(repo: Repository):
    row = norm.normalize_activity(fx.ACTIVITY)
    repo.upsert_activity(row)
    repo.upsert_activity(row)
    repo.commit()
    assert repo.count_activities() == 1
    got = repo.activity("x111-act-1")
    assert got is not None
    assert got["activity_type"] == "RUNNING"


def test_activity_samples_replace_not_append(repo: Repository):
    repo.upsert_activity(norm.normalize_activity(fx.ACTIVITY))
    samples = norm.normalize_activity_samples(fx.ACTIVITY_DETAILS)
    repo.replace_activity_samples("x111-act-1", samples)
    repo.replace_activity_samples("x111-act-1", samples)  # again
    repo.commit()
    stored = repo.activity_samples("x111-act-1")
    assert len(stored) == 2  # not 4
    # has_details flag set
    assert repo.activity("x111-act-1")["has_details"] == 1


def test_sleep_stage_replacement(repo: Repository):
    repo.upsert_sleep(norm.normalize_sleep(fx.SLEEP))
    stages = norm.normalize_sleep_stages(fx.SLEEP)
    repo.replace_sleep_stages("x111-sleep-1", stages)
    repo.replace_sleep_stages("x111-sleep-1", stages)
    repo.commit()
    rows = repo.conn.execute(
        "SELECT COUNT(*) AS c FROM sleep_stages WHERE sleep_summary_id = ?",
        ("x111-sleep-1",),
    ).fetchone()
    assert rows["c"] == 3


def test_body_battery_samples_round_trip(repo: Repository):
    repo.upsert_stress(norm.normalize_stress(fx.STRESS))
    bb = norm.normalize_body_battery_samples(fx.STRESS)
    repo.replace_body_battery_samples("2026-02-08", bb)
    repo.commit()
    rows = repo.body_battery_for_date("2026-02-08")
    assert [r["body_battery_value"] for r in rows] == [60, 58, 55]


def test_sync_state_tracks_progress(repo: Repository):
    repo.update_sync_state("dailies", 1675918800)
    repo.commit()
    st = repo.get_sync_state("dailies")
    assert st is not None
    assert st["last_synced_through"] == 1675918800
    assert st["last_success_at"] is not None
