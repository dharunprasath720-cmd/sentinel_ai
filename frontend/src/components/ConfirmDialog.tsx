import type { ReactNode } from "react";

export function ConfirmDialog(props: {
  open: boolean; title: string; children: ReactNode; confirmLabel: string;
  onConfirm: () => void; onCancel: () => void;
}) {
  if (!props.open) return null;
  return (
    <div className="overlay">
      <div role="dialog" aria-modal="true" aria-label={props.title} className="panel dialog">
        <h3>{props.title}</h3>
        <div>{props.children}</div>
        <div className="row">
          <button className="btn" onClick={props.onCancel}>Cancel</button>
          <button className="btn btn-primary" onClick={props.onConfirm}>{props.confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}
