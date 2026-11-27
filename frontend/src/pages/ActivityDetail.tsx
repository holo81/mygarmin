import { Link, useParams } from "react-router-dom";
import {
  CartesianGrid,
  Area,
  AreaChart,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, useApi } from "../api/client";
import { MetaBanner } from "../components/MetaBanner";
import { Loading, ErrorState, EmptyState } from "../components/States";
import { TrackMap } from "../components/TrackMap";
import {
  activityIcon,
  activityTypeLabel,
  DASH,
  fmtDistance,
  fmtDuration,
  fmtElevation,
  fmtInt,
  fmtLocalDateTime,
  fmtPace,
  fmtSpeedKmh,
} from "../lib/format";
import { cssVar } from "../lib/theme";
import type { Sample } from "../api/types";

export function ActivityDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data, loading, error, reload } = useApi(
    () => api.activity(id as string),
    [id]
  );

  if (loading) return <Loading label="Loading activity…" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  const { activity: a, samples, available, meta } = data;
  const unit = meta.unitSystem;

  // Downsample for charts if there are a lot of points (keeps rendering snappy).
  const chartSamples = downsample(samples, 600);
  const xAxisKey = "offsetSeconds";

  return (
    <>
      <div className="page-head">
        <div>
          <Link to="/activities" className="faint" style={{ fontSize: 13 }}>
            ← All activities
          </Link>
          <h1 className="page-title" style={{ marginTop: 6 }}>
            <span style={{ marginRight: 10 }} aria-hidden>
              {activityIcon(a.activityType)}
            </span>
            {a.activityName || activityTypeLabel(a.activityType)}
          </h1>
          <div className="page-sub">
            {fmtLocalDateTime(a.startLocalIso)}
            {a.deviceName ? ` · ${a.deviceName}` : ""}
            {a.manual ? " · manual entry" : ""}
          </div>
        </div>
      </div>

      <MetaBanner meta={meta} />

      {/* Summary stats */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="stat-row">
          <Stat k="Duration" v={fmtDuration(a.durationSeconds)} />
          {a.distanceMeters != null && (
            <Stat k="Distance" v={fmtDistance(a.distanceMeters, unit)} />
          )}
          {a.avgPaceMinPerKm != null && (
            <Stat k="Avg pace" v={fmtPace(a.avgPaceMinPerKm, unit)} />
          )}
          {a.avgSpeedMps != null && a.avgPaceMinPerKm == null && (
            <Stat k="Avg speed" v={fmtSpeedKmh(a.avgSpeedMps, unit)} />
          )}
          {a.avgHrBpm != null && <Stat k="Avg HR" v={`${a.avgHrBpm} bpm`} />}
          {a.maxHrBpm != null && <Stat k="Max HR" v={`${a.maxHrBpm} bpm`} />}
          {a.activeKilocalories != null && (
            <Stat k="Calories" v={`${fmtInt(a.activeKilocalories)} kcal`} />
          )}
          {a.totalElevationGainM != null && (
            <Stat k="Elev gain" v={fmtElevation(a.totalElevationGainM, unit)} />
          )}
          {a.totalElevationLossM != null && (
            <Stat k="Elev loss" v={fmtElevation(a.totalElevationLossM, unit)} />
          )}
          {a.avgRunCadenceSpm != null && (
            <Stat k="Avg cadence" v={`${Math.round(a.avgRunCadenceSpm)} spm`} />
          )}
          {a.avgBikeCadenceRpm != null && (
            <Stat k="Avg cadence" v={`${Math.round(a.avgBikeCadenceRpm)} rpm`} />
          )}
          {a.steps != null && <Stat k="Steps" v={fmtInt(a.steps)} />}
        </div>
      </div>

      {/* GPS map (only when location data exists) */}
      {available.gps && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="card-title">Route</div>
          <TrackMap samples={samples} />
        </div>
      )}

      {/* Time-series charts — only rendered for metrics that actually exist. */}
      {!available.samples ? (
        <EmptyState
          icon="📉"
          title="No time-series data"
          hint={
            a.manual
              ? "This activity was entered manually, so it has no recorded sample data."
              : "No detailed samples were available for this activity. Run enrich to fetch activity details and FIT files where available."
          }
        />
      ) : (
        <div className="grid two">
          {available.heartRate && (
            <ChartCard title="Heart rate (bpm)">
              <AreaChart data={chartSamples}>
                {commonAxes(xAxisKey)}
                <defs>
                  <linearGradient id="hr" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={cssVar("--bad")} stopOpacity={0.4} />
                    <stop offset="100%" stopColor={cssVar("--bad")} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <Area
                  type="monotone"
                  dataKey="heartRateBpm"
                  stroke={cssVar("--bad")}
                  strokeWidth={2}
                  fill="url(#hr)"
                  connectNulls
                  isAnimationActive={false}
                  dot={false}
                />
                <Tooltip {...tooltip()} />
              </AreaChart>
            </ChartCard>
          )}

          {chartSamples.some((s) => s.paceMinPerKm != null) && (
            <ChartCard title="Pace (min/km)">
              <LineChart data={chartSamples}>
                {commonAxes(xAxisKey)}
                <YAxis reversed width={44} stroke={cssVar("--text-faint")} fontSize={11} />
                <Line
                  type="monotone"
                  dataKey="paceMinPerKm"
                  stroke={cssVar("--accent")}
                  strokeWidth={2}
                  connectNulls
                  isAnimationActive={false}
                  dot={false}
                />
                <Tooltip {...tooltip()} />
              </LineChart>
            </ChartCard>
          )}

          {available.elevation && (
            <ChartCard title="Elevation (m)">
              <AreaChart data={chartSamples}>
                {commonAxes(xAxisKey)}
                <defs>
                  <linearGradient id="elev" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={cssVar("--text-dim")} stopOpacity={0.45} />
                    <stop offset="100%" stopColor={cssVar("--text-dim")} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <Area
                  type="monotone"
                  dataKey="elevationMeters"
                  stroke={cssVar("--text-dim")}
                  strokeWidth={1.5}
                  fill="url(#elev)"
                  connectNulls
                  isAnimationActive={false}
                  dot={false}
                />
                <Tooltip {...tooltip()} />
              </AreaChart>
            </ChartCard>
          )}

          {available.power && (
            <ChartCard title="Power (W)">
              <LineChart data={chartSamples}>
                {commonAxes(xAxisKey)}
                <Line
                  type="monotone"
                  dataKey="powerWatts"
                  stroke={cssVar("--accent-2")}
                  strokeWidth={1.5}
                  connectNulls
                  isAnimationActive={false}
                  dot={false}
                />
                <Tooltip {...tooltip()} />
              </LineChart>
            </ChartCard>
          )}

          {available.cadence && (
            <ChartCard title="Cadence">
              <LineChart data={chartSamples}>
                {commonAxes(xAxisKey)}
                <Line
                  type="monotone"
                  dataKey="cadence"
                  stroke={cssVar("--warn")}
                  strokeWidth={1.5}
                  connectNulls
                  isAnimationActive={false}
                  dot={false}
                />
                <Tooltip {...tooltip()} />
              </LineChart>
            </ChartCard>
          )}
        </div>
      )}
    </>
  );
}

