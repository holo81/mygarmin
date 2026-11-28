"""Recorded-style fixtures matching the REAL Personal API schemas.

Trimmed from live responses (no personal values of concern). Let tests run with
no credentials or network.
"""

from __future__ import annotations

DAILY = {
    "calendarDate": "2026-10-21",
    "totalKilocalories": 2391.0,
    "activeKilocalories": 158.0,
    "bmrKilocalories": 2233.0,
    "totalSteps": 4433,
    "totalDistanceMeters": 3440,
    "dailyStepGoal": 10000,
    "wellnessStartTimeGmt": "2026-10-20T21:00:00.0",
    "wellnessStartTimeLocal": "2026-10-21T00:00:00.0",
    "durationInMilliseconds": 86400000,
    "moderateIntensityMinutes": 0,
    "vigorousIntensityMinutes": 0,
    "intensityMinutesGoal": 150,
    "floorsAscended": 0.0,
    "userFloorsAscendedGoal": 10,
    "minHeartRate": 49,
    "maxHeartRate": 109,
    "restingHeartRate": 52,
    "lastSevenDaysAvgRestingHeartRate": 55,
    "averageStressLevel": 29,
    "maxStressLevel": 93,
    "stressDuration": 37620,
    "restStressDuration": 35100,
    "lowStressDuration": 25320,
    "mediumStressDuration": 10800,
    "highStressDuration": 1500,
    "stressQualifier": "BALANCED",
    "bodyBatteryChargedValue": 79,
    "bodyBatteryDrainedValue": 83,
    "bodyBatteryHighestValue": 100,
    "bodyBatteryLowestValue": 17,
    "bodyBatteryMostRecentValue": 17,
    "averageSpo2": 97.0,
    "lowestSpo2": 82,
    "avgWakingRespirationValue": 15.0,
    "highestRespirationValue": 23.0,
    "lowestRespirationValue": 7.0,
    "sleepingSeconds": 26406,
    "activeSeconds": 3582,
}

# Device not worn: stress sentinel, missing resting HR.
DAILY_NO_DATA = {
    "calendarDate": "2026-10-20",
    "totalSteps": 0,  # measured zero
    "averageStressLevel": -1,  # sentinel
    "wellnessStartTimeGmt": "2026-10-19T21:00:00.0",
    "wellnessStartTimeLocal": "2026-10-20T00:00:00.0",
    # restingHeartRate intentionally absent -> null
}

SLEEP = {
    "calendarDate": "2026-10-21",
    "sleepTimeSeconds": 27591,
    "napTimeSeconds": 0,
    "sleepWindowConfirmationType": "enhanced_confirmed_final",
    "sleepStartTimestampGMT": 1792528815000,
    "sleepEndTimestampGMT": 1792556406000,
    "sleepStartTimestampLocal": 1792539615000,
    "unmeasurableSleepSeconds": 0,
    "deepSleepSeconds": 3960,
    "lightSleepSeconds": 17580,
    "remSleepSeconds": 6060,
    "awakeSleepSeconds": 0,
    "averageSpO2Value": 97.0,
    "lowestSpO2Value": 82,
    "averageRespirationValue": 12.0,
    "awakeCount": 0,
    "avgSleepStress": 18.0,
    "avgHeartRate": 55.0,
    "sleepScores": {
        "overall": {"value": 87, "qualifierKey": "GOOD"},
        "remPercentage": {"value": 22, "qualifierKey": "GOOD"},
    },
}

HRV = {
    "userProfilePk": 1,
    "startTimestampGMT": "2026-10-20T20:42:51.0",
    "startTimestampLocal": "2026-10-20T23:42:51.0",
    "hrvSummary": {
        "calendarDate": "2026-10-21",
        "weeklyAvg": 54,
        "lastNightAvg": 63,
        "lastNight5MinHigh": 88,
        "baseline": {"lowUpper": 45, "balancedLow": 50, "balancedUpper": 73},
        "status": "BALANCED",
    },
}

HRV_RANGE = {
    "userProfilePk": 1,
    "hrvSummaries": [
        {
            "calendarDate": "2026-10-20",
            "weeklyAvg": 47,
            "lastNightAvg": 48,
            "lastNight5MinHigh": 83,
            "baseline": {"lowUpper": 46, "balancedLow": 50, "balancedUpper": 73},
            "status": "UNBALANCED",
        },
        {
            "calendarDate": "2026-10-21",
            "weeklyAvg": 54,
            "lastNightAvg": 63,
            "lastNight5MinHigh": 88,
            "baseline": {"lowUpper": 45, "balancedLow": 50, "balancedUpper": 73},
            "status": "BALANCED",
        },
    ],
}

