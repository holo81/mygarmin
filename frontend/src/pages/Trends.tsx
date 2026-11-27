import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Area,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, useApi } from "../api/client";
import { MetaBanner } from "../components/MetaBanner";
import { Loading, ErrorState, EmptyState } from "../components/States";
import { cssVar } from "../lib/theme";
import { fmtDateShort, fmtHoursMinutes } from "../lib/format";
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
        <div className="pill-row">
          {RANGES.map((r) => (
            <button
              key={r.k}
              className={`pill${range === r.k ? " active" : ""}`}
              onClick={() => setRange(r.k)}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      <MetaBanner meta={data?.meta} />

      {loading ? (
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
          <TrendCard title="Resting heart rate" unit="bpm">
            <LineSeries data={data.series.restingHeartRate} color={cssVar("--bad")} />
          </TrendCard>

          <TrendCard title="HRV (last night)" unit="ms" subtitle="Shaded band = your balanced baseline">
            <HrvSeries data={data.series.hrv} />
          </TrendCard>

          <TrendCard title="Sleep duration" unit="h" subtitle="Stacked sleep stages">
            <SleepSeries data={data.series.sleepDuration} />
          </TrendCard>

          <TrendCard title="Steps" unit="">
            <BarSeries data={data.series.steps} color={cssVar("--accent")} />
          </TrendCard>

          <TrendCard title="Average stress" unit="0–100">
            <LineSeries data={data.series.stress} color={cssVar("--warn")} />
          </TrendCard>

          <TrendCard title="Intensity minutes" unit="min/day">
            <BarSeries data={data.series.intensityMinutes} color={cssVar("--accent-2")} />
          </TrendCard>
        </div>
      )}
    </>
  );
}

function hasAnySeries(series: Record<string, TrendPoint[]>): boolean {
  return Object.values(series).some((arr) => arr.some((p) => p.value != null));
}

function TrendCard({
  title,
  unit,
  subtitle,
  children,
}: {
  title: string;
  unit: string;
  subtitle?: string;
  children: React.ReactElement;
}) {
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
      <div className="chart-wrap">
        <ResponsiveContainer width="100%" height="100%">
          {children}
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function axes() {
  return (
    <>
      <CartesianGrid stroke={cssVar("--chart-grid")} vertical={false} />
      <XAxis
        dataKey="date"
        tickFormatter={fmtDateShort}
        stroke={cssVar("--text-faint")}
        fontSize={11}
        minTickGap={40}
      />
      <YAxis width={40} stroke={cssVar("--text-faint")} fontSize={11} />
    </>
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

function LineSeries({ data, color }: { data: TrendPoint[]; color: string }) {
  return (
    <ComposedChart data={data}>
      {axes()}
      <Line
        type="monotone"
        dataKey="value"
        stroke={color}
        strokeWidth={2}
        dot={false}
        connectNulls={false}
        isAnimationActive={false}
      />
      <Tooltip {...tt()} />
    </ComposedChart>
  );
}

function BarSeries({ data, color }: { data: TrendPoint[]; color: string }) {
  return (
    <BarChart data={data}>
      {axes()}
      <Bar dataKey="value" fill={color} radius={[3, 3, 0, 0]} isAnimationActive={false} />
      <Tooltip {...tt()} />
    </BarChart>
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
    <ComposedChart data={shaped}>
      {axes()}
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
        fill={cssVar("--accent")}
        fillOpacity={0.14}
        isAnimationActive={false}
      />
      <Line
        type="monotone"
        dataKey="value"
        stroke={cssVar("--accent")}
        strokeWidth={2}
        dot={false}
        connectNulls={false}
        isAnimationActive={false}
      />
      <Tooltip {...tt()} />
    </ComposedChart>
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
    <BarChart data={shaped}>
      <CartesianGrid stroke={cssVar("--chart-grid")} vertical={false} />
      <XAxis dataKey="date" tickFormatter={fmtDateShort} stroke={cssVar("--text-faint")} fontSize={11} minTickGap={40} />
      <YAxis width={40} stroke={cssVar("--text-faint")} fontSize={11} unit="h" />
      <Bar dataKey="deep" stackId="s" fill={cssVar("--accent-2")} isAnimationActive={false} />
      <Bar dataKey="light" stackId="s" fill={cssVar("--accent")} isAnimationActive={false} />
      <Bar dataKey="rem" stackId="s" fill={cssVar("--good")} isAnimationActive={false} />
      <Bar dataKey="awake" stackId="s" fill={cssVar("--text-faint")} radius={[3, 3, 0, 0]} isAnimationActive={false} />
      <Tooltip
        {...tt()}
        formatter={(v: number, name: string) => [`${v?.toFixed?.(1) ?? v} h`, name]}
      />
    </BarChart>
  );
}

function toHours(seconds: number | null): number | null {
  return seconds == null ? null : seconds / 3600;
}

void fmtHoursMinutes;
