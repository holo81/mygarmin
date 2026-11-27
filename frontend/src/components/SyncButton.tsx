import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { SyncRun } from "../api/types";
import { timeAgo } from "../lib/format";

/** Polls /api/meta; calls onNew when a sync (e.g. the backend's auto sync) lands. */
function useLastSync(onNew?: () => void): SyncRun | null {
  const [last, setLast] = useState<SyncRun | null>(null);
  const seen = useRef<number | null>(null);
  useEffect(() => {
    const poll = () =>
      api.meta().then((m) => {
        const run = m.lastSync;
        if (run?.finished_at && seen.current !== null && run.id !== seen.current) onNew?.();
        if (run?.finished_at) seen.current = run.id;
        setLast(run);
      }, () => {});
    poll();
    const t = setInterval(poll, 30_000); // also re-renders the "x min ago" label
    return () => clearInterval(t);
  }, []);
  return last;
}

/**
 * Triggers a manual sync. If the server has SYNC_API_TOKEN set, the sync is
 * protected and the user is prompted for the token (stored only in
 * sessionStorage, never bundled). If the server has no token configured
 * (typical localhost setup), sync just works with no prompt.
 */
export function SyncButton({ onDone }: { onDone?: () => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [showToken, setShowToken] = useState(false);
  const [token, setToken] = useState(() => sessionStorage.getItem("sync-token") ?? "");
  const last = useLastSync(onDone);
  const failed = last?.finished_at && !["success", "partial"].includes(last.status);

  async function run() {
    setBusy(true);
    setMsg(null);
    if (token) sessionStorage.setItem("sync-token", token);
    try {
      // Try with whatever token we have (possibly empty). If the server is
      // unprotected, an empty token succeeds; otherwise it returns 401/403 and
      // we reveal the token field.
      await api.triggerSync(token, "enrich=true");
      setMsg("Sync complete");
      setShowToken(false);
      onDone?.();
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
        setMsg(token ? "Invalid sync token" : "This server requires a sync token");
        setShowToken(true);
      } else if (e instanceof ApiError && e.status === 409) {
        setMsg("A sync is already running");
      } else {
        setMsg(e instanceof Error ? e.message : "Sync failed");
      }
    } finally {
      setBusy(false);
      setTimeout(() => setMsg(null), 4000);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <button className="btn primary" disabled={busy} onClick={run}>
        {busy ? "Syncing…" : "⟳ Sync now"}
      </button>
      {last && (
        <div
          className="faint"
          style={{ fontSize: 11, textAlign: "center", color: failed ? "var(--bad)" : undefined }}
          title={last.finished_at ? new Date(last.finished_at).toLocaleString() : "In progress"}
        >
          {last.finished_at
            ? `${failed ? "Last sync failed" : "Synced"} ${timeAgo(last.finished_at)}`
            : "Syncing in background…"}
        </div>
      )}
      {showToken && (
        <input
          className="input"
          type="password"
          placeholder="Sync token"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
          autoFocus
        />
      )}
      {msg && <div className="faint" style={{ fontSize: 12 }}>{msg}</div>}
    </div>
  );
}
