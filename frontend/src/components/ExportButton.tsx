import { useState } from "react";

/**
 * Generic "export JSON for an AI coach" button. Fetches a JSON payload, shows a
 * preview, and offers copy-to-clipboard + download. Reused for the per-activity
 * export and the daily health snapshot.
 */
export function ExportButton({
  fetcher,
  title,
  label = "🤖 Export for AI coach",
  filenameBase = "export",
  description = "A compact JSON summary for an AI coach. Paste it to your assistant, or download it.",
}: {
  fetcher: () => Promise<unknown>;
  title: string;
  label?: string;
  filenameBase?: string;
  description?: string;
}) {
  const [open, setOpen] = useState(false);
  const [json, setJson] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function load() {
    setOpen(true);
    if (json || loading) return;
    setLoading(true);
    setError(null);
    try {
      const data = await fetcher();
      setJson(JSON.stringify(data, null, 2));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    } finally {
      setLoading(false);
    }
  }

  async function copy() {
    if (!json) return;
    try {
      await navigator.clipboard.writeText(json);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Clipboard not available — use Download instead.");
    }
  }

  function download() {
    if (!json) return;
    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const safe = filenameBase.replace(/[^a-z0-9]+/gi, "-").toLowerCase() || "export";
    a.href = url;
    a.download = `${safe}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <>
      <button className="btn" onClick={load}>
        {label}
      </button>

      {open && (
        <div
          role="dialog"
          aria-modal="true"
          onClick={() => setOpen(false)}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.55)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 100,
            padding: 20,
          }}
        >
          <div
            className="card"
            onClick={(e) => e.stopPropagation()}
            style={{ width: "min(760px, 100%)", maxHeight: "85vh", display: "flex", flexDirection: "column" }}
          >
            <div
              className="card-title"
              style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}
            >
              <span>{title}</span>
              <button className="btn ghost" onClick={() => setOpen(false)}>
                ✕
              </button>
            </div>

            <div style={{ fontSize: 12.5, color: "var(--text-dim)", marginBottom: 10 }}>
              {description}
            </div>

            {loading ? (
              <div className="state">
                <div className="spinner" />
                <div>Building export…</div>
              </div>
            ) : error ? (
              <div className="banner error">{error}</div>
            ) : (
              <>
                <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
                  <button className="btn primary" onClick={copy}>
                    {copied ? "✓ Copied" : "Copy to clipboard"}
                  </button>
                  <button className="btn" onClick={download}>
                    Download .json
                  </button>
                </div>
                <pre
                  style={{
                    flex: 1,
                    overflow: "auto",
                    background: "var(--bg)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius-sm)",
                    padding: 12,
                    margin: 0,
                    fontFamily: "var(--mono)",
                    fontSize: 11.5,
                    lineHeight: 1.45,
                    whiteSpace: "pre",
                  }}
                >
                  {json}
                </pre>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
