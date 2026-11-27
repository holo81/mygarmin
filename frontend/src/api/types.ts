// Shapes mirror the backend presenter output. Nullable fields are nullable here
// too: `null` means "no data" and must be rendered differently from 0.

export interface SyncRun {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  trigger: string | null;
  window_start: number | null;
  window_end: number | null;
  records_written: number;
  message: string | null;
  categories?: CategoryResult[];
}

export interface CategoryResult {
  category: string;
  status: string;
  records_written: number;
  message: string | null;
}

export interface SyncState {
  category: string;
  last_success_at: string | null;
  last_synced_through: number | null;
}

export interface Meta {
  dataSource: "mock" | "garmin";
  appEnv: string;
  lastSync: SyncRun | null;
  syncState: SyncState[];
  isStale: boolean | null;
  displayTimezone: string;
  unitSystem: string;
}

export interface Daily {
  calendarDate: string | null;
  steps: number | null;
  stepsGoal: number | null;
  distanceMeters: number | null;
  floorsClimbed: number | null;
  floorsClimbedGoal: number | null;
  activeKilocalories: number | null;
  bmrKilocalories: number | null;
  totalKilocalories: number | null;
  activeTimeSeconds: number | null;
  moderateIntensitySeconds: number | null;
  vigorousIntensitySeconds: number | null;
  intensityGoalSeconds: number | null;
  intensityMinutes: number | null;
  minHrBpm: number | null;
  maxHrBpm: number | null;
  averageHrBpm: number | null;
  restingHrBpm: number | null;
  avgStressLevel: number | null;
  maxStressLevel: number | null;
  stressQualifier: string | null;
  bodyBatteryHigh: number | null;
  bodyBatteryLow: number | null;
  bodyBatteryMostRecent: number | null;
  avgSpo2: number | null;
  avgWakingRespiration: number | null;
}

export interface Sleep {
  calendarDate: string | null;
  startLocalIso: string | null;
  durationSeconds: number | null;
  unmeasurableSeconds: number | null;
  deepSeconds: number | null;
  lightSeconds: number | null;
  remSeconds: number | null;
  awakeSeconds: number | null;
  totalNapSeconds: number | null;
  overallScoreValue: number | null;
  overallScoreQualifier: string | null;
  avgSleepRespiration: number | null;
  avgSleepSpo2: number | null;
  validation: string | null;
}

export interface Hrv {
  calendarDate: string | null;
  lastNightAvgMs: number | null;
  lastNight5MinHighMs: number | null;
  weeklyAvgMs: number | null;
  baselineLowMs: number | null;
  baselineHighMs: number | null;
  status: string | null;
}

export interface BodyBatteryPoint {
  offsetSeconds: number;
  value: number;
}

export interface FitnessAge {
  calendarDate: string | null;
  chronologicalAge: number | null;
  fitnessAge: number | null;
  achievableFitnessAge: number | null;
  previousFitnessAge: number | null;
  deltaYears: number | null;
  rhr: number | null;
  bmi: number | null;
  components: Record<string, unknown> | null;
}

export interface Overview {
  meta: Meta;
  today: {
    daily: Daily | null;
    sleep: Sleep | null;
    hrv: Hrv | null;
    fitnessAge: FitnessAge | null;
    stress: {
      calendarDate: string;
      bodyBatteryLevel: number | null;
      bodyBattery: BodyBatteryPoint[];
    } | null;
  };
  sevenDay: Daily[];
  recentActivities: Activity[];
}

export interface Activity {
  summaryId: string;
  activityId: string | null;
  activityType: string | null;
  activityName: string | null;
  startTimeSeconds: number | null;
  startTimeOffsetSeconds: number | null;
  startLocalIso: string | null;
  durationSeconds: number | null;
  distanceMeters: number | null;
  activeKilocalories: number | null;
  avgHrBpm: number | null;
  maxHrBpm: number | null;
  avgSpeedMps: number | null;
  maxSpeedMps: number | null;
  avgPaceMinPerKm: number | null;
  avgRunCadenceSpm: number | null;
  maxRunCadenceSpm: number | null;
  avgBikeCadenceRpm: number | null;
  avgSwimCadenceSpm: number | null;
  totalElevationGainM: number | null;
  totalElevationLossM: number | null;
  startingLatitude: number | null;
  startingLongitude: number | null;
  steps: number | null;
  deviceName: string | null;
  manual: boolean | null;
  hasDetails: boolean;
  hasFit: boolean;
}

export interface ActivityList {
  meta: Meta;
  total: number;
  limit: number;
  offset: number;
  activityTypes: string[];
  items: Activity[];
}

export interface Sample {
  index: number;
  offsetSeconds: number | null;
  clockTimeSeconds: number | null;
  latitude: number | null;
  longitude: number | null;
  elevationMeters: number | null;
  heartRateBpm: number | null;
  speedMps: number | null;
  paceMinPerKm: number | null;
  cadence: number | null;
  powerWatts: number | null;
  distanceMeters: number | null;
  temperatureCelsius: number | null;
}

export interface HrZone {
  zone: string;
  seconds: number;
  percent: number | null;
}

export interface Split {
  split: number;
  distanceMeters: number;
  durationSeconds: number | null;
  paceMinPerKm: number | null;
  avgHrBpm: number | null;
  elevationChangeMeters: number | null;
}

export interface ActivityDetail {
  meta: Meta;
  activity: Activity;
  samples: Sample[];
  derived: {
    hrZones: { basis: string; zones: HrZone[] } | null;
    splitsPerKm: Split[] | null;
  };
  available: {
    gps: boolean;
    heartRate: boolean;
    elevation: boolean;
    power: boolean;
    cadence: boolean;
    samples: boolean;
  };
}

export interface TrendPoint {
  date: string;
  value: number | null;
  [k: string]: unknown;
}

export interface Trends {
  meta: Meta;
  range: string;
  startDate?: string;
  endDate?: string;
  series: {
    restingHeartRate: TrendPoint[];
    steps: TrendPoint[];
    stress: TrendPoint[];
    intensityMinutes: TrendPoint[];
    sleepDuration: TrendPoint[];
    hrv: TrendPoint[];
    weight: TrendPoint[];
  };
}

export interface SyncStatus {
  meta: Meta;
  runs: SyncRun[];
}
