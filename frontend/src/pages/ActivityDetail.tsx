import { Link, useParams } from "react-router-dom";
import {
  CartesianGrid,
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, useApi } from "../api/client";
import { MetaBanner } from "../components/MetaBanner";
import { ChartBoundary } from "../components/ChartBoundary";
import { Loading, ErrorState, EmptyState } from "../components/States";
import { TrackMap } from "../components/TrackMap";
import { ExportButton } from "../components/ExportButton";
import {
  activityColor,
  activityIcon,
  activityTypeLabel,
  DASH,
  fmtDistance,
  fmtDuration,
  fmtElevation,
  fmtInt,
  fmtLocalDateTime,
  fmtPace,
  fmtPaceClock,
  fmtSpeedKmh,
} from "../lib/format";
import { niceAxis, timeAxis } from "../lib/chart";
import { cssVar } from "../lib/theme";
import type { ActivityDetail, Sample } from "../api/types";

export function ActivityDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data, loading, error, reload } = useApi(
    () => api.activity(id as string),
    [id]
  );

  if (loading) return <Loading label="Loading activity…" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  const { activity: a, samples, available, meta, derived } = data;
  const unit = meta.unitSystem;
  const title = a.activityName || activityTypeLabel(a.activityType);

  const imperial = unit === "imperial";
  // Downsample for charts if there are a lot of points (keeps rendering snappy).
  // Pace: drop null/zero speed and anything slower than 20 min/km (standing still, GPS glitches).
  // Pace and elevation are converted to the page's unit system here.
  const chartSamples: PlotSample[] = downsample(samples, 600)
    .filter((s) => s.offsetSeconds != null)
    .map((s) => ({
      ...s,
      pace:
        s.paceMinPerKm != null && s.paceMinPerKm > 0 && s.paceMinPerKm <= 20 && (s.speedMps ?? 1) > 0
          ? s.paceMinPerKm * (imperial ? 1.609344 : 1)
          : null,
      elev: s.elevationMeters == null ? null : imperial ? s.elevationMeters * 3.28084 : s.elevationMeters,
    }));
  const maxOffset = chartSamples.reduce((m, s) => Math.max(m, s.offsetSeconds as number), 0);
  const xAxis = timeAxis(0, maxOffset);

  const charts: { key: keyof PlotSample; title: string; color: string; show: boolean; reversed?: boolean; pad?: number; clip?: boolean }[] = [
    { key: "heartRateBpm", title: "Heart rate (bpm)", color: "--bad", show: available.heartRate, pad: 5 },
    { key: "pace", title: `Pace (min/${imperial ? "mi" : "km"})`, color: "--accent", show: chartSamples.some((s) => s.pace != null), reversed: true, clip: true },
    { key: "elev", title: `Elevation (${imperial ? "ft" : "m"})`, color: "--text-dim", show: available.elevation },
    { key: "powerWatts", title: "Power (W)", color: "--accent-2", show: available.power },
    { key: "cadence", title: "Cadence", color: "--warn", show: available.cadence },
  ];

  return (
    <>
      <div className="page-head">
        <Link to="/activities" className="faint" style={{ fontSize: 13 }}>
          ← All activities
        </Link>
        {available.samples && (
          <ExportButton
            fetcher={() => api.activityExport(a.summaryId)}
            title={`Coach export · ${title}`}
            filenameBase={`coach-export-${a.summaryId}`}
            description="A compact JSON summary (aggregates, HR zones, splits, drift + a downsampled series). Paste it to your AI coach, or download it."
          />
        )}
      </div>

      <MetaBanner meta={meta} />

      {/* Hero: map banner (or gradient fallback) with title + headline stats over it */}
      <div
        className={`act-hero${available.gps ? "" : " nogps"}`}
        style={{ ["--chip" as string]: activityColor(a.activityType) }}
      >
        {available.gps && <TrackMap samples={samples} />}
        <div className="act-overlay">
          <h1>
            <span style={{ marginRight: 10 }} aria-hidden>
              {activityIcon(a.activityType)}
            </span>
            {title}
          </h1>
          <div className="sub">
            {fmtLocalDateTime(a.startLocalIso)}
            {a.deviceName ? ` · ${a.deviceName}` : ""}
            {a.manual ? " · manual entry" : ""}
          </div>
          <div className="act-hstats">
            <HeroStat k="Duration" v={fmtDuration(a.durationSeconds)} />
            {a.distanceMeters != null && <HeroStat k="Distance" v={fmtDistance(a.distanceMeters, unit)} />}
            {a.avgPaceMinPerKm != null && <HeroStat k="Avg pace" v={fmtPace(a.avgPaceMinPerKm, unit)} />}
            {a.avgHrBpm != null && <HeroStat k="Avg HR" v={`${a.avgHrBpm} bpm`} />}
          </div>
        </div>
      </div>

      {/* Summary stats */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="stat-row">
          {a.maxHrBpm != null && <Stat k="Max HR" v={`${a.maxHrBpm} bpm`} />}
          {a.avgSpeedMps != null && a.avgPaceMinPerKm == null && (
            <Stat k="Avg speed" v={fmtSpeedKmh(a.avgSpeedMps, unit)} />
          )}
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

      {(derived.hrZones || derived.splitsPerKm) && (
        <div className="grid two" style={{ marginBottom: 16 }}>
          {derived.hrZones && <ZonesCard zones={derived.hrZones} />}
          {derived.splitsPerKm && <SplitsCard splits={derived.splitsPerKm} />}
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
          {charts.filter((c) => c.show).map((c) => {
            const yAxis = valueAxis(chartSamples.map((s) => s[c.key] as number | null), c.pad ?? 0, c.clip);
            const fmtY = c.key === "pace" ? (v: number) => fmtPaceClock(v / (imperial ? 1.609344 : 1), unit) : undefined;
            return (
            <ChartCard key={c.key} title={c.title}>
              <AreaChart data={chartSamples} syncId="activity">
                <CartesianGrid stroke={cssVar("--chart-grid")} vertical={false} />
                <XAxis
                  type="number"
                  dataKey="offsetSeconds"
                  domain={xAxis.domain}
                  ticks={xAxis.ticks}
                  tickFormatter={(s) => fmtDuration(Number(s))}
                  stroke={cssVar("--text-faint")}
                  fontSize={11}
                />
                <YAxis
                  width={c.key === "pace" ? 48 : 44}
                  reversed={c.reversed}
                  stroke={cssVar("--text-faint")}
                  fontSize={11}
                  domain={yAxis.domain}
                  ticks={yAxis.ticks}
                  allowDataOverflow
                  tickFormatter={fmtY}
                />
                <defs>
                  <linearGradient id={`g-${c.key}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={cssVar(c.color)} stopOpacity={0.45} />
                    <stop offset="100%" stopColor={cssVar(c.color)} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <Area
                  type="monotone"
                  dataKey={c.key}
                  stroke={cssVar(c.color)}
                  strokeWidth={2}
                  fill={`url(#g-${c.key})`}
                  connectNulls
                  isAnimationActive={false}
                  dot={false}
                />
                <Tooltip {...tooltip()} formatter={fmtY ? (v: number) => [`${fmtY(v)} ${imperial ? "/mi" : "/km"}`, "Pace"] : undefined} />
              </AreaChart>
            </ChartCard>
            );
          })}
        </div>
      )}
    </>
  );
}

type PlotSample = Sample & { pace: number | null; elev: number | null };

// Round-tick axis; `clip` limits the domain to the 5th-95th percentile so outliers don't dominate.
function valueAxis(values: (number | null)[], pad: number, clip?: boolean) {
  const v = values.filter((x): x is number => x != null).sort((a, b) => a - b);
  if (!v.length) return { domain: ["auto", "auto"] as [string, string], ticks: undefined };
  const q = (f: number) => v[Math.min(v.length - 1, Math.floor(f * (v.length - 1)))];
  const a = niceAxis((clip ? q(0.05) : v[0]) - pad, (clip ? q(0.95) : v[v.length - 1]) + pad);
  return a;
}

function HeroStat({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <div className="k">{k}</div>
      <div className="v">{v}</div>
    </div>
  );
}

const ZONE_COLORS = ["--z1", "--z2", "--z3", "--z4", "--z5"];

function ZonesCard({ zones }: { zones: NonNullable<ActivityDetail["derived"]["hrZones"]> }) {
  return (
    <div className="card">
      <div className="card-title">
        Heart-rate zones
        <span className="faint" style={{ textTransform: "none", letterSpacing: 0 }}>
          {zones.basis === "percent_of_max_hr_estimate" ? "estimate from max HR" : "your zones"}
        </span>
      </div>
      <div className="zonebar">
        {zones.zones.map((z, i) => (
          <i key={z.zone} title={`${z.zone}: ${z.percent ?? 0}%`} style={{ width: `${z.percent ?? 0}%`, background: `var(${ZONE_COLORS[i]})` }} />
        ))}
      </div>
      <div className="zone-legend">
        {zones.zones.map((z, i) => (
          <div key={z.zone}>
            <span className="sw" style={{ background: `var(${ZONE_COLORS[i]})` }} />
            {z.zone}
            <div className="faint" style={{ marginLeft: 17 }}>
              {fmtDuration(z.seconds)} · {z.percent != null ? `${Math.round(z.percent)}%` : DASH}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SplitsCard({ splits }: { splits: NonNullable<ActivityDetail["derived"]["splitsPerKm"]> }) {
  const paces = splits.map((s) => s.paceMinPerKm).filter((p): p is number => p != null && p > 0);
  const fastest = paces.length ? Math.min(...paces) : null;
  const slowest = paces.length ? Math.max(...paces) : null;
  return (
    <div className="card">
      <div className="card-title">Km splits</div>
      <div style={{ overflowX: "auto" }}>
      <table className="table static">
        <thead>
          <tr>
            <th>Km</th>
            <th>Pace /km</th>
            <th className="num">HR</th>
            <th>&nbsp;</th>
          </tr>
        </thead>
        <tbody>
          {splits.map((s) => (
            <tr key={s.split}>
              <td>{s.distanceMeters < 950 ? `${(s.distanceMeters / 1000).toFixed(1)} km` : s.split}</td>
              <td>{fmtPace(s.paceMinPerKm, "metric")}</td>
              <td className="num">{s.avgHrBpm != null ? Math.round(s.avgHrBpm) : DASH}</td>
              <td className="pace-bar">
                {fastest != null && slowest != null && s.paceMinPerKm != null && s.paceMinPerKm > 0 && (
                  <div className="bar">
                    <i style={{ width: `${slowest === fastest ? 100 : 20 + ((slowest - s.paceMinPerKm) / (slowest - fastest)) * 80}%`, background: "var(--g-strain)" }} />
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
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
      <ChartBoundary>
        <div className="chart-wrap">
          <ResponsiveContainer width="100%" height="100%">
            {children}
          </ResponsiveContainer>
        </div>
      </ChartBoundary>
    </div>
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
