import type { ReactNode } from "react";
import { Area, AreaChart, ResponsiveContainer, YAxis } from "recharts";
import { DASH } from "../lib/format";

interface SparkPoint {
  v: number | null;
}

/**
 * A single headline metric. Renders a clear "No data" state (distinct from zero)
 * when `value` is null, and an optional sparkline trend when enough points exist.
 */
export function MetricCard({
  label,
  icon,
  value,
  unit,
  sub,
  spark,
  accent = "var(--accent)",
}: {
  label: string;
  icon?: ReactNode;
  value: string | number | null;
  unit?: string;
  sub?: ReactNode;
  spark?: (number | null)[];
  accent?: string;
}) {
  const gid = `sg-${label.replace(/\W/g, "")}`;
  const noData = value === null || value === undefined || value === DASH;
  const sparkData: SparkPoint[] = (spark ?? []).map((v) => ({ v }));
  const validSpark = sparkData.filter((p) => p.v !== null);
  const showSpark = validSpark.length >= 3;

  return (
    <div className={`card metric${noData ? " nodata" : ""}`}>
      <div className="label">
        {icon && (
          <span className="chip-ico" style={{ ["--chip" as string]: accent }} aria-hidden>
            {icon}
          </span>
        )}
        {label}
      </div>
      {noData ? (
        <div className="value">No data</div>
      ) : (
        <div className="value">
          {value}
          {unit && <span className="unit">{unit}</span>}
        </div>
      )}
      {sub && <div className="sub">{sub}</div>}
      {showSpark && (
        <div className="spark">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={sparkData} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={accent} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={accent} stopOpacity={0} />
                </linearGradient>
              </defs>
              <YAxis hide domain={["dataMin", "dataMax"]} />
              <Area
                type="monotone"
                dataKey="v"
                stroke={accent}
                strokeWidth={2}
                fill={`url(#${gid})`}
                connectNulls
                isAnimationActive={false}
                dot={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
