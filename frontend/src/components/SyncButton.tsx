import { useState } from "react";
import { api, ApiError } from "../api/client";

/**
 * Triggers a manual sync. A token is optional; when the server requires one,
 * the user can enter it and it is kept only in sessionStorage.
 */
export function SyncButton({ onDone }: { onDone?: () => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [showToken, setShowToken] = useState(false);
  const [token, setToken] = useState(() => sessionStorage.getItem("sync-token") ?? "");

  async function run() {
    setBusy(true);
    setMsg(null);
    if (token) sessionStorage.setItem("sync-token", token);
    try {
      await api.triggerSync(token, "");
      setMsg("Sync complete");
      onDone?.();
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
        setMsg("A valid sync token is required");
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
