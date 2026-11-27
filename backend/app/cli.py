"""Command-line interface for mygarmin.

Examples:
    python -m app.cli init-db
    python -m app.cli verify-auth
    python -m app.cli sync --days 7
    python -m app.cli sync --initial
    python -m app.cli enrich --days 7
    python -m app.cli status
    python -m app.cli load-fixtures        # development only
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from .config import get_settings
from .db.database import init_db
from .garmin.client import GarminClient
from .garmin.errors import GarminError
from .sync import SyncEngine

_DAY = 86400


def _cmd_init_db(args: argparse.Namespace) -> int:
    settings = get_settings()
    settings.ensure_dirs()
    init_db(settings.database_file)
    print(f"Initialized database at {settings.database_file}")
    return 0


def _cmd_verify_auth(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.has_api_key:
        print("ERROR: GARMIN_PERSONAL_API_KEY is not set. See .env.example.", file=sys.stderr)
        return 2
    try:
        with GarminClient(settings) as client:
            info = client.verify_auth()
        print("Authentication OK. Token (redacted):")
        print(json.dumps(info, indent=2))
        return 0
    except GarminError as exc:
        print(f"Authentication failed: {exc}", file=sys.stderr)
        return 1


def _cmd_sync(args: argparse.Namespace) -> int:
    settings = get_settings()
    settings.ensure_dirs()
    init_db(settings.database_file)
    engine = SyncEngine(settings)
    try:
        now = int(time.time())
        if args.initial:
            start = now - settings.initial_import_days * _DAY
            trigger = "initial"
        elif args.days:
            start = now - args.days * _DAY
            trigger = "cli"
        else:
            # default: incremental
            outcome = engine.incremental(trigger="cli")
            print(json.dumps(outcome.to_dict(), indent=2))
            return 0 if outcome.status in ("success", "partial") else 1
        cats = args.categories.split(",") if args.categories else None
        outcome = engine.run(start_time=start, end_time=now, categories=cats, trigger=trigger)
        print(json.dumps(outcome.to_dict(), indent=2))
        return 0 if outcome.status in ("success", "partial") else 1
    finally:
        engine.close()


def _cmd_enrich(args: argparse.Namespace) -> int:
    settings = get_settings()
    init_db(settings.database_file)
    engine = SyncEngine(settings)
    try:
        now = int(time.time())
        start = now - (args.days or settings.initial_import_days) * _DAY
        result = engine.enrich_activity_details(start_time=start, end_time=now)
        print(json.dumps(result, indent=2))
        return 0
    finally:
        engine.close()


def _cmd_status(args: argparse.Namespace) -> int:
    from .db.database import connect
    from .db.repository import Repository

    settings = get_settings()
    init_db(settings.database_file)
    conn = connect(settings.database_file)
    repo = Repository(conn)
    try:
        last = repo.last_sync_run()
        state = repo.all_sync_state()
        out = {
            "database": str(settings.database_file),
            "app_env": settings.app_env,
            "last_sync_run": dict(last) if last else None,
            "sync_state": [dict(s) for s in state],
            "activity_count": repo.count_activities(),
        }
        print(json.dumps(out, indent=2, default=str))
        return 0
    finally:
        conn.close()


def _cmd_load_fixtures(args: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.is_production:
        print(
            "Refusing to load mock fixtures in production (APP_ENV=production).",
            file=sys.stderr,
        )
        return 2
    from .fixtures import load_mock_fixtures

    init_db(settings.database_file)
    n = load_mock_fixtures(settings)
    print(f"Loaded mock fixtures ({n} records). THIS IS MOCK DATA (development only).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mygarmin", description="Personal Garmin dashboard CLI")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Create the SQLite schema").set_defaults(func=_cmd_init_db)
    sub.add_parser("verify-auth", help="Verify Garmin Personal API auth").set_defaults(
        func=_cmd_verify_auth
    )

    sp = sub.add_parser("sync", help="Synchronize data from Garmin")
    sp.add_argument("--days", type=int, default=0, help="Sync the last N days")
    sp.add_argument("--initial", action="store_true", help="Initial historical import")
    sp.add_argument("--categories", type=str, default="", help="Comma list of categories")
    sp.set_defaults(func=_cmd_sync)

    ep = sub.add_parser("enrich", help="Fetch activity details + FIT time-series")
    ep.add_argument("--days", type=int, default=0, help="Enrich activities from last N days")
    ep.set_defaults(func=_cmd_enrich)

    sub.add_parser("status", help="Show sync status").set_defaults(func=_cmd_status)
    sub.add_parser(
        "load-fixtures", help="Load labelled mock data (development only)"
    ).set_defaults(func=_cmd_load_fixtures)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
