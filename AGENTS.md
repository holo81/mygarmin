# AGENTS.md

Self-hosted Garmin dashboard: FastAPI + SQLite backend (`backend/`), React/Vite/TS
frontend (`frontend/`). Human setup is in `README.md`; endpoint mappings in `docs/API.md`.

## Hard rules

- **Never run the app, a sync, or `load-fixtures` against the real config.** The real `.env`
  points at `data/mygarmin.db` (the owner's health data) and a live Garmin key. Starting
  `python -m app.server` runs a real sync at startup, then every 15 min. Always use the sandbox below.
- Never read, print, commit or edit `.env`, `*.key`, `data/`. Never call Garmin from tests (mock with `respx`).
- A Garmin HTTP 429 is expected under load. The client already backs off (`garmin/client.py`); do not add retry loops or lower the sync interval.
- Don't commit to `main`; use a branch and open a draft PR.

## Sandbox start (temp DB, mock data, no Garmin access)

```bash
cd backend && source .venv/bin/activate
export T=$(mktemp -d) APP_ENV=development PORT=8790 \
  DATABASE_PATH=$T/db.sqlite RAW_PAYLOAD_DIR=$T/raw FIT_FILE_DIR=$T/fit \
  GARMIN_PERSONAL_API_KEY= GARMIN_PERSONAL_API_KEY_FILE=   # blank = no auto-sync
python -m app.cli load-fixtures      # labelled MOCK data
python -m app.server                 # API on 127.0.0.1:8790
```

Env vars override `.env`. The UI proxies `/api` to `API_URL` (default `http://127.0.0.1:8787`, the owner's real
backend, which may be running): run `cd frontend && npm install && API_URL=http://127.0.0.1:8790 npm run dev`.

## Checks (run before every commit)

```bash
cd backend && python -m pytest -q && ruff check app tests
cd frontend && npm run lint && npm run check:scores
```

`ruff format` is not enforced yet; don't reformat files you aren't changing.

## Code map

| Concern | Where |
|---|---|
| Garmin HTTP client, token, FIT decode | `backend/app/garmin/` |
| Sync engine (per-day / per-range / snapshot / activities) | `backend/app/sync.py` |
| Raw JSON to rows | `backend/app/normalize.py` |
| SQLite schema and queries | `backend/app/db/schema.sql`, `repository.py` |
| API routes, auto-sync scheduler | `backend/app/api/app.py`, JSON shaping in `presenter.py` |
| Export (health snapshot / activity) | `backend/app/export.py` |
| Log setup | `backend/app/server.py` |
| Frontend pages / components / API types | `frontend/src/{pages,components,api}` |
| Training scores | `frontend/src/lib/scores.ts` (checked by `scores.check.ts`) |

## Adding a Garmin data category

1. Add `GARMIN_PATH_<NAME>` in `config.py` (+ `resource_paths()`) and `.env.example`.
2. Add the name to `PER_DAY` / `PER_RANGE` / `SNAPSHOT` in `sync.py` and handle it in the matching `_sync_*` method.
3. Normalize in `normalize.py`; add table in `schema.sql` and upsert/query in `repository.py`.
4. Expose via a view in `presenter.py` and a route in `api/app.py`; add the type in `frontend/src/api/types.ts`.
5. Add a fixture in `tests/fixtures_api.py` and tests (client, normalize, repository, sync, api).

Read endpoints serve from SQLite only; never call Garmin from a request handler.
Incremental sync starts at the oldest `sync_state` watermark of a category in `DEFAULT_CATEGORIES`.
Renaming or removing a category is safe now; stale `sync_state` rows are ignored.
