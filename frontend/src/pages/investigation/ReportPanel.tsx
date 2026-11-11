import type { Finding, InvestigationReport } from "../../api/types";

function Findings({ title, items }: { title: string; items: Finding[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <h3>{title}</h3>
      <ul>
        {items.map((f, i) => (
          <li key={i}>
            {f.claim}{" "}
            {f.evidence_ids.map((id) => <code key={id} className="pill">{id}</code>)}
          </li>
        ))}
      </ul>
    </div>
  );
}

function List({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return <div><h3>{title}</h3><ul>{items.map((t, i) => <li key={i}>{t}</li>)}</ul></div>;
}

/** Everything here is text: model and API strings are never inserted as HTML. */
export function ReportPanel({ report }: { report: InvestigationReport }) {
  return (
    <section className="panel" aria-label="Investigation report">
      <h2>Investigation report</h2>
      <div className="row">
        <span className="pill">
          {report.llm_narrative ? "Model-written narrative" : "Deterministic fallback (no model narrative)"}
        </span>
        <span className="pill">Classification: {report.classification}</span>
        <span className="pill">Confidence: {report.confidence.level}</span>
      </div>
      <p>{report.summary}</p>
      <Findings title="Model findings" items={report.model_findings} />
      <Findings title="Behavioural findings" items={report.behavioural_findings} />
      <Findings title="Graph findings" items={report.graph_findings} />
      <Findings title="Supporting evidence" items={report.supporting_evidence} />
      <Findings title="Contradictory evidence" items={report.contradictory_evidence} />
      <List title="Limitations of this assessment" items={report.confidence.limitations} />
      <List title="Missing information" items={report.missing_information} />
      <List title="Recommended next steps" items={report.recommended_next_steps} />
      <List title="Notes" items={report.notes} />
      <div className="muted">A suspicious classification is a reason for analyst review, not a confirmed outcome.</div>
    </section>
  );
}
