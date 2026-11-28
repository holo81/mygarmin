# Operations guide

Startup, shutdown, updates, backups, restore, and scheduled sync for a
self-hosted deployment (e.g. a home Raspberry Pi or a laptop).

## Processes

There are two independent processes. You can run either or both.

| Process | Command | Purpose |
| --- | --- | --- |
| Web server | `python -m app.server` | Serves the API (and, in production, the built UI if you wire it up) |
| Scheduler | `python -m app.scheduler --interval-hours 6` | Periodic incremental sync |

The CLI (`python -m app.cli …`) covers one-off tasks: `init-db`, `verify-auth`,
`sync`, `enrich`, `status`, `load-fixtures`.

## Startup

```bash
cd backend
source .venv/bin/activate
python -m app.cli init-db          # first run only (idempotent afterwards)
python -m app.cli verify-auth      # sanity-check the key
python -m app.server               # starts on HOST:PORT from .env
```

Build and serve the UI (production):

```bash
cd frontend && npm install && npm run build   # -> frontend/dist
```

Serve `frontend/dist` behind the same reverse proxy as `/api`, or with any
static file server. In development, `npm run dev` proxies `/api` to the backend
automatically.

## Shutdown

- Web server / scheduler started in a shell: `Ctrl-C` (both handle SIGINT/SIGTERM
  cleanly; the scheduler stops without starting a new job).
- Under systemd: `systemctl --user stop mygarmin-web mygarmin-sync`.
- SQLite in WAL mode flushes on clean shutdown; abrupt kills are still safe
  (WAL recovery), but prefer a clean stop before backups.

## Scheduled sync

### Built-in auto-sync (default)

`python -m app.server` runs its own background sync every `AUTO_SYNC_MINUTES`
minutes (default `60`; `0` disables it). Garmin returns HTTP 429 under load, so
do not lower this much. `python -m app.scheduler` (Option A) is a **separate**
process and should NOT be run together with the server's auto-sync: set
`AUTO_SYNC_MINUTES=0` if you use it or cron. As a safety net every sync takes a
non-blocking lock file (`<database>.sync.lock`, next to the DB), so overlapping
syncs are skipped rather than run twice, but running both is still pointless.

### Option A — built-in scheduler

```bash
python -m app.scheduler --interval-hours 6 --run-now
```

Example systemd user service (`~/.config/systemd/user/mygarmin-sync.service`):

```ini
[Unit]
Description=mygarmin scheduled sync

[Service]
WorkingDirectory=%h/dev/mygarmin/backend
ExecStart=%h/dev/mygarmin/backend/.venv/bin/python -m app.scheduler --interval-hours 6
Restart=on-failure
EnvironmentFile=%h/dev/mygarmin/.env

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now mygarmin-sync.service
```

### Option B — cron + CLI

```cron
# every 6 hours, incremental sync
0 */6 * * * cd /home/pi/mygarmin/backend && .venv/bin/python -m app.cli sync >> /home/pi/mygarmin/data/sync.log 2>&1
```

Both options run an **incremental** sync (resumes from the last successful point,
with a one-day overlap). They never duplicate records.

## API key expiry & recovery

Keys expire after 30/90/180 days or 1 year; Garmin emails you ~1 week before.

When a key expires (or you rotate it):

1. In Garmin Connect, delete the old key and **Create Key** again.
2. Copy the new key (shown once).
3. Update `GARMIN_PERSONAL_API_KEY` in `.env`.
4. Remove the stale cached token: `rm backend/data/token_cache.json`
   (or just run any sync — an expired token auto-refreshes).
5. `python -m app.cli verify-auth` to confirm.

Symptoms of an expired/invalid key: `verify-auth` and syncs fail with a
`GarminAuthError` ("key may be invalid, expired, or revoked"). The dashboard
keeps showing previously-stored data and surfaces a "sync failed" banner — it
does not break.

## Backup

Everything lives under `data/` (path from `DATABASE_PATH` / `RAW_PAYLOAD_DIR` /
`FIT_FILE_DIR`):

- `mygarmin.db` (+ `-wal`, `-shm`) — the database
- `raw_payloads/` — archived raw API responses
- `fit_files/` — downloaded `.FIT` files

**Consistent DB backup** (safe while running, thanks to SQLite's backup API):

```bash
cd backend && source .venv/bin/activate
python -c "import sqlite3,sys; src=sqlite3.connect('data/mygarmin.db'); dst=sqlite3.connect('data/backup-mygarmin.db'); src.backup(dst); dst.close(); src.close(); print('backup ok')"
```

Then archive the whole `data/` directory:

```bash
tar czf mygarmin-backup-$(date +%F).tgz data/
```

## Restore

```bash
# stop the web server / scheduler first
tar xzf mygarmin-backup-YYYY-MM-DD.tgz        # restores data/
# (or copy a single backup DB back into place)
cp data/backup-mygarmin.db data/mygarmin.db
python -m app.cli status                       # verify
```

Because sync upserts are idempotent and keyed on Garmin's stable identifiers, you
can also simply re-run `sync --initial` after a restore to top up any gap without
creating duplicates.

## Updates

```bash
git pull
cd backend && source .venv/bin/activate && uv pip install -e ".[dev]"
python -m app.cli init-db     # applies additive schema changes safely
cd ../frontend && npm install && npm run build
```

The schema uses `CREATE TABLE IF NOT EXISTS` with a `schema_migrations` version
marker; ordinary updates never drop historical data.

## Monitoring sync health

- CLI: `python -m app.cli status` (last run + per-category state).
- API: `GET /api/sync/status` returns recent runs with per-category results.
- UI: the sidebar/banners show last-sync time, stale-data warnings, and failures.
