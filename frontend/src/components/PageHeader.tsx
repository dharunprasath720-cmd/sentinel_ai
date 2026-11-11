import type { ReactNode } from "react";

/** One consistent title block for every page: heading, one-line subtitle, optional actions on the right. */
export function PageHeader({ title, subtitle, children }: { title: string; subtitle?: string; children?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle ? <div className="page-subtitle">{subtitle}</div> : null}
      </div>
      {children ? <div className="row">{children}</div> : null}
    </header>
  );
}
