import { Link } from "react-router-dom";
import { api, useApi } from "../api/client";
import { MetricCard } from "../components/MetricCard";
import { MetaBanner } from "../components/MetaBanner";
import { Loading, ErrorState, EmptyState } from "../components/States";
import {
  activityIcon,
  activityTypeLabel,
  DASH,
  fmtDistance,
  fmtDuration,
  fmtHoursMinutes,
  fmtInt,
  fmtLocalDateTime,
  fmtNum,
  timeAgo,
} from "../lib/format";
import type { Daily } from "../api/types";

export function OverviewPage({ refreshKey }: { refreshKey: number }) {
  const { data, loading, error, reload } = useApi(() => api.overview(), [refreshKey]);

  if (loading) return <Loading label="Loading your dashboard…" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  const { today, sevenDay, recentActivities, meta } = data;
  const unit = meta.unitSystem;
  const hasAnything =
    today.daily || today.sleep || today.hrv || recentActivities.length > 0;

  // Build sparkline arrays from the 7-day window (chronological).
  const stepsSpark = sevenDay.map((d) => d.steps);
  const rhrSpark = sevenDay.map((d) => d.restingHrBpm);
  const stressSpark = sevenDay.map((d) =>
    d.avgStressLevel !== null && d.avgStressLevel >= 0 ? d.avgStressLevel : null
  );

  const lastAt = meta.lastSync?.finished_at ?? meta.lastSync?.started_at ?? null;

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Overview</h1>
          <div className="page-sub">
            {today.daily?.calendarDate
              ? `Latest day: ${today.daily.calendarDate}`
              : "Most recent available metrics"}
            {" · "}
            Last sync {timeAgo(lastAt)}
          </div>
        </div>
      </div>

      <MetaBanner meta={meta} />

      {!hasAnything ? (
        <EmptyState
          icon="⌚"
          title="No data yet"
          hint="Configure your Garmin Personal API key and run a sync to populate the dashboard. In development you can load mock fixtures with the CLI."
        />
      ) : (
        <>
          <div className="grid metrics">
            <MetricCard
              label="Steps"
              icon="👟"
              value={today.daily ? fmtInt(today.daily.steps) : null}
              sub={stepsGoalSub(today.daily)}
              spark={stepsSpark}
            />
            <MetricCard
              label="Resting HR"
              icon="❤️"
              value={today.daily ? fmtInt(today.daily.restingHrBpm) : null}
              unit="bpm"
              sub={
                today.daily?.minHrBpm != null
                  ? `Range ${fmtInt(today.daily.minHrBpm)}–${fmtInt(today.daily.maxHrBpm)} bpm`
                  : undefined
              }
              spark={rhrSpark}
              accent="var(--bad)"
            />
            <MetricCard
              label="Sleep"
              icon="🌙"
              value={today.sleep ? fmtHoursMinutes(today.sleep.durationSeconds) : null}
              sub={sleepSub(today.sleep)}
              accent="var(--accent-2)"
            />
            <MetricCard
              label="Body Battery"
              icon="🔋"
              value={bodyBatteryLatest(today.stress?.bodyBattery)}
              sub={
                today.stress?.bodyBatteryLevel
                  ? today.stress.bodyBatteryLevel.toLowerCase()
                  : undefined
              }
              spark={(today.stress?.bodyBattery ?? []).map((p) => p.value)}
              accent="var(--good)"
            />
            <MetricCard
              label="Stress"
              icon="🌀"
              value={
                today.daily && today.daily.avgStressLevel != null && today.daily.avgStressLevel >= 0
                  ? fmtInt(today.daily.avgStressLevel)
                  : null
              }
              sub={today.daily?.stressQualifier?.replace(/_/g, " ")}
              spark={stressSpark}
              accent="var(--warn)"
            />
            <MetricCard
              label="HRV (last night)"
              icon="💗"
              value={today.hrv ? fmtInt(today.hrv.lastNightAvgMs) : null}
              unit="ms"
              sub={hrvSub(today.hrv)}
            />
            <MetricCard
              label="Intensity minutes"
              icon="⚡"
              value={today.daily ? fmtInt(today.daily.intensityMinutes) : null}
              sub={
                today.daily?.intensityGoalSeconds
                  ? `Goal ${Math.round(today.daily.intensityGoalSeconds / 60)} min/wk`
                  : undefined
              }
            />
            <MetricCard
              label="Calories"
              icon="🔥"
              value={today.daily ? fmtInt(today.daily.totalKilocalories) : null}
              unit="kcal"
              sub={
                today.daily?.activeKilocalories != null
                  ? `${fmtInt(today.daily.activeKilocalories)} active`
                  : undefined
              }
            />
          </div>

          <div className="grid two" style={{ marginTop: 20 }}>
            <SevenDayCard days={sevenDay} unit={unit} />
            <RecentActivitiesCard activities={recentActivities} unit={unit} />
          </div>
        </>
      )}
    </>
  );
}

