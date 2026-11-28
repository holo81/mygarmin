# Garmin Personal API — verified endpoints & field mapping

This reflects the **real** Personal API, confirmed against the official Swagger
(`developer.garmin.com` → Personal API Swagger Docs) and validated with live
calls to a real account.

## Authentication (verified)

```
POST https://personal.connectapi.garmin.com/personalapitoken-service/personal-api/personal-api-key/token
Authorization: ApiKey <PERSONAL_API_KEY>
```

Returns an OAuth2 access token (`access_token`, `token_type`, `expires_in`),
valid 24h, no refresh token. Verified: a real key returns a Bearer token with
~86400s lifetime. Implementation: `app/garmin/token.py`. The key may be supplied
inline (`GARMIN_PERSONAL_API_KEY`) or from a file (`GARMIN_PERSONAL_API_KEY_FILE`,
e.g. `./garmin_access.key`). Credentials are never logged.

## Base URL & delivery

- Base: `https://personal.connectapi.garmin.com`
- Delivery is **pull-only**. The API exposes the modern Garmin Connect service
  routes (not the business Health API `wellness-api/rest/*` shape). Dates are
  path segments or query params; timestamps in responses are epoch
  **milliseconds**, with paired GMT and Local values.

## Verified endpoints (used by this app)

| Category | Method & path | Date params | Returns |
| --- | --- | --- | --- |
| Daily summary | `GET /usersummary-service/usersummary/daily` | `?calendarDate=` | one day object |
| Sleep | `GET /sleep-service/sleep/dailySleep` | `?date=` | one sleep object |
| HRV (day) | `GET /hrv-service/hrv/{date}` | path | summary + readings |
| HRV (range) | `GET /hrv-service/hrv/daily/{fromDate}/{toDate}` | path | `hrvSummaries[]` |
| Daily heart rate | `GET /wellness-service/wellness/dailyHeartRate` | `?date=` | `heartRateValues[[ms,bpm]]` |
| Body Battery | `GET /wellness-service/wellness/bodyBattery/reports/daily` | `?startDate=&endDate=` | per-day `bodyBatteryValuesArray` |
| Stress (range) | `GET /usersummary-service/stats/stress/daily/{fromDate}/{toDate}` | path | per-day overall stress |
| Steps (range) | `GET /usersummary-service/stats/steps/daily/{fromDate}/{toDate}` | path | per-day steps |
| Activities | `GET /activitylist-service/activities/search/activities` | `?start=&limit=` | activity summaries |
| Activity detail | `GET /activity-service/activity/{activityId}` | path | `summaryDTO` + metadata |
| Activity FIT | `GET /download-service/files/activity/{activityId}` | path | **ZIP** containing `.FIT` |
| User profile | `GET /userprofile-service/userprofile/settings` | — | units, timezone |

All paths are configurable via `GARMIN_PATH_*` in `.env` (with `{date}`,
`{fromDate}`, `{toDate}`, `{activityId}` placeholders), so a future Garmin route
change needs no code edit.

## Verified JSON schemas → local columns

Confirmed against real responses.

### Daily (`usersummary/daily`) → `daily_summaries`

`calendarDate`, `totalSteps`→steps, `dailyStepGoal`→steps_goal,
`totalDistanceMeters`, `activeKilocalories`, `bmrKilocalories`,
`totalKilocalories`, `minHeartRate`/`maxHeartRate`/`restingHeartRate`,
`lastSevenDaysAvgRestingHeartRate`→resting_hr_7d_avg, `averageStressLevel`
(+ `maxStressLevel`, `*StressDuration`), `stressQualifier`,
`bodyBattery{Charged,Drained,Highest,Lowest,MostRecent}Value`,
`averageSpo2`/`lowestSpo2`, `avgWakingRespirationValue` (+ highest/lowest),
`moderate/vigorousIntensityMinutes` (minutes → stored as seconds),
`sleepingSeconds`, `activeSeconds`. Device offset derived from
`wellnessStartTimeGmt` vs `wellnessStartTimeLocal`.

### Sleep (`sleep/dailySleep`) → `sleep_summaries`

