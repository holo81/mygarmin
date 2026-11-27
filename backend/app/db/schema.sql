-- ===========================================================================
-- mygarmin SQLite schema (v1)
--
-- Conventions:
--   * All instants are stored as Unix epoch SECONDS in UTC (integer), exactly as
--     Garmin returns them. A separate *_offset_seconds column stores the device
--     local-time offset so the UI can reconstruct the user's local time. We never
--     silently convert to local time in storage.
--   * Source values are preserved in their original units (meters, seconds, m/s,
--     bpm, etc.). Presentation-layer unit conversion happens in the frontend/API,
--     never by mutating stored values.
--   * NULL means "no data". Zero means "measured zero". These are never conflated.
--   * Idempotency: natural keys use Garmin's stable identifiers (summaryId /
--     activityId). Repeated syncs UPSERT on these keys.
--   * Raw payloads are archived on disk; `raw_payloads` records a pointer + hash.
-- ===========================================================================

PRAGMA foreign_keys = ON;

-- --- schema versioning -----------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_migrations (
    version      INTEGER PRIMARY KEY,
    applied_at   TEXT NOT NULL   -- ISO-8601 UTC
);

-- --- raw payload archive pointers ------------------------------------------
-- The actual bytes live on disk under RAW_PAYLOAD_DIR; this table indexes them
-- so a record can always be traced back to the exact API response that produced
-- it (recoverable raw representation).
CREATE TABLE IF NOT EXISTS raw_payloads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    category      TEXT NOT NULL,          -- dailies | sleeps | stress | hrv | activities | ...
    start_time    INTEGER,               -- window start (epoch s, UTC)
    end_time      INTEGER,               -- window end (epoch s, UTC)
    fetched_at    TEXT NOT NULL,         -- ISO-8601 UTC
    file_path     TEXT NOT NULL,         -- path under RAW_PAYLOAD_DIR
    sha256        TEXT NOT NULL,         -- content hash (dedupe / integrity)
    byte_size     INTEGER NOT NULL,
    sync_run_id   INTEGER REFERENCES sync_runs(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_category_time ON raw_payloads(category, start_time);

-- --- activities (summaries) ------------------------------------------------
CREATE TABLE IF NOT EXISTS activities (
    summary_id              TEXT PRIMARY KEY,   -- Garmin summaryId (stable)
    activity_id             TEXT,               -- Garmin Connect activityId
    activity_type           TEXT,
    activity_name           TEXT,
    start_time_seconds      INTEGER NOT NULL,   -- UTC epoch s
    start_time_offset_seconds INTEGER,          -- + offset => device local time
    duration_seconds        INTEGER,
    distance_meters         REAL,
    active_kilocalories     INTEGER,
    avg_hr_bpm              INTEGER,
    max_hr_bpm              INTEGER,
    avg_speed_mps           REAL,
    max_speed_mps           REAL,
    avg_pace_min_per_km     REAL,
    avg_run_cadence_spm     REAL,
    max_run_cadence_spm     REAL,
    avg_bike_cadence_rpm    REAL,
    avg_swim_cadence_spm    REAL,
    total_elevation_gain_m  REAL,
    total_elevation_loss_m  REAL,
    starting_latitude       REAL,
    starting_longitude      REAL,
    steps                   INTEGER,
    device_name             TEXT,
    is_parent               INTEGER,            -- 0/1/NULL
    parent_summary_id       TEXT,
    manual                  INTEGER,            -- 0/1/NULL
    -- activity detail / FIT linkage
    has_details             INTEGER DEFAULT 0,  -- 1 if sample time-series stored
    has_fit                 INTEGER DEFAULT 0,  -- 1 if a .FIT file was downloaded
    fit_file_path           TEXT,
    -- bookkeeping
    raw_payload_id          INTEGER REFERENCES raw_payloads(id) ON DELETE SET NULL,
    first_seen_at           TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activities_start ON activities(start_time_seconds DESC);
CREATE INDEX IF NOT EXISTS idx_activities_type ON activities(activity_type);

-- --- activity time-series samples ------------------------------------------
-- One row per recorded sample for an activity (from activityDetails or a FIT
-- file). Sparse by design: any metric may be NULL for a given sample.
CREATE TABLE IF NOT EXISTS activity_samples (
    activity_summary_id     TEXT NOT NULL REFERENCES activities(summary_id) ON DELETE CASCADE,
    sample_index            INTEGER NOT NULL,   -- ordinal within the activity
    offset_seconds          INTEGER,            -- seconds from activity start
    clock_time_seconds      INTEGER,            -- absolute UTC epoch s if known
    latitude                REAL,
    longitude               REAL,
    elevation_meters        REAL,
    heart_rate_bpm          INTEGER,
    speed_mps               REAL,
    cadence                 REAL,               -- steps/min or rpm per activity type
    power_watts             REAL,
    distance_meters         REAL,
    temperature_celsius     REAL,
    source                  TEXT,               -- 'activityDetails' | 'fit'
    PRIMARY KEY (activity_summary_id, sample_index)
);

-- --- daily health summaries -------------------------------------------------
CREATE TABLE IF NOT EXISTS daily_summaries (
    summary_id                  TEXT PRIMARY KEY,
    calendar_date               TEXT NOT NULL,   -- yyyy-mm-dd (as Garmin reports)
    start_time_seconds          INTEGER,
    start_time_offset_seconds   INTEGER,
    duration_seconds            INTEGER,
    steps                       INTEGER,
    steps_goal                  INTEGER,
    distance_meters             REAL,
    floors_climbed              INTEGER,
    floors_climbed_goal         INTEGER,
    active_kilocalories         INTEGER,
    bmr_kilocalories            INTEGER,
    active_time_seconds         INTEGER,
    moderate_intensity_seconds  INTEGER,
    vigorous_intensity_seconds  INTEGER,
    intensity_goal_seconds      INTEGER,
    min_hr_bpm                  INTEGER,
    max_hr_bpm                  INTEGER,
    average_hr_bpm              INTEGER,          -- 7-day avg per Garmin docs
    resting_hr_bpm              INTEGER,
    avg_stress_level            INTEGER,          -- -1/-2 sentinels preserved as-is
    max_stress_level            INTEGER,
    stress_duration_seconds     INTEGER,
    rest_stress_duration_seconds INTEGER,
    activity_stress_duration_seconds INTEGER,
    low_stress_duration_seconds INTEGER,
    medium_stress_duration_seconds INTEGER,
    high_stress_duration_seconds INTEGER,
    stress_qualifier            TEXT,
    raw_payload_id              INTEGER REFERENCES raw_payloads(id) ON DELETE SET NULL,
    first_seen_at               TEXT NOT NULL,
    updated_at                  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_calendar ON daily_summaries(calendar_date);

-- Per-day heart-rate samples (from timeOffsetHeartRateSamples).
CREATE TABLE IF NOT EXISTS daily_hr_samples (
    calendar_date   TEXT NOT NULL,
    offset_seconds  INTEGER NOT NULL,
    heart_rate_bpm  INTEGER NOT NULL,
    PRIMARY KEY (calendar_date, offset_seconds)
);

-- --- sleep summaries --------------------------------------------------------
CREATE TABLE IF NOT EXISTS sleep_summaries (
    summary_id                  TEXT PRIMARY KEY,
    calendar_date               TEXT NOT NULL,
    start_time_seconds          INTEGER,
    start_time_offset_seconds   INTEGER,
    duration_seconds            INTEGER,          -- measured sleep (excl awake/unmeasurable)
    unmeasurable_seconds        INTEGER,
    deep_seconds                INTEGER,
    light_seconds               INTEGER,
    rem_seconds                 INTEGER,
    awake_seconds               INTEGER,
    total_nap_seconds           INTEGER,
    overall_score_value         INTEGER,
    overall_score_qualifier     TEXT,
    avg_sleep_respiration       REAL,             -- derived mean of respiration samples (documented)
    avg_sleep_spo2              REAL,             -- derived mean of spo2 samples (documented)
    validation                  TEXT,
    raw_payload_id              INTEGER REFERENCES raw_payloads(id) ON DELETE SET NULL,
    first_seen_at               TEXT NOT NULL,
    updated_at                  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sleep_calendar ON sleep_summaries(calendar_date);

-- Sleep stage intervals (from sleepLevelsMap).
CREATE TABLE IF NOT EXISTS sleep_stages (
    sleep_summary_id    TEXT NOT NULL REFERENCES sleep_summaries(summary_id) ON DELETE CASCADE,
    stage               TEXT NOT NULL,       -- deep | light | rem | awake
    start_time_seconds  INTEGER NOT NULL,
    end_time_seconds    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sleep_stages_summary ON sleep_stages(sleep_summary_id);

-- --- stress detail + body battery time series ------------------------------
CREATE TABLE IF NOT EXISTS stress_summaries (
    summary_id                  TEXT PRIMARY KEY,
    calendar_date               TEXT NOT NULL,
    start_time_seconds          INTEGER,
    start_time_offset_seconds   INTEGER,
    duration_seconds            INTEGER,
    body_battery_level          TEXT,            -- VERY_LOW/LOW/MODERATE/HIGH, if provided
    raw_payload_id              INTEGER REFERENCES raw_payloads(id) ON DELETE SET NULL,
    first_seen_at               TEXT NOT NULL,
    updated_at                  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_stress_calendar ON stress_summaries(calendar_date);

-- Stress level samples (3-min). Value <0 is a sentinel (off-wrist, motion, etc.).
CREATE TABLE IF NOT EXISTS stress_samples (
    calendar_date   TEXT NOT NULL,
    offset_seconds  INTEGER NOT NULL,
    stress_value    INTEGER NOT NULL,
    PRIMARY KEY (calendar_date, offset_seconds)
);

-- Body battery samples (0-100).
CREATE TABLE IF NOT EXISTS body_battery_samples (
    calendar_date       TEXT NOT NULL,
    offset_seconds      INTEGER NOT NULL,
    body_battery_value  INTEGER NOT NULL,
    PRIMARY KEY (calendar_date, offset_seconds)
);

-- --- HRV summaries ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS hrv_summaries (
    summary_id                  TEXT PRIMARY KEY,
    calendar_date               TEXT NOT NULL,
    start_time_seconds          INTEGER,
    start_time_offset_seconds   INTEGER,
    duration_seconds            INTEGER,
    last_night_avg_ms           REAL,
    last_night_5min_high_ms     REAL,
    weekly_avg_ms               REAL,
    baseline_low_ms             REAL,
    baseline_high_ms            REAL,
    status                      TEXT,            -- BALANCED/UNBALANCED/LOW/POOR etc.
    raw_payload_id              INTEGER REFERENCES raw_payloads(id) ON DELETE SET NULL,
    first_seen_at               TEXT NOT NULL,
    updated_at                  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_hrv_calendar ON hrv_summaries(calendar_date);

-- --- sync bookkeeping -------------------------------------------------------
-- One row per sync invocation.
CREATE TABLE IF NOT EXISTS sync_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT NOT NULL,     -- running | success | partial | failed
    trigger         TEXT,              -- manual | scheduled | cli | initial
    window_start    INTEGER,           -- epoch s UTC
    window_end      INTEGER,
    records_written INTEGER DEFAULT 0,
    message         TEXT               -- human-readable summary / error (no secrets)
);

-- Per-category result within a sync run.
CREATE TABLE IF NOT EXISTS sync_category_results (
    sync_run_id     INTEGER NOT NULL REFERENCES sync_runs(id) ON DELETE CASCADE,
    category        TEXT NOT NULL,
    status          TEXT NOT NULL,     -- success | failed | skipped
    records_written INTEGER DEFAULT 0,
    message         TEXT,
    PRIMARY KEY (sync_run_id, category)
);

-- Tracks the last successfully-synced window per category for incremental sync.
CREATE TABLE IF NOT EXISTS sync_state (
    category            TEXT PRIMARY KEY,
    last_success_at     TEXT,          -- ISO-8601 UTC of last successful pull
    last_synced_through INTEGER        -- epoch s UTC: data is current up to here
);
