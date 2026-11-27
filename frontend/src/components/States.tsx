import type { ReactNode } from "react";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="state">
      <div className="spinner" />
      <div>{label}</div>
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="state">
      <div className="big">⚠️</div>
      <div style={{ maxWidth: 440 }}>{message}</div>
      {onRetry && (
        <button className="btn" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  icon = "🗂️",
  children,
}: {
  title: string;
  hint?: string;
  icon?: string;
  children?: ReactNode;
}) {
  return (
    <div className="state">
      <div className="big">{icon}</div>
      <div style={{ fontWeight: 600, color: "var(--text)" }}>{title}</div>
      {hint && <div style={{ maxWidth: 460 }}>{hint}</div>}
      {children}
    </div>
  );
}

export function CardSkeleton({ height = 120 }: { height?: number }) {
  return <div className="skeleton" style={{ height }} />;
}