function stepsGoalSub(daily: Daily | null) {
  if (!daily || daily.steps == null) return undefined;
  if (daily.stepsGoal == null) return `${fmtDistanceInline(daily.distanceMeters)}`;
  const pct = Math.round((daily.steps / daily.stepsGoal) * 100);
  return `${pct}% of ${fmtInt(daily.stepsGoal)} goal`;
}

function fmtDistanceInline(m: number | null) {
  return m == null ? "" : `${(m / 1000).toFixed(1)} km`;
}

function sleepSub(sleep: { overallScoreValue: number | null; overallScoreQualifier: string | null } | null) {
  if (!sleep) return undefined;
  if (sleep.overallScoreValue == null) return undefined;
  return `Score ${sleep.overallScoreValue}${
    sleep.overallScoreQualifier ? ` · ${sleep.overallScoreQualifier.toLowerCase()}` : ""
  }`;
}

function hrvSub(hrv: { status: string | null; weeklyAvgMs: number | null } | null) {
  if (!hrv) return undefined;
  const parts: string[] = [];
  if (hrv.status) parts.push(hrv.status.toLowerCase());
  if (hrv.weeklyAvgMs != null) parts.push(`7d avg ${Math.round(hrv.weeklyAvgMs)} ms`);
  return parts.join(" · ") || undefined;
}

function bodyBatteryLatest(points: { value: number }[] | undefined): string | null {
  if (!points || points.length === 0) return null;
  return fmtInt(points[points.length - 1].value);
}

function SevenDayCard({ days, unit }: { days: Daily[]; unit: string }) {
  if (days.length === 0) {
    return (
      <div className="card">
        <div className="card-title">7-day activity</div>
        <EmptyState icon="📊" title="Not enough data" />
      </div>
    );
  }
  const totalSteps = days.reduce((a, d) => a + (d.steps ?? 0), 0);
  const totalDist = days.reduce((a, d) => a + (d.distanceMeters ?? 0), 0);
  const avgRhr = avg(days.map((d) => d.restingHrBpm));
  return (
    <div className="card">
      <div className="card-title">7-day summary</div>
      <div className="stat-row">
        <div className="stat">
          <div className="k">Total steps</div>
          <div className="v">{fmtInt(totalSteps)}</div>
        </div>
        <div className="stat">
          <div className="k">Distance</div>
          <div className="v">{fmtDistance(totalDist, unit)}</div>
        </div>
        <div className="stat">
          <div className="k">Avg resting HR</div>
          <div className="v">{avgRhr == null ? DASH : `${Math.round(avgRhr)} bpm`}</div>
        </div>
        <div className="stat">
          <div className="k">Days with data</div>
          <div className="v">{days.filter((d) => d.steps != null).length}/7</div>
        </div>
      </div>
    </div>
  );
}

function RecentActivitiesCard({
  activities,
  unit,
}: {
  activities: import("../api/types").Activity[];
  unit: string;
}) {
  return (
    <div className="card">
      <div className="card-title">
        Recent activities
        <Link to="/activities" className="faint" style={{ fontWeight: 600 }}>
          View all →
        </Link>
      </div>
      {activities.length === 0 ? (
        <EmptyState icon="🏃" title="No activities yet" />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {activities.map((a) => (
            <Link
              key={a.summaryId}
              to={`/activities/${encodeURIComponent(a.summaryId)}`}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "9px 6px",
                borderBottom: "1px solid var(--border)",
              }}
            >
              <span style={{ fontSize: 20 }} aria-hidden>
                {activityIcon(a.activityType)}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600 }}>
                  {a.activityName || activityTypeLabel(a.activityType)}
                </div>
                <div className="faint" style={{ fontSize: 12 }}>
                  {fmtLocalDateTime(a.startLocalIso)}
                </div>
              </div>
              <div style={{ textAlign: "right", fontSize: 13 }}>
                <div>{a.distanceMeters != null ? fmtDistance(a.distanceMeters, unit) : fmtDuration(a.durationSeconds)}</div>
                <div className="faint" style={{ fontSize: 12 }}>
                  {a.avgHrBpm != null ? `${a.avgHrBpm} bpm` : fmtDuration(a.durationSeconds)}
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function avg(values: (number | null)[]): number | null {
  const v = values.filter((x): x is number => x != null);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}

// silence unused import in some build configs
void fmtNum;
