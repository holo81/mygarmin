# Security model

This app handles your personal health data and a Garmin credential. The defaults
are conservative; read this before exposing it beyond your own machine.

## Credentials stay server-side

- The Garmin Personal API key is read only from the environment
  (`GARMIN_PERSONAL_API_KEY`), loaded via `.env`, which is git-ignored.
- The key and access tokens are **never** sent to the frontend, embedded in the
  built JS bundle, or written to logs. Token diagnostics are redacted
  (`AccessToken.redacted()` returns only type + seconds remaining).
- The access token is cached at `data/token_cache.json` with owner-only file
  permissions (`chmod 600`). It is git-ignored.
- All authenticated Garmin requests happen in the Python backend only.

## Network exposure

- The backend binds to `127.0.0.1` (localhost) by default. Nothing is reachable
  from your LAN unless you explicitly set `HOST=0.0.0.0`.
- Read endpoints (`/api/overview`, `/api/activities`, `/api/trends`, …) expose
  **your stored health data**. If you set `HOST=0.0.0.0`, anyone on your network
  can read them. Only do this on a trusted network, and prefer putting the app
  behind a reverse proxy that adds authentication (e.g. HTTP basic auth or an
  SSO proxy) and TLS.

## The sync (mutating) operation: optional token

- `POST /api/sync` is the only state-changing endpoint.
- `SYNC_API_TOKEN` is **optional**. If set, the endpoint requires a matching
  `Authorization: Bearer <token>` header (compared in constant time): 401 if
  missing, 403 if wrong.
- If unset (the default), anyone who can reach the API can trigger a sync. That
  is fine for the default localhost-only bind (`HOST=127.0.0.1`) but **set a
  token before binding to `0.0.0.0` or exposing the app** on a network.
- The UI never ships the token: you enter it in the browser and it is kept in
  `sessionStorage` for that tab only.
- Generate a strong token:
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

## Input handling & robustness

- All outbound requests use explicit connect/read/write timeouts.
- Transient failures (5xx, network, 429) retry with capped exponential backoff;
  permanent auth failures (401/403) are **not** retried.
- External responses are treated as untrusted: parsing is defensive, missing
  fields become `null` (never fabricated), and one failing category cannot
  corrupt others (per-category transactions).
- Date/range query parameters are validated and coerced server-side.

## No third-party analytics

- Health data is never sent to any analytics or telemetry service.
- The only third-party network calls from the UI are to OpenStreetMap tile
  servers, and only when rendering a GPS map for an activity that has location
  data. If you prefer zero external calls, remove the map layer or point it at a
  self-hosted tile server in `TrackMap.tsx`.

## Secrets & version control

- `.gitignore` excludes `.env`, `*.key`, `token_cache.json`, `data/`, and
  database files.
- `.env.example` contains **placeholders only**.
- Before committing, double-check `git status` does not include `.env` or any
  file under `data/`.

## Recommended hardening if LAN-exposed

1. Put the API + built frontend behind a reverse proxy (Caddy/nginx) with TLS.
2. Require authentication at the proxy for all routes.
3. Set a strong `SYNC_API_TOKEN` (not optional once the app is reachable by others).
4. Restrict the host firewall to the devices that need access.
