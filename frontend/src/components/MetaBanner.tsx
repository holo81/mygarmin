import type { Meta } from "../api/types";
import { timeAgo } from "../lib/format";

/** Surfaces mock-data and stale-data conditions without hiding the dashboard. */
export function MetaBanner({ meta }: { meta: Meta | undefined }) {
  if (!meta) return null;
  const lastAt = meta.lastSync?.finished_at ?? meta.lastSync?.started_at ?? null;
  return (
    <>
      {meta.dataSource === "mock" && (
        <div className="banner mock">
          <span aria-hidden>🧪</span>
          <span>
            <strong>Mock data</strong> — these are development fixtures, not real
            Garmin data. Set <code>APP_ENV=production</code> and sync to show real data.
          </span>
        </div>
      )}
      {meta.isStale && meta.dataSource !== "mock" && (
        <div className="banner stale">
          <span aria-hidden>⏳</span>
          <span>
            Data may be stale — last successful sync {timeAgo(lastAt)}. Run a sync to
            refresh.
          </span>
        </div>
      )}
      {meta.lastSync?.status === "failed" && (
        <div className="banner error">
          <span aria-hidden>⚠️</span>
          <span>
            Last sync failed: {meta.lastSync.message || "unknown error"}. Showing the
            most recent stored data.
          </span>
        </div>
      )}
    </>
  );
}
