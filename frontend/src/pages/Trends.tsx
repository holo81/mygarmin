import { useId, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Area,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, useApi } from "../api/client";
import { MetaBanner } from "../components/MetaBanner";
import { ChartBoundary } from "../components/ChartBoundary";
import { Loading, ErrorState, EmptyState } from "../components/States";
import { cssVar } from "../lib/theme";
import { niceAxis } from "../lib/chart";
import { fmtDateShort, fmtHoursMinutes, fmtInt, fmtNum } from "../lib/format";
import type { TrendPoint } from "../api/types";

const RANGES = [
  { k: "7d", label: "7 days" },
  { k: "30d", label: "30 days" },
  { k: "90d", label: "90 days" },
  { k: "all", label: "All" },
];

export function TrendsPage() {
  const [range, setRange] = useState("30d");
  const { data, loading, error, reload } = useApi(() => api.trends(range), [range]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Health trends</h1>
          <div className="page-sub">
            Compare metrics over time. Gaps indicate days without recorded data.
          </div>
        </div>
        <div className="seg" role="group" aria-label="Range">
          {RANGES.map((r) => (
            <button
              key={r.k}
              className={range === r.k ? "active" : ""}
              aria-pressed={range === r.k}
              onClick={() => setRange(r.k)}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      <MetaBanner meta={data?.meta} />

      {loading && !data ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : !data || !hasAnySeries(data.series) ? (
        <EmptyState
          icon="📈"
          title="No trend data"
          hint="Sync some history to see trends. The Personal API supports historical retrieval for the days your device recorded data."
        />
      ) : (
        <div className="grid two">
          <TrendCard title="Resting heart rate" unit="bpm" data={data.series.restingHeartRate}>
            <LineSeries data={data.series.restingHeartRate} color={cssVar("--hrt-a")} yScale="auto" />
          </TrendCard>

          <TrendCard title="HRV (last night)" unit="ms" subtitle="Shaded band = your balanced baseline" data={data.series.hrv}>
            <HrvSeries data={data.series.hrv} />
          </TrendCard>

          <TrendCard title="Sleep duration" unit="h" subtitle="Stacked sleep stages" data={data.series.sleepDuration} fmt={fmtHoursMinutes}>
            <SleepSeries data={data.series.sleepDuration} />
          </TrendCard>

          <TrendCard title="Steps" unit="" data={data.series.steps} fmt={fmtInt}>
            <BarSeries data={data.series.steps} color={cssVar("--rec-b")} />
          </TrendCard>

          <TrendCard title="Average stress" unit="0–100" data={data.series.stress}>
            <LineSeries data={data.series.stress} color={cssVar("--str-a")} />
          </TrendCard>

          <TrendCard title="Intensity minutes" unit="min/day" data={data.series.intensityMinutes}>
            <BarSeries data={data.series.intensityMinutes} color={cssVar("--slp-a")} />
          </TrendCard>

          {data.series.weight.some((p) => p.value != null) && (
            <TrendCard title="Weight" unit="kg" subtitle="Each logged measurement" data={data.series.weight} fmt={(n) => fmtNum(n, 1)}>
              <LineSeries data={data.series.weight} color={cssVar("--rec-a")} yScale="auto" decimals={1} />
            </TrendCard>
          )}
        </div>
      )}
    </>
  );
}

function hasAnySeries(series: Record<string, TrendPoint[]>): boolean {
  return Object.values(series).some((arr) => arr.some((p) => p.value != null));
}

/** avg / min / max plus change of the 2nd half of the range vs the 1st half. */
function summarise(data: TrendPoint[]) {
  const v = data.map((p) => p.value).filter((x): x is number => x != null);
  if (v.length === 0) return null;
  const avg = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;
  const half = Math.floor(v.length / 2);
  const delta =
    v.length >= 4 && avg(v.slice(0, half)) !== 0
      ? ((avg(v.slice(half)) - avg(v.slice(0, half))) / avg(v.slice(0, half))) * 100
      : null;
  return { avg: avg(v), min: Math.min(...v), max: Math.max(...v), delta };
}

function TrendCard({
  title,
  unit,
  subtitle,
  data,
  fmt = fmtNum.bind(null) as (n: number) => string,
  children,
}: {
  title: string;
  unit: string;
  subtitle?: string;
  data: TrendPoint[];
  fmt?: (n: number) => string;
  children: React.ReactElement;
}) {
  const st = summarise(data);
  return (
    <div className="card">
      <div className="card-title">
        <span>
          {title} {unit && <span className="faint">· {unit}</span>}
        </span>
      </div>
      {subtitle && (
        <div className="faint" style={{ fontSize: 12, marginTop: -6, marginBottom: 8 }}>
          {subtitle}
        </div>
      )}
      <div className="chips">
        {st ? (
          <>
            <span className="sum-chip">avg <b>{fmt(st.avg)}</b></span>
            <span className="sum-chip">min <b>{fmt(st.min)}</b></span>
            <span className="sum-chip">max <b>{fmt(st.max)}</b></span>
            {st.delta != null && (
              <span className="sum-chip" title="Average of the second half of the range vs the first half">
                <b>{Math.abs(st.delta) < 1 ? "→" : st.delta > 0 ? "▲" : "▼"} {Math.abs(st.delta).toFixed(0)}%</b> vs first half
              </span>
            )}
          </>
        ) : (
          <span className="sum-chip">No data</span>
        )}
      </div>
      <ChartBoundary>
        <div style={{ width: "100%", height: 260 }}>{children}</div>
      </ChartBoundary>
    </div>
  );
}

const tt = () => ({
  contentStyle: {
    background: cssVar("--bg-elev-2"),
    border: `1px solid ${cssVar("--border-strong")}`,
    borderRadius: 8,
    fontSize: 12,
  },
  labelFormatter: (d: string) => fmtDateShort(d),
});

function LineSeries({
  data,
  color,
  // "auto" = fit the data range (don't force 0); "zero" = start at 0.
  yScale = "auto",
  decimals = 0,
}: {
  data: TrendPoint[];
  color: string;
  yScale?: "auto" | "zero";
  decimals?: number;
}) {
  const gid = useId().replace(/:/g, "");
  const axis = yScale === "auto" ? paddedAxis(data) : null;
  const domain = (axis?.domain ?? [0, "auto"]) as [number | string, number | string];
  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart data={data}>
        <CartesianGrid stroke={cssVar("--chart-grid")} vertical={false} />
        <XAxis dataKey="date" tickFormatter={fmtDateShort} stroke={cssVar("--text-faint")} fontSize={11} minTickGap={40} />
        <YAxis
          width={44}
          stroke={cssVar("--text-faint")}
          fontSize={11}
          domain={domain}
          ticks={axis?.ticks}
          allowDecimals={decimals > 0}
          tickFormatter={(v: number) => v.toFixed(decimals)}
        />
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.4} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          type="monotone"
          dataKey="value"
          stroke={color}
          strokeWidth={2.5}
          fill={`url(#${gid})`}
          dot={false}
          isAnimationActive={false}
        />
        <Tooltip {...tt()} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

/**
 * Compute a Y domain that fits the data with a little padding, so metrics like
 * resting HR (which never approach 0) use the full chart height instead of
 * being squashed against the top. Returns null when no data.
 */
function paddedAxis(data: TrendPoint[]): { domain: [number, number]; ticks: number[] } | null {
  const vals = data.map((p) => p.value).filter((v): v is number => v != null);
  if (vals.length === 0) return null;
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const pad = (max - min) * 0.12;
  return niceAxis(min - pad, max + pad);
}

function BarSeries({ data, color }: { data: TrendPoint[]; color: string }) {
  const gid = useId().replace(/:/g, "");
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data}>
        <CartesianGrid stroke={cssVar("--chart-grid")} vertical={false} />
        <XAxis dataKey="date" tickFormatter={fmtDateShort} stroke={cssVar("--text-faint")} fontSize={11} minTickGap={40} />
        <YAxis width={40} stroke={cssVar("--text-faint")} fontSize={11} />
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={1} />
            <stop offset="100%" stopColor={color} stopOpacity={0.35} />
          </linearGradient>
        </defs>
        <Bar dataKey="value" fill={`url(#${gid})`} radius={[3, 3, 0, 0]} isAnimationActive={false} />
        <Tooltip {...tt()} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function HrvSeries({ data }: { data: TrendPoint[] }) {
  // Represent the balanced baseline band as an area between low and high.
  const shaped = data.map((p) => ({
    date: p.date,
    value: p.value,
    low: p.baselineLow as number | null,
    band:
      p.baselineHigh != null && p.baselineLow != null
        ? (p.baselineHigh as number) - (p.baselineLow as number)
        : null,
  }));
  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart data={shaped}>
        <CartesianGrid stroke={cssVar("--chart-grid")} vertical={false} />
        <XAxis dataKey="date" tickFormatter={fmtDateShort} stroke={cssVar("--text-faint")} fontSize={11} minTickGap={40} />
        <YAxis width={40} stroke={cssVar("--text-faint")} fontSize={11} />
        <Area
          dataKey="low"
          stackId="band"
          stroke="none"
          fill="transparent"
          isAnimationActive={false}
        />
        <Area
          dataKey="band"
          stackId="band"
          stroke="none"
          fill={cssVar("--slp-a")}
          fillOpacity={0.16}
          isAnimationActive={false}
        />
        <Line
          type="monotone"
          dataKey="value"
          stroke={cssVar("--slp-a")}
          strokeWidth={2.5}
          dot={false}
          connectNulls={false}
          isAnimationActive={false}
        />
        <Tooltip {...tt()} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

function SleepSeries({ data }: { data: TrendPoint[] }) {
  // Convert seconds to hours for readability; keep stages stacked.
  const shaped = data.map((p) => ({
    date: p.date,
    deep: toHours(p.deep as number | null),
    light: toHours(p.light as number | null),
    rem: toHours(p.rem as number | null),
    awake: toHours(p.awake as number | null),
  }));
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={shaped}>
        <CartesianGrid stroke={cssVar("--chart-grid")} vertical={false} />
        <XAxis dataKey="date" tickFormatter={fmtDateShort} stroke={cssVar("--text-faint")} fontSize={11} minTickGap={40} />
        <YAxis width={40} stroke={cssVar("--text-faint")} fontSize={11} unit="h" />
        <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: 12 }} />
        <Bar name="Deep" dataKey="deep" stackId="s" fill={cssVar("--accent-2")} isAnimationActive={false} />
        <Bar name="Light" dataKey="light" stackId="s" fill={cssVar("--accent")} isAnimationActive={false} />
        <Bar name="REM" dataKey="rem" stackId="s" fill={cssVar("--good")} isAnimationActive={false} />
        <Bar name="Awake" dataKey="awake" stackId="s" fill={cssVar("--text-faint")} radius={[3, 3, 0, 0]} isAnimationActive={false} />
        <Tooltip
          {...tt()}
          formatter={(v: number, name: string) => [`${v?.toFixed?.(1) ?? v} h`, name]}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}

function toHours(seconds: number | null): number | null {
  return seconds == null ? null : seconds / 3600;
}