`sleepTimeSeconds`→duration, `deep/light/rem/awakeSleepSeconds`,
`unmeasurableSleepSeconds`, `napTimeSeconds`, `sleepScores.overall.{value,qualifierKey}`,
`averageRespirationValue`, `averageSpO2Value`/`lowestSpO2Value`, `avgSleepStress`,
`avgHeartRate`, `awakeCount`, `sleepWindowConfirmationType`→validation. Start
time + offset from `sleepStartTimestampGMT/Local` (epoch ms).

### HRV (`hrv/{date}`, `hrv/daily/{from}/{to}`) → `hrv_summaries`

`hrvSummary.{lastNightAvg, lastNight5MinHigh, weeklyAvg, status}` and
`baseline.{balancedLow, balancedUpper}` → baseline low/high. The range endpoint
returns `hrvSummaries[]` of the same shape.

### Daily heart rate (`dailyHeartRate`) → `daily_hr_samples`

`heartRateValues` = `[[epochMs, bpm], …]`; null bpm entries are gaps and are
**skipped** (not stored as zero). Offsets computed from `startTimestampGMT`.

### Body Battery (`bodyBattery/reports/daily`) → `body_battery_samples`

Each day: `bodyBatteryValuesArray` = `[[epochMs, level], …]` (descriptor list
confirms index 0=timestamp, 1=bodyBatteryLevel). Summary charged/drained/high/low
come from the daily endpoint.

### Activities (`activities/search/activities`) → `activities`

`activityId` (stable key), `activityName`, `activityType.typeKey`,
`startTimeGMT`/`startTimeLocal`, `duration`, `distance`, `calories`,
`averageHR`/`maxHR`, `averageSpeed`/`maxSpeed`, `elevationGain/Loss`,
`startLatitude/Longitude`, `steps`, `isParent`. Pace derived from avg speed
when > 0.1 m/s.

### Activity time-series → `activity_samples`

The search/detail JSON does **not** include per-second samples. Those come from
the **FIT file** downloaded via `download-service` (a ZIP → unzip → decode with
the official `garmin-fit-sdk`). Record fields: timestamp, position_lat/long
(semicircles → degrees via `180/2³¹`), enhanced_altitude/altitude,
heart_rate, enhanced_speed/speed, cadence, power, distance, temperature.
Verified: a real 5 km run decoded to 2124 samples incl. 2119 GPS points.

## Documented vs derived values

| Derived metric | Formula | Where |
| --- | --- | --- |
| `intensityMinutes` | `moderateMin + 2 × vigorousMin` | `api/presenter._intensity_minutes` |
| `totalKilocalories` (fallback) | `active + bmr` if API total absent | `api/presenter.daily_view` |
| activity `avgPaceMinPerKm` | `(1000 / avgSpeedMps) / 60` | `normalize.normalize_activity` |
| sample `paceMinPerKm` | `(1000 / speedMps) / 60` | `api/presenter.pace_from_speed` |

Note: the real daily endpoint already supplies `totalKilocalories`, so the
fallback rarely triggers. Intensity minutes are stored in seconds for schema
consistency and converted back for display. No proprietary readiness/medical
scores are invented.

## Metric availability (this account, verified)

Present and flowing: steps, distance, floors, calories (active/bmr/total),
resting + min/max HR, 7-day avg RHR, all-day HR time-series, stress
(level/durations/qualifier), Body Battery (summary + intraday series), SpO2
(avg/lowest), respiration (waking avg/high/low), sleep (stages, score, spo2,
respiration, sleep HR/stress), HRV (last-night avg, 5-min high, weekly avg,
baseline band, status), activities (running/walking/strength) with FIT-derived
GPS/HR/elevation/power/cadence.

Endpoints that returned HTTP 400 for the tested params (not wired into sync):
`usersummary/v2/dailysummaries`, `sleep/dailySleepSummariesByDate` — these likely
need different parameters; they are not required since the per-day endpoints
cover the same data. `hydration` and `wellnessactivity range` returned empty
arrays (no data for this account).

## Incremental retrieval

`sync_state.last_synced_through` per category; `incremental()` resumes from the
earliest category's last point minus one day of overlap. Idempotent upserts
(keyed on calendar date or activityId) make overlap and repeated runs safe.
Rate limiting (HTTP 429) is handled with `Retry-After`/backoff — observed and
handled during a real 30-day import.
