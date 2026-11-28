import { api, useApi } from "../api/client";
import { fmtDuration } from "../lib/format";

const WEEKS = 12;
const ymd = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

// Activity-duration buckets (minutes) -> cell level.
const level = (sec: number) => (sec <= 0 ? 0 : sec < 1800 ? 1 : sec < 3600 ? 2 : sec < 5400 ? 3 : 4);

/** GitHub-style 12-week calendar, cells colored by total activity time that day. */
export function TrainingHeatmap({ endDate }: { endDate?: string | null }) {
  const end = endDate ? new Date(`${endDate}T00:00:00`) : new Date();
  // Grid starts on the Monday WEEKS-1 weeks before the end date's week.
  const dow = (end.getDay() + 6) % 7;
  const start = new Date(end);
  start.setDate(end.getDate() - dow - (WEEKS - 1) * 7);

  const { data, loading, error } = useApi(() => api.activities(`?start=${ymd(start)}&limit=200`), [ymd(start)]);

  const secs = new Map<string, number>();
  for (const a of data?.items ?? []) {
    const day = a.startLocalIso?.slice(0, 10);
    if (day) secs.set(day, (secs.get(day) ?? 0) + (a.durationSeconds ?? 0));
  }

  const cells = Array.from({ length: WEEKS * 7 }, (_, i) => {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    return { key: ymd(d), future: d > end, d };
  });

  return (
    <div className="card">
      <div className="card-title">Training · last {WEEKS} weeks</div>
      {error ? (
        <div className="faint">Could not load activities.</div>
      ) : loading ? (
        <div className="skeleton" style={{ height: 110 }} />
      ) : (
        <>
          <div className="heat-wrap">
            <div className="heat-days" aria-hidden>
              {["Mon", "", "Wed", "", "Fri", "", "Sun"].map((d, i) => (
                <span key={i}>{d}</span>
              ))}
            </div>
            <div>
          <div className="heat-months" style={{ gridTemplateColumns: `repeat(${WEEKS}, 1fr)` }} aria-hidden>
            {Array.from({ length: WEEKS }, (_, w) => {
              const first = cells[w * 7].d;
              const prev = w > 0 ? cells[w * 7 - 7].d : null;
              return (
                <span key={w}>
                  {!prev || prev.getMonth() !== first.getMonth()
                    ? first.toLocaleDateString(undefined, { month: "short" })
                    : ""}
                </span>
              );
            })}
          </div>
          <div className="heat" style={{ gridTemplateColumns: `repeat(${WEEKS}, 1fr)` }}>
            {cells.map((c) => {
              const s = secs.get(c.key) ?? 0;
              const label = `${c.d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}: ${
                s > 0 ? fmtDuration(s) : "no activity"
              }`;
              return (
                <div
                  key={c.key}
                  className={`heat-cell l${level(s)}${c.future ? " future" : ""}`}
                  title={label}
                  aria-label={label}
                />
              );
            })}
          </div>
            </div>
          </div>
          <div className="heat-legend">
            Less
            {[0, 1, 2, 3, 4].map((l) => (
              <span key={l} className={`heat-cell l${l}`} />
            ))}
            More
          </div>
        </>
      )}
    </div>
  );
}
