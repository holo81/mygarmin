# mygarmin — personal Garmin Connect dashboard

A polished, self-hosted, single-user dashboard for your own Garmin data, built
on the **official Garmin Connect Personal API**. It syncs your activity and
health data into a local SQLite database and presents it with a clean web UI:
an overview, searchable activity history, detailed per-activity views (charts +
GPS map), and historical health trends.

> This is a personal project for your own data. It is **not** affiliated with or
> endorsed by Garmin, and it does not reproduce Garmin Connect's branding.

---

## Highlights

- **Official Personal API only.** API-key → access-token flow, server-side
  credentials, no scraping, no session-cookie workarounds.
- **Pull-based sync** into SQLite with idempotent upserts (no duplicates),
  raw-payload archival, sync history, and partial-failure safety.
- **Real data, honestly presented.** Missing data is shown as "No data", never
  as zero; mock fixtures are clearly labelled and blocked in production.
- **Dashboard**: Overview, Activity history, Activity detail (HR / pace /
  elevation / power / cadence charts, GPS map, FIT time-series), Health trends.
- **Dark + light themes**, desktop-first and responsive, Finnish local-time
  rendering by default.
- **Self-hosting friendly**: localhost-bound by default, optional scheduled sync,
  runs comfortably on a Raspberry Pi.

## Architecture

```
┌──────────────┐    pull     ┌──────────────┐   normalize   ┌──────────┐
│ Garmin       │  (HTTPS)    │ sync engine   │  + upsert     │ SQLite   │
│ Personal API │ ──────────▶ │ (Python)      │ ────────────▶ │ (local)  │
└──────────────┘             └──────────────┘               └────┬─────┘
                                                                  │ read-only
                                                             ┌────▼─────┐
                                                  serves     │ FastAPI  │
                                             ◀────────────── │ backend  │
                                                             └────┬─────┘
                                                                  │ /api JSON
                                                             ┌────▼─────┐
                                                             │ React UI │
                                                             └──────────┘
```

Separation of concerns: **acquisition** (`garmin/`), **persistence** (`db/`),
**processing** (`normalize.py`, `sync.py`), **presentation** (`api/`, frontend).
Read endpoints serve only from SQLite, so the dashboard stays usable even when
Garmin is unreachable.

- Backend: Python 3.11+, FastAPI, httpx, SQLite (WAL), official `garmin-fit-sdk`.
- Frontend: React + Vite + TypeScript, Recharts, MapLibre GL (free OSM tiles).

See [`docs/API.md`](docs/API.md) for the verified Garmin endpoints and field
mappings, [`docs/SECURITY.md`](docs/SECURITY.md) for the security model, and
[`docs/OPERATIONS.md`](docs/OPERATIONS.md) for run/backup/restore/scheduled-sync.

---

## Prerequisites

- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/) (or plain `venv` + `pip`).
- Node.js 18+ and npm.
- A Garmin Connect account and a **Personal API key** (see below).

## 1. Get your Personal API key

1. Log in to the Garmin Connect website and open the **Personal API Key** page
   (Account settings → Personal API Key).
2. **Create Key**, accept the terms, choose an expiration (30 / 90 / 180 days or
   1 year), and **Create**.
3. **Copy the key immediately** — it is shown only once. Treat it like a password.
4. If you lose it or it expires, delete it and create a new one, then update
   your `.env` (see [expiry recovery](docs/OPERATIONS.md#api-key-expiry--recovery)).

## 2. Configure

```bash
cp .env.example .env
# Edit .env and set at least:
#   GARMIN_PERSONAL_API_KEY=...        your key
#   SYNC_API_TOKEN=...                 optional; leave blank for localhost-only use
#   APP_ENV=production
```

`SYNC_API_TOKEN` is optional. With the default localhost-only bind you can leave it
blank. Set it if the app is reachable by others (see `docs/SECURITY.md`). To generate one:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

The `.env` file is git-ignored. No secret is ever sent to the frontend or logged.

## 3. Install & initialise the backend

```bash
cd backend
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"      # or: pip install -e ".[dev]"
python -m app.cli init-db
python -m app.cli verify-auth   # confirms your key works (prints a redacted token)
```

## 4. First sync (historical import)

```bash
python -m app.cli sync --initial      # imports INITIAL_IMPORT_DAYS of history
python -m app.cli enrich --days 30     # fetch activity details + FIT time-series
python -m app.cli status               # show sync state
```

## 5. Run the dashboard

**Backend** (serves the API on `127.0.0.1:8787` by default):

```bash
cd backend && source .venv/bin/activate
python -m app.server
```

**Frontend** (dev server with hot reload, proxies `/api` to the backend):

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

For a production build of the UI:

```bash
cd frontend && npm run build   # outputs frontend/dist
```

You can serve `frontend/dist` with any static server, or put it behind the same
reverse proxy as the API. See [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

## 6. Keep it in sync

Trigger a sync anytime from the UI ("Sync now", asks for the sync token only if you set one) or:

```bash
python -m app.cli sync           # incremental since last successful sync
```

The web server already syncs in the background every `AUTO_SYNC_MINUTES` minutes
(default 60, `0` disables it), so no extra scheduler is needed. Only if you set
`AUTO_SYNC_MINUTES=0` and want the server-less alternative:

```bash
python -m app.scheduler --interval-hours 6 --run-now
```

(or use cron + `python -m app.cli sync` — see
[`docs/OPERATIONS.md`](docs/OPERATIONS.md#scheduled-sync)).

---

## Development mode & mock data

For UI work without real credentials. **`load-fixtures` writes to `DATABASE_PATH`, so
point it at a throwaway DB** (see `AGENTS.md`), or it will put mock rows in your real database:

```bash
cd backend && source .venv/bin/activate
APP_ENV=development python -m app.cli load-fixtures   # labelled MOCK data
APP_ENV=development python -m app.server
```

The UI shows a prominent **"Mock data"** banner. `load-fixtures` refuses to run
when `APP_ENV=production`, and the API reports `dataSource: mock` so production
never silently displays fabricated values.

## Tests

```bash
cd backend && source .venv/bin/activate
python -m pytest -q
```

Tests use recorded-style fixtures and mocked HTTP (`respx`) — **no real Garmin
credentials are required**. They cover the API client, token lifecycle,
normalization, persistence/idempotency, sync (including partial failure and auth
failure), and FIT handling.

## Data categories & availability

The Personal API is **pull-only** and exposes Activity data (JSON & `.FIT`),
Health data (JSON), and Women's health data (JSON). Exactly which metrics are
present depends on your devices and whether you wore them. The dashboard only
renders a metric when its value is actually available. See
[`docs/API.md`](docs/API.md) for the full verified field inventory and the
documented-vs-derived breakdown.

## Troubleshooting

- **`verify-auth` fails with an auth error** — your key is invalid, expired, or
  revoked. Create a new key and update `.env`.
- **A category 404s during sync** — the configured resource path may not match
  your account's live Personal API. Adjust `GARMIN_PATH_*` in `.env` to match
  the Personal API Swagger; raw payloads and other categories are unaffected.
- **A metric shows "No data"** — that metric wasn't recorded for that day/device.
  This is intentional: missing data is never shown as zero.
