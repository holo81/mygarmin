# Garmin Personal API — verified endpoints & field mapping

This documents what was verified against official Garmin materials while building
the client, and how raw API fields map to the local schema and the UI.

## Authentication (verified)

Documented on the Garmin Connect Developer Program Personal API pages:

```
POST https://personal.connectapi.garmin.com/personalapitoken-service/personal-api/personal-api-key/token
Authorization: ApiKey <PERSONAL_API_KEY>
```

- Returns an **OAuth2 access token**.
- Access tokens are valid for **24 hours** or until the key expires, whichever is
  first.
- **No refresh tokens.** A new access token is obtained by calling the endpoint
  again.
- Personal API keys expire after 30 / 90 / 180 days or 1 year and are shown only
  once at creation.

Implementation: `app/garmin/token.py` posts the `ApiKey` header, caches the
returned token on disk (owner-only permissions), refreshes within a 5-minute
safety margin of expiry, and treats HTTP 401/403 as **permanent** (no retry).

## Delivery model (verified)

The Garmin Connect Developer Program overview lists the **Personal** tier as:

| Data              | Format       | Delivery |
| ----------------- | ------------ | -------- |
| Activity data     | JSON & .FIT  | Pull     |
| Health data       | JSON         | Pull     |
| Women's health    | JSON         | Pull     |

Business/Enterprise tiers are push-based; **Personal is pull-only**, which is why
this app issues GET requests over time windows rather than running a webhook.

## Resource paths (configurable)

The Personal API wraps Garmin's Health/Wellness REST API and Activity API. Those
services use `…/wellness-api/rest/<resource>` with a UTC time window:

```
GET <base>/wellness-api/rest/activities?uploadStartTimeInSeconds=<s>&uploadEndTimeInSeconds=<e>
GET <base>/wellness-api/rest/activityDetails?uploadStartTimeInSeconds=<s>&uploadEndTimeInSeconds=<e>
GET <base>/wellness-api/rest/activityFile?id=<id>&token=<fileToken>
```

The full set of Personal API resource paths is published in Garmin's
**login-gated** Personal API Swagger, which can't be read without an account.
To avoid guessing, every path is **configuration-driven** via `GARMIN_PATH_*` in
`.env` (defaults follow the documented `wellness-api` model). If a path returns
404, the client raises a clear error telling you to adjust the matching
`GARMIN_PATH_*` to your account's Swagger. The base host is `GARMIN_API_BASE_URL`
(default `https://personal.connectapi.garmin.com`).

Logical categories (see `Settings.resource_paths()`): `dailies`, `sleeps`,
`stress`, `hrv`, `respiration`, `pulseox`, `activities`, `activity_details`,
`activity_file`.

## Verified JSON schemas → local columns

Field names below are the camelCase keys documented in Garmin's Health/Activity
API specification and data-export schemas. The normalizer (`app/normalize.py`)
reads them case-insensitively (so PascalCase export payloads also work).

### Daily summary → `daily_summaries`

| API field | Column | Notes |
| --- | --- | --- |
| `summaryId` | `summary_id` | natural key |
| `calendarDate` | `calendar_date` | `yyyy-mm-dd`, UI display date |
| `startTimeInSeconds` / `startTimeOffsetInSeconds` | `start_time_seconds` / `start_time_offset_seconds` | UTC epoch + device offset |
| `steps`, `stepsGoal` | `steps`, `steps_goal` | |
| `distanceInMeters` | `distance_meters` | meters (source unit) |
| `activeKilocalories`, `bmrKilocalories` | `active_kilocalories`, `bmr_kilocalories` | |
| `moderateIntensityDurationInSeconds`, `vigorousIntensityDurationInSeconds` | `moderate_intensity_seconds`, `vigorous_intensity_seconds` | |
| `min/max/average/restingHeartRateInBeatsPerMinute` | `min_hr_bpm` / `max_hr_bpm` / `average_hr_bpm` / `resting_hr_bpm` | `average` is Garmin's 7-day avg |
| `averageStressLevel`, `maxStressLevel` | `avg_stress_level`, `max_stress_level` | `-1`/`-2` = not enough data (kept, hidden by UI) |
| `stressQualifier` | `stress_qualifier` | e.g. `balanced`, `stressful_awake` |
| `timeOffsetHeartRateSamples` | `daily_hr_samples` | expanded to {offset→bpm} rows |

