import { ApiError } from "../api/client";

export function Spinner({ label = "Loading" }: { label?: string }) {
  return <div role="status" className="muted">{label}…</div>;
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="panel empty">
      <strong>{title}</strong>
      {hint ? <div className="muted">{hint}</div> : null}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof ApiError ? error.detail : error instanceof Error ? error.message : "Something went wrong";
  return (
    <div role="alert" className="panel error">
      <strong>Could not load this</strong>
      <div>{message}</div>
      {onRetry ? <button className="btn" onClick={onRetry}>Retry</button> : null}
    </div>
  );
}
