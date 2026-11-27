// Tiny typed fetch wrapper + a useApi hook with loading/error/stale handling.
import { useCallback, useEffect, useRef, useState } from "react";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
  } catch {
    throw new ApiError(0, "Could not reach the server. Is the backend running?");
  }
  if (!resp.ok) {
    let detail = `Request failed (HTTP ${resp.status})`;
    try {
      const body = await resp.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(resp.status, detail);
  }
  return (await resp.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  overview: () => request<import("./types").Overview>("/api/overview"),
  meta: () => request<import("./types").Meta>("/api/meta"),
  activities: (qs: string) =>
    request<import("./types").ActivityList>(`/api/activities${qs}`),
  activity: (id: string) =>
    request<import("./types").ActivityDetail>(`/api/activities/${encodeURIComponent(id)}`),
  activityExport: (id: string) =>
    request<unknown>(`/api/activities/${encodeURIComponent(id)}/export`),
  healthSnapshotExport: () => request<unknown>("/api/export/health-snapshot"),
  trends: (range: string) =>
    request<import("./types").Trends>(`/api/trends?range=${range}`),
  syncStatus: () => request<import("./types").SyncStatus>("/api/sync/status"),
  triggerSync: (token: string, params = "enrich=true") =>
    request<unknown>(`/api/sync?${params}`, {
      method: "POST",
      // Only send the auth header when a token is present; an unprotected
      // server (no SYNC_API_TOKEN) accepts the request without it.
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    }),
};

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  // Keep a stable reference to the fetcher for the given deps.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const stableFetcher = useCallback(fetcher, deps);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    stableFetcher()
      .then((d) => {
        if (mounted.current) setData(d);
      })
      .catch((e: unknown) => {
        if (mounted.current) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (mounted.current) setLoading(false);
      });
  }, [stableFetcher]);

  useEffect(() => {
    mounted.current = true;
    load();
    return () => {
      mounted.current = false;
    };
  }, [load]);

  return { data, loading, error, reload: load };
}
