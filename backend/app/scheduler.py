"""Optional scheduled sync for self-hosted deployments.

Runs an incremental sync on a fixed interval using APScheduler. Intended to be
launched as a long-lived process (e.g. a systemd service on a Raspberry Pi)
separate from the web server, OR disabled entirely if you prefer cron + the CLI.

Usage:
    python -m app.scheduler --interval-hours 6
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys

from apscheduler.schedulers.blocking import BlockingScheduler

from .config import get_settings
from .db.database import init_db
from .sync import SyncEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("mygarmin.scheduler")


def _run_once() -> None:
    settings = get_settings()
    if not settings.has_api_key:
        logger.error("No API key configured; skipping scheduled sync.")
        return
    engine = SyncEngine(settings)
    try:
        outcome = engine.incremental(trigger="scheduled")
        logger.info("Scheduled sync finished: %s (%s)", outcome.status, outcome.message)
    except Exception:
        logger.exception("Scheduled sync raised")
    finally:
        engine.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="mygarmin scheduled sync")
    parser.add_argument(
        "--interval-hours", type=float, default=6.0, help="Hours between syncs"
    )
    parser.add_argument(
        "--run-now", action="store_true", help="Run one sync immediately on startup"
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    settings.ensure_dirs()
    init_db(settings.database_file)

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        _run_once,
        "interval",
        hours=args.interval_hours,
        id="incremental-sync",
        max_instances=1,
        coalesce=True,
    )
    logger.info("Scheduled incremental sync every %.1f h", args.interval_hours)

    if args.run_now:
        _run_once()

    def _stop(*_: object) -> None:
        logger.info("Shutting down scheduler")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    scheduler.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
