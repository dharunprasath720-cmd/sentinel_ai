import { useState } from "react";
import { ApiError } from "../api/client";
import type { ChatResult } from "../api/types";
import { canAct } from "../auth/roles";
import { useSession } from "../auth/session";

const MAX_CHARS = 8000;   // the server's per-message limit
const MAX_MESSAGES = 40;  // the server's per-conversation limit

interface Turn { role: "user" | "assistant"; content: string; result?: ChatResult }

const NOTICE: Partial<Record<ChatResult["status"], string>> = {
  refused: "The model declined to answer this question.",
  truncated: "The reply was cut off before it finished. Try a narrower question.",
  iteration_limit: "The investigator needed too many steps and stopped. Try a narrower question.",
};

function Reply({ turn }: { turn: Turn }) {
  const r = turn.result;
  if (!r) return <div className="panel"><strong>You</strong><div style={{ whiteSpace: "pre-wrap" }}>{turn.content}</div></div>;
  const tools = [...new Set(r.tool_calls.map((c) => c.name))];
  return (
    <div className="panel">
      <strong>Investigator</strong>
      {r.status === "withheld" ? (
        <div role="note" className="muted">
          This reply was withheld: it {r.withheld_reasons.join(" and ") || "broke a safety rule"}. The investigator may
          only describe evidence; analysts decide what is fraud and what action is taken.
        </div>
      ) : (
        <>
          {r.text ? <div style={{ whiteSpace: "pre-wrap" }}>{r.text}</div> : null}
          {NOTICE[r.status] ? <div role="note" className="muted">{NOTICE[r.status]}</div> : null}
        </>
      )}
      {r.verified_citations.length ? (
        <div className="row muted">Evidence: {r.verified_citations.map((c) => <code key={c} className="pill">{c}</code>)}</div>
      ) : null}
      {r.unverified_citations.length ? (
        <div className="row muted">Cited but not retrieved this turn (treat with caution):{" "}
          {r.unverified_citations.map((c) => <code key={c} className="pill">{c}</code>)}</div>
      ) : null}
      {tools.length ? <div className="muted">Looked up: {tools.join(", ")}</div> : null}
    </div>
  );
}

export function Investigator() {
  const { client, role } = useSession();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!canAct(role)) {
    return <div className="grid"><h1>AI Investigator</h1>
      <div className="panel muted">The AI investigator is available to analysts and admins.</div></div>;
  }

  async function send() {
    const text = input.trim();
    if (!text) return;
    if (text.length > MAX_CHARS) return setError(`A message can be at most ${MAX_CHARS} characters.`);
    if (turns.length + 1 > MAX_MESSAGES) return setError("This conversation is full. Start a new conversation.");
    setBusy(true); setError(null);
    const messages = [...turns, { role: "user" as const, content: text }].map(({ role, content }) => ({ role, content }));
    try {
      const result = await client.post<ChatResult>("/agent/chat", { messages });
      setTurns((t) => [...t, { role: "user", content: text },
        { role: "assistant", content: result.text || "(no answer was produced)", result }]);
      setInput("");
    } catch (err) {
      setError(err instanceof ApiError
        ? err.status === 503 ? "No language model is configured, so chat is unavailable."
        : err.status === 502 ? "The language model request failed. Try again."
        : err.detail
        : "The request failed. Try again.");
    } finally { setBusy(false); }
  }

  return (
    <div className="grid">
      <div className="row">
        <h1>AI Investigator</h1>
        <button className="btn" onClick={() => { setTurns([]); setError(null); }}>New conversation</button>
      </div>
      <div className="muted">Answers come only from retrieved evidence and are for analyst review. The investigator
        never decides that something is fraud and never takes an action.</div>
      {turns.map((t, i) => <Reply key={i} turn={t} />)}
      {error ? <div role="alert" className="panel error">{error}</div> : null}
      <form className="grid" onSubmit={(e) => { e.preventDefault(); void send(); }}>
        <label>Your question
          <textarea rows={3} value={input} onChange={(e) => setInput(e.target.value)} style={{ width: "100%" }} />
        </label>
        <div className="row">
          <button className="btn btn-primary" disabled={busy || !input.trim()}>Send</button>
          <span className="muted">{input.length} / {MAX_CHARS}</span>
          {busy ? <span role="status" className="muted">Investigating…</span> : null}
        </div>
      </form>
    </div>
  );
}
