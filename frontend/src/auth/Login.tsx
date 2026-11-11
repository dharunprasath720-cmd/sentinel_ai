import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useSession } from "./session";

export function Login() {
  const { token, login } = useSession();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (token) return <Navigate to="/" replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try { await login(username, password); }
    catch (err) { setError(err instanceof ApiError ? err.detail : "Could not sign in"); }
    finally { setBusy(false); }
  }

  return (
    <form className="panel login" onSubmit={submit}>
      <h1>SENTINEL</h1>
      <div className="muted">Payment-fraud intelligence. Sign in to continue.</div>
      <label>Username<input autoFocus value={username} onChange={(e) => setUsername(e.target.value)} required /></label>
      <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
      {error ? <div role="alert" className="muted">{error}</div> : null}
      <button className="btn btn-primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
    </form>
  );
}