### Sleep → `sleep_summaries` / `sleep_stages`

| API field | Column |
| --- | --- |
| `deepSleepDurationInSeconds` / `lightSleepDurationInSeconds` / `remSleepInSeconds` / `awakeDurationInSeconds` | `deep_seconds` / `light_seconds` / `rem_seconds` / `awake_seconds` |
| `unmeasurableSleepInSeconds` | `unmeasurable_seconds` |
| `overallSleepScore.value` / `.qualifierKey` | `overall_score_value` / `overall_score_qualifier` |
| `validation` | `validation` (e.g. `ENHANCED_FINAL`) |
| `sleepLevelsMap` | `sleep_stages` (stage interval rows) |
| `timeOffsetSleepRespiration` | **derived** mean → `avg_sleep_respiration` |
| `timeOffsetSleepSpo2` | **derived** mean → `avg_sleep_spo2` |

### Stress detail + Body Battery → `stress_summaries` / `stress_samples` / `body_battery_samples`

| API field | Column |
| --- | --- |
| `bodyBatteryDynamicFeedbackEvent.bodyBatteryLevel` | `body_battery_level` |
| `timeOffsetStressLevelValues` | `stress_samples` (value `<0` = off-wrist/motion sentinel, preserved) |
| `timeOffsetBodyBatteryValues` | `body_battery_samples` (0–100) |

### HRV → `hrv_summaries`

| API field | Column |
| --- | --- |
| `hrvSummary.lastNightAvg` | `last_night_avg_ms` |
| `hrvSummary.weeklyAvg` | `weekly_avg_ms` |
| `hrvSummary.baselineBalancedLow` / `…High` | `baseline_low_ms` / `baseline_high_ms` |
| `hrvSummary.status` | `status` (e.g. `BALANCED`) |

### Activities → `activities`

`summaryId`, `activityId`, `activityType`, `activityName`,
`startTimeInSeconds`/`startTimeOffsetInSeconds`, `durationInSeconds`,
`distanceInMeters`, `activeKilocalories`,
`average/maxHeartRateInBeatsPerMinute`, `average/maxSpeedInMetersPerSecond`,
`averagePaceInMinutesPerKilometer`, `averageRun/BikeCadence…`,
`totalElevationGain/LossInMeters`, `startingLatitude/LongitudeInDegree`,
`steps`, `deviceName`, `isParent`, `parentSummaryId`, `manual`.

### Activity detail samples → `activity_samples`

From `activityDetails.samples[]` and/or decoded `.FIT` `record` messages:
`startTimeInSeconds`, `latitude/longitudeInDegree`, `elevationInMeters`,
`heartRate`, `speedMetersPerSecond`, `stepsPerMinute`/`bikeCadenceInRPM`,
`powerInWatts`, `totalDistanceInMeters`, `airTemperatureCelcius`.

FIT decoding uses the official `garmin-fit-sdk`. Positions are converted from
semicircles to degrees (`180 / 2^31`); timestamps from the FIT epoch
(1989-12-31) to Unix.

## Documented vs derived values

Everything above maps directly to a documented API field **except** these clearly
labelled derived metrics, computed by this app (not supplied by Garmin):

| Derived metric | Formula | Where |
| --- | --- | --- |
| `avgSleepRespiration` | mean of `timeOffsetSleepRespiration` | `normalize.normalize_sleep` |
| `avgSleepSpo2` | mean of `timeOffsetSleepSpo2` | `normalize.normalize_sleep` |
| `intensityMinutes` | `moderateMin + 2 × vigorousMin` | `api/presenter._intensity_minutes` |
| `totalKilocalories` | `activeKilocalories + bmrKilocalories` | `api/presenter.daily_view` |
| sample `paceMinPerKm` | `(1000 / speedMps) / 60` | `api/presenter.pace_from_speed` |

No proprietary "readiness" or medical-diagnosis scores are invented. Sleep/HRV/
stress are shown as Garmin reported them, with qualifiers where Garmin provides
them.

## Incremental retrieval

The documented pull model uses an upload-time window. `sync_state` records
`last_synced_through` per category; `SyncEngine.incremental()` resumes from the
earliest category's last point (overlapping one day to catch late/updated
summaries — safe because upserts are idempotent). Historical import is bounded by
`INITIAL_IMPORT_DAYS`. If Garmin limits available history for the Personal tier,
only the days the API actually returns are stored — the app does not pretend to
have more.
