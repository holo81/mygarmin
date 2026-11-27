import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, useApi } from "../api/client";
import { MetaBanner } from "../components/MetaBanner";
import { Loading, ErrorState, EmptyState } from "../components/States";
import {
  activityIcon,
  activityTypeLabel,
  DASH,
  fmtDistance,
  fmtDuration,
  fmtInt,
  fmtLocalDateTime,
  fmtPace,
} from "../lib/format";

const PAGE_SIZE = 25;

export function ActivitiesPage() {
  const nav = useNavigate();
  const [type, setType] = useState("");
  const [search, setSearch] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [page, setPage] = useState(0);

  const qs = useMemo(() => {
    const p = new URLSearchParams();
    p.set("limit", String(PAGE_SIZE));
    p.set("offset", String(page * PAGE_SIZE));
    if (type) p.set("type", type);
    if (search) p.set("search", search);
    if (start) p.set("start", start);
    if (end) p.set("end", end);
    return `?${p.toString()}`;
  }, [type, search, start, end, page]);

  const { data, loading, error, reload } = useApi(() => api.activities(qs), [qs]);
  const unit = data?.meta.unitSystem ?? "metric";

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Activities</h1>
          <div className="page-sub">
            {data ? `${data.total} activities` : "Your recorded activities"}
          </div>
        </div>
      </div>

      <MetaBanner meta={data?.meta} />

      <div
        className="card"
        style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 16 }}
      >
        <input
          className="input"
          placeholder="Search name or type…"
          value={search}
          onChange={(e) => {
            setPage(0);
            setSearch(e.target.value);
          }}
          style={{ flex: "1 1 220px" }}
        />
        <select
          className="select"
          value={type}
          onChange={(e) => {
            setPage(0);
            setType(e.target.value);
          }}
        >
          <option value="">All types</option>
          {(data?.activityTypes ?? []).map((t) => (
            <option key={t} value={t}>
              {activityTypeLabel(t)}
            </option>
          ))}
        </select>
        <label className="faint" style={{ fontSize: 12 }}>
          From{" "}
          <input
            className="input"
            type="date"
            value={start}
            onChange={(e) => {
              setPage(0);
              setStart(e.target.value);
            }}
          />
        </label>
        <label className="faint" style={{ fontSize: 12 }}>
          To{" "}
          <input
            className="input"
            type="date"
            value={end}
            onChange={(e) => {
              setPage(0);
              setEnd(e.target.value);
            }}
          />
        </label>
        {(type || search || start || end) && (
          <button
            className="btn ghost"
            onClick={() => {
              setType("");
              setSearch("");
              setStart("");
              setEnd("");
              setPage(0);
            }}
          >
            Clear
          </button>
        )}
      </div>

      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : !data || data.items.length === 0 ? (
        <EmptyState
          icon="🏃"
          title="No activities match"
          hint="Try clearing filters, or run a sync to import activity data."
        />
      ) : (
        <div className="card" style={{ padding: 0, overflowX: "auto" }}>
          <table className="table">
            <thead>
              <tr>
                <th>Activity</th>
                <th>Date</th>
                <th className="num">Duration</th>
                <th className="num">Distance</th>
                <th className="num">Pace / Speed</th>
                <th className="num">Avg HR</th>
                <th className="num">Elev gain</th>
                <th className="num">Calories</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((a) => (
                <tr
                  key={a.summaryId}
                  onClick={() => nav(`/activities/${encodeURIComponent(a.summaryId)}`)}
                >
                  <td>
                    <span style={{ marginRight: 8 }} aria-hidden>
                      {activityIcon(a.activityType)}
                    </span>
                    <strong>{a.activityName || activityTypeLabel(a.activityType)}</strong>
                  </td>
                  <td className="dim">{fmtLocalDateTime(a.startLocalIso)}</td>
                  <td className="num">{fmtDuration(a.durationSeconds)}</td>
                  <td className="num">
                    {a.distanceMeters != null ? fmtDistance(a.distanceMeters, unit) : DASH}
                  </td>
                  <td className="num">
                    {a.avgPaceMinPerKm != null ? fmtPace(a.avgPaceMinPerKm, unit) : DASH}
                  </td>
                  <td className="num">{a.avgHrBpm != null ? `${a.avgHrBpm}` : DASH}</td>
                  <td className="num">
                    {a.totalElevationGainM != null ? `${Math.round(a.totalElevationGainM)} m` : DASH}
                  </td>
                  <td className="num">{fmtInt(a.activeKilocalories)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && data.total > PAGE_SIZE && (
        <div style={{ display: "flex", gap: 10, justifyContent: "center", marginTop: 18, alignItems: "center" }}>
          <button className="btn" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
            ← Prev
          </button>
          <span className="faint" style={{ fontSize: 13 }}>
            Page {page + 1} of {totalPages}
          </span>
          <button
            className="btn"
            disabled={page + 1 >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            Next →
          </button>
        </div>
      )}
    </>
  );
}