DAILY_HEART_RATE = {
    "calendarDate": "2026-10-21",
    "startTimestampGMT": 1792530000000,
    "maxHeartRate": 109,
    "minHeartRate": 49,
    "restingHeartRate": 52,
    "heartRateValueDescriptors": [
        {"index": 0, "key": "timestamp"},
        {"index": 1, "key": "heartrate"},
    ],
    "heartRateValues": [
        [1792530000000, 55],
        [1792530120000, 54],
        [1792530240000, None],  # gap: no reading, must be skipped (not zero)
        [1792530360000, 58],
    ],
}

BODY_BATTERY_REPORT = [
    {
        "date": "2026-10-20",
        "charged": 79,
        "drained": 83,
        "bodyBatteryValueDescriptorDTOList": [
            {"bodyBatteryValueDescriptorIndex": 0, "bodyBatteryValueDescriptorKey": "timestamp"},
            {"bodyBatteryValueDescriptorIndex": 1, "bodyBatteryValueDescriptorKey": "bodyBatteryLevel"},
        ],
        "bodyBatteryValuesArray": [
            [1792011600000, 27],
            [1792038420000, 91],
            [1792040400000, 86],
        ],
    },
    {
        "date": "2026-10-21",
        "charged": 80,
        "drained": 70,
        "bodyBatteryValuesArray": [
            [1792098000000, 30],
            [1792120000000, 88],
        ],
    },
]

STRESS_RANGE = [
    {
        "calendarDate": "2026-10-20",
        "values": {
            "overallStressLevel": 29,
            "restStressDuration": 37860,
            "lowStressDuration": 20820,
            "mediumStressDuration": 9360,
            "highStressDuration": 1680,
        },
    }
]

ACTIVITY = {
    "activityId": 24734466614,
    "activityName": "Strength",
    "startTimeLocal": "2026-10-15 17:11:50",
    "startTimeGMT": "2026-10-15 14:11:50",
    "activityType": {"typeId": 13, "typeKey": "strength_training", "parentTypeId": 29},
    "isParent": False,
    "distance": 0.0,
    "duration": 2710.58,
    "averageSpeed": 0.0,
    "calories": 318.0,
    "bmrCalories": 70.0,
    "averageHR": 112.0,
    "maxHR": 163.0,
    "steps": 208,
}

ACTIVITY_RUN = {
    "activityId": 111,
    "activityName": "Morning Run",
    "startTimeLocal": "2026-10-14 07:30:00",
    "startTimeGMT": "2026-10-14 04:30:00",
    "activityType": {"typeId": 1, "typeKey": "running", "parentTypeId": 17},
    "isParent": False,
    "distance": 10000.0,
    "duration": 3600.0,
    "averageSpeed": 2.78,
    "maxSpeed": 3.5,
    "calories": 650.0,
    "averageHR": 152.0,
    "maxHR": 178.0,
    "elevationGain": 120.0,
    "startLatitude": 60.17,
    "startLongitude": 24.94,
}

HR_ZONES = [
    {
        "sport": "DEFAULT",
        "trainingMethod": "LACTATE_THRESHOLD",
        "restingHeartRateUsed": 55,
        "lactateThresholdHeartRateUsed": 172,
        "maxHeartRateUsed": 197,
        "zone1Floor": 97,
        "zone2Floor": 118,
        "zone3Floor": 154,
        "zone4Floor": 169,
        "zone5Floor": 189,
    },
    {
        "sport": "RUNNING",
        "trainingMethod": "HR_MAX",
        "restingHeartRateUsed": 55,
        "lactateThresholdHeartRateUsed": 171,
        "maxHeartRateUsed": 197,
        "zone1Floor": 99,
        "zone2Floor": 118,
        "zone3Floor": 138,
        "zone4Floor": 158,
        "zone5Floor": 177,
    },
]

FITNESS_AGE = {
    "chronologicalAge": 45,
    "fitnessAge": 46.76,
    "achievableFitnessAge": 38.9,
    "previousFitnessAge": 45.8,
    "components": {
        "rhr": {"value": 53},
        "bmi": {"value": 34.3, "targetValue": 21.5},
        "vigorousDaysAvg": {"value": 0.8, "targetValue": 3},
        "vigorousMinutesAvg": {"value": 50.0, "targetValue": 75},
    },
    "lastUpdated": "2026-10-22T00:00:00.0",
}

WEIGHT_RANGE = {
    "dailyWeightSummaries": [
        {
            "summaryDate": "2026-10-06",
            "latestWeight": {"weight": 98900.0, "bmi": None, "sourceType": "MANUAL"},
        },
        {
            "summaryDate": "2026-10-10",
            "latestWeight": {"weight": 98100.0, "bmi": 30.1, "sourceType": "MANUAL"},
        },
    ],
    "totalAverage": {"weight": 98500.0},
}

TOKEN_RESPONSE = {"access_token": "test-access-token-xyz", "token_type": "Bearer", "expires_in": 86400}