function Stat({ k, v }: { k: string; v: string }) {
  return (
    <div className="stat">
      <div className="k">{k}</div>
      <div className="v">{v || DASH}</div>
    </div>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactElement }) {
  return (
    <div className="card">
      <div className="card-title">{title}</div>
      <div className="chart-wrap">
        <ResponsiveContainer width="100%" height="100%">
          {children}
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function commonAxes(xKey: string) {
  return (
    <>
      <CartesianGrid stroke={cssVar("--chart-grid")} vertical={false} />
      <XAxis
        dataKey={xKey}
        tickFormatter={(s) => fmtDuration(Number(s))}
        stroke={cssVar("--text-faint")}
        fontSize={11}
        minTickGap={48}
      />
      <YAxis width={40} stroke={cssVar("--text-faint")} fontSize={11} />
    </>
  );
}

function tooltip() {
  return {
    contentStyle: {
      background: cssVar("--bg-elev-2"),
      border: `1px solid ${cssVar("--border-strong")}`,
      borderRadius: 8,
      fontSize: 12,
    },
    labelFormatter: (s: number) => `at ${fmtDuration(Number(s))}`,
  };
}

// Even-stride downsample so long activities stay responsive without distorting shape.
function downsample(samples: Sample[], max: number): Sample[] {
  if (samples.length <= max) return samples;
  const step = Math.ceil(samples.length / max);
  return samples.filter((_, i) => i % step === 0);
}
