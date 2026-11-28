import { useState } from "react";
import { Link } from "react-router-dom";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, useApi } from "../api/client";
import { MetricCard } from "../components/MetricCard";
import { MetaBanner } from "../components/MetaBanner";
import { ExportButton } from "../components/ExportButton";
import { ChartBoundary } from "../components/ChartBoundary";
import { Contributors, ScoreRing } from "../components/ScoreRing";
import { TrainingHeatmap } from "../components/TrainingHeatmap";
import { cssVar } from "../lib/theme";
import { timeAxis } from "../lib/chart";
import { dailyInsight, recoveryScore, sleepScore, strainScore } from "../lib/scores";
import { Loading, ErrorState, EmptyState } from "../components/States";
import {
  activityColor,
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

type RingKey = "recovery" | "sleep" | "strain";

export function OverviewPage({ refreshKey }: { refreshKey: number }) {
  const { data, loading, error, reload } = useApi(() => api.overview(), [refreshKey]);
  const [open, setOpen] = useState<RingKey | null>(null);

  if (loading && !data) return <Loading label="Loading your dashboard…" />;
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

  const scores = {
    recovery: recoveryScore(today, sevenDay),
    sleep: sleepScore(today.sleep),
    strain: strainScore(today, sevenDay),
  };
  const insight = dailyInsight(scores.recovery, today.hrv);
  const rings: { key: RingKey; label: string; grad: "rec" | "slp" | "str"; g: string }[] = [
    { key: "recovery", label: "Recovery", grad: "rec", g: "recovery" },
    { key: "sleep", label: "Sleep", grad: "slp", g: "sleep" },
    { key: "strain", label: "Strain", grad: "str", g: "strain" },
  ];
  const openRing = rings.find((r) => r.key === open);
  const bbPoints = today.stress?.bodyBattery ?? [];

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
        {hasAnything && (
          <ExportButton
            fetcher={() => api.healthSnapshotExport()}
            label="🤖 Export health snapshot"
            title="Health snapshot export"
            filenameBase={`health-snapshot-${today.daily?.calendarDate ?? "latest"}`}
            description="Today's health metrics with 7/30-day baselines, deltas, and trend arrays — built for an AI coach. Paste it to your assistant, or download it."
          />
        )}
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
          <div className="hero">
            {rings.map((r) => (
              <ScoreRing
                key={r.key}
                label={r.label}
                grad={r.grad}
                score={scores[r.key]}
                open={open === r.key}
                onClick={() => setOpen(open === r.key ? null : r.key)}
              />
            ))}
          </div>
          {openRing && (
            <Contributors title={openRing.label} score={scores[openRing.key]} grad={openRing.g} />
          )}
          {insight && <p className="insight">{insight}</p>}

          {bbPoints.length >= 2 && <BodyBatteryCard points={bbPoints} />}

          <div className="grid metrics" style={{ marginTop: 16 }}>
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
              accent="var(--hrt-a)"
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
                today.daily?.bodyBatteryHigh != null && today.daily.bodyBatteryLow != null
                  ? `Range ${today.daily.bodyBatteryLow}–${today.daily.bodyBatteryHigh}`
                  : undefined
              }
              spark={(today.stress?.bodyBattery ?? []).map((p) => p.value)}
              accent="var(--rec-a)"
            />
            <MetricCard
              label="Stress"
              icon="🌀"
              value={
                today.daily && today.daily.avgStressLevel != null && today.daily.avgStressLevel >= 0
                  ? fmtInt(today.daily.avgStressLevel)
                  : null
              }
              sub={stressSub(today.daily?.stressQualifier)}
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
            <MetricCard
              label="Fitness age"
              icon="🎂"
              value={today.fitnessAge ? fmtNum(today.fitnessAge.fitnessAge, 1) : null}
              unit="yrs"
              sub={fitnessAgeSub(today.fitnessAge)}
              accent="var(--accent-2)"
            />
          </div>

          <div style={{ marginTop: 20 }}>
            <TrainingHeatmap endDate={today.daily?.calendarDate} />
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

function stressSub(q: string | null | undefined) {
  if (!q || q.toUpperCase() === "UNKNOWN") return undefined;
  return q.replace(/_/g, " ");
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

function fitnessAgeSub(fa: import("../api/types").FitnessAge | null) {
  if (!fa || fa.fitnessAge == null || fa.deltaYears == null) return undefined;
  const d = fa.deltaYears;
  if (Math.abs(d) < 0.1) return "on par with your age";
  const younger = d < 0;
  return `${Math.abs(d).toFixed(1)} yrs ${younger ? "younger" : "older"} than actual`;
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
              className="act-row"
            >
              <span className="act-chip" style={{ ["--chip" as string]: activityColor(a.activityType) }} aria-hidden>
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
                <div style={{ fontWeight: 700 }}>
                  {a.distanceMeters != null ? fmtDistance(a.distanceMeters, unit) : fmtDuration(a.durationSeconds)}
                </div>
                <div className="faint" style={{ fontSize: 12 }}>
                  {[a.distanceMeters != null ? fmtDuration(a.durationSeconds) : null, a.avgHrBpm != null ? `${a.avgHrBpm} bpm` : null]
                    .filter(Boolean)
                    .join(" · ") || DASH}
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

function BodyBatteryCard({ points }: { points: { offsetSeconds: number; value: number }[] }) {
  const hhmm = (sec: number) => `${String(Math.floor(sec / 3600) % 24).padStart(2, "0")}:${String(Math.floor((sec % 3600) / 60)).padStart(2, "0")}`;
  const xAxis = timeAxis(points[0].offsetSeconds, points[points.length - 1].offsetSeconds, 8);
  return (
    <div className="card">
      <div className="card-title">Body battery today</div>
      <ChartBoundary>
        <div style={{ width: "100%", height: 200 }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={points} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="bb-fill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={cssVar("--rec-a")} stopOpacity={0.5} />
                  <stop offset="100%" stopColor={cssVar("--rec-b")} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={cssVar("--chart-grid")} vertical={false} />
              <XAxis type="number" dataKey="offsetSeconds" domain={xAxis.domain} ticks={xAxis.ticks} tickFormatter={hhmm} stroke={cssVar("--text-faint")} fontSize={11} />
              <YAxis width={32} domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} stroke={cssVar("--text-faint")} fontSize={11} />
              <Area type="monotone" dataKey="value" stroke={cssVar("--rec-a")} strokeWidth={2.5} fill="url(#bb-fill)" isAnimationActive={false} dot={false} />
              <Tooltip
                contentStyle={{ background: cssVar("--bg-elev-2"), border: `1px solid ${cssVar("--border-strong")}`, borderRadius: 8, fontSize: 12 }}
                labelFormatter={(s: number) => hhmm(Number(s))}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </ChartBoundary>
    </div>
  );
}
