"""Recorded-style API payload fixtures.

These mirror the documented Garmin Health/Activity API schemas (camelCase JSON).
They let tests run without any real credentials or network access.
"""

from __future__ import annotations

# A daily summary as the wellness-api returns it.
DAILY = {
    "summaryId": "x111-daily-1",
    "calendarDate": "2026-02-08",
    "startTimeInSeconds": 1675832400,
    "startTimeOffsetInSeconds": 7200,
    "durationInSeconds": 86400,
    "steps": 12543,
    "stepsGoal": 10000,
    "distanceInMeters": 9100.5,
    "floorsClimbed": 7,
    "activeKilocalories": 856,
    "bmrKilocalories": 1600,
    "activeTimeInSeconds": 5400,
    "moderateIntensityDurationInSeconds": 1800,
    "vigorousIntensityDurationInSeconds": 600,
    "intensityDurationGoalInSeconds": 9000,
    "minHeartRateInBeatsPerMinute": 48,
    "maxHeartRateInBeatsPerMinute": 165,
    "averageHeartRateInBeatsPerMinute": 68,
    "restingHeartRateInBeatsPerMinute": 52,
    "averageStressLevel": 35,
    "maxStressLevel": 78,
    "stressQualifier": "balanced",
    "timeOffsetHeartRateSamples": {"0": 75, "15": 74, "900": 60},
}

# A daily summary where the device was not worn: stress sentinels, null-ish fields.
DAILY_NO_DATA = {
    "summaryId": "x111-daily-2",
    "calendarDate": "2026-02-07",
    "startTimeInSeconds": 1675746000,
    "startTimeOffsetInSeconds": 7200,
    "durationInSeconds": 86400,
    "steps": 0,  # measured zero
    "averageStressLevel": -1,  # sentinel: not enough data
    # restingHeartRateInBeatsPerMinute intentionally ABSENT (null, not zero)
}

SLEEP = {
    "summaryId": "x111-sleep-1",
    "calendarDate": "2026-02-08",
    "startTimeInSeconds": 1675810000,
    "startTimeOffsetInSeconds": 7200,
    "durationInSeconds": 28800,
    "unmeasurableSleepInSeconds": 0,
    "deepSleepDurationInSeconds": 7200,
    "lightSleepDurationInSeconds": 14400,
    "remSleepInSeconds": 7200,
    "awakeDurationInSeconds": 1800,
    "overallSleepScore": {"value": 85, "qualifierKey": "GOOD"},
    "validation": "ENHANCED_FINAL",
    "timeOffsetSleepRespiration": {"60": 14.0, "120": 16.0},
    "timeOffsetSleepSpo2": {"60": 95, "120": 97},
    "sleepLevelsMap": {
        "deep": [{"startTimeInSeconds": 1675810000, "endTimeInSeconds": 1675817200}],
        "light": [{"startTimeInSeconds": 1675817200, "endTimeInSeconds": 1675831600}],
        "rem": [{"startTimeInSeconds": 1675831600, "endTimeInSeconds": 1675838800}],
    },
}

STRESS = {
    "summaryId": "x111-stress-1",
    "calendarDate": "2026-02-08",
    "startTimeInSeconds": 1675832400,
    "startTimeOffsetInSeconds": 7200,
    "durationInSeconds": 86400,
    "bodyBatteryDynamicFeedbackEvent": {
        "eventStartTimeInSeconds": 1675860000,
        "bodyBatteryLevel": "MODERATE",
    },
    "timeOffsetStressLevelValues": {"0": 20, "180": -2, "360": 45},
    "timeOffsetBodyBatteryValues": {"0": 60, "3600": 58, "7200": 55},
}

HRV = {
    "summaryId": "x111-hrv-1",
    "calendarDate": "2026-02-08",
    "startTimeInSeconds": 1675810000,
    "startTimeOffsetInSeconds": 7200,
    "durationInSeconds": 28800,
    "hrvSummary": {
        "lastNightAvg": 45,
        "lastNight5MinHigh": 68,
        "weeklyAvg": 42,
        "baselineBalancedLow": 38,
        "baselineBalancedHigh": 48,
        "status": "BALANCED",
    },
}

ACTIVITY = {
    "summaryId": "x111-act-1",
    "activityId": "987654",
    "activityType": "RUNNING",
    "activityName": "Morning Run",
    "startTimeInSeconds": 1675846800,
    "startTimeOffsetInSeconds": 7200,
    "durationInSeconds": 3600,
    "averageSpeedInMetersPerSecond": 2.78,
    "distanceInMeters": 10000.0,
    "activeKilocalories": 650,
    "averageHeartRateInBeatsPerMinute": 152,
    "maxHeartRateInBeatsPerMinute": 178,
    "averageRunCadenceInStepsPerMinute": 165.0,
    "totalElevationGainInMeters": 120.0,
    "startingLatitudeInDegree": 60.17,
    "startingLongitudeInDegree": 24.94,
    "deviceName": "Forerunner 965",
    "manual": False,
}

ACTIVITY_DETAILS = {
    "summary": {"summaryId": "x111-act-1", "activityId": "987654"},
    "samples": [
        {
            "startTimeInSeconds": 1675846800,
            "latitudeInDegree": 60.1700,
            "longitudeInDegree": 24.9400,
            "elevationInMeters": 10.0,
            "heartRate": 140,
            "speedMetersPerSecond": 2.5,
            "stepsPerMinute": 160.0,
            "totalDistanceInMeters": 0.0,
        },
        {
            "startTimeInSeconds": 1675846810,
            "latitudeInDegree": 60.1702,
            "longitudeInDegree": 24.9403,
            "elevationInMeters": 11.0,
            "heartRate": 150,
            "speedMetersPerSecond": 2.9,
            "stepsPerMinute": 168.0,
            "totalDistanceInMeters": 27.0,
        },
    ],
}

TOKEN_RESPONSE = {"access_token": "test-access-token-xyz", "token_type": "Bearer", "expires_in": 86400}
