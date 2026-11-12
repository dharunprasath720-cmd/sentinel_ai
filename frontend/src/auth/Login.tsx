import { motion, useReducedMotion } from "framer-motion";
import { Eye, EyeOff, Network, ScanSearch, ShieldCheck, UserCheck } from "lucide-react";
import { useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Navigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useSession } from "./session";

const DEMO_USERS = [
  { name: "ana", role: "analyst" },
  { name: "vic", role: "viewer" },
  { name: "adm", role: "admin" },
];
const POINTS = [
  { icon: ScanSearch, text: "Scores every payment as it arrives" },
  { icon: Network, text: "Explains each decision with the evidence behind it" },
  { icon: UserCheck, text: "Analysts decide: nothing is blocked automatically" },
];

export function Login() {
  const { token, login } = useSession();
  const reduceMotion = useReducedMotion();
  const passwordRef = useRef<HTMLInputElement>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
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
  const watchCaps = (e: KeyboardEvent<HTMLInputElement>) => setCapsLock(e.getModifierState("CapsLock"));

  return (
    <div className="login-page">
      <section className="login-hero" aria-label="About SENTINEL">
        <motion.div initial={reduceMotion ? false : { opacity: 0, x: -16 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.35, ease: [0.23, 1, 0.32, 1] }}>
          <div className="login-mark" aria-hidden><ShieldCheck size={34} /></div>
          <h1>SENTINEL</h1>
          <p className="login-sub">Payment-fraud intelligence</p>
          <ul className="login-points">
            {POINTS.map(({ icon: Icon, text }) => (
              <li key={text}><Icon size={18} aria-hidden /> <span>{text}</span></li>
            ))}
          </ul>
        </motion.div>
        <div className="login-glow" aria-hidden />
      </section>

      <motion.form className="login-card" onSubmit={submit} aria-labelledby="login-title"
                   initial={reduceMotion ? false : { opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, delay: 0.06, ease: [0.23, 1, 0.32, 1] }}>
        <h2 id="login-title">Sign in</h2>
        <div className="field">
          <label htmlFor="login-username">Username</label>
          <input id="login-username" autoFocus autoComplete="username" value={username}
                 onChange={(e) => setUsername(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="login-password">Password</label>
          <div className="input-group">
            <input id="login-password" ref={passwordRef} type={showPassword ? "text" : "password"} autoComplete="current-password"
                   value={password} onChange={(e) => setPassword(e.target.value)} onKeyDown={watchCaps} onKeyUp={watchCaps}
                   onBlur={() => setCapsLock(false)} required />
            <button type="button" className="icon-btn" aria-label={showPassword ? "Hide password" : "Show password"}
                    aria-pressed={showPassword} onClick={() => setShowPassword((s) => !s)}>
              {showPassword ? <EyeOff size={18} aria-hidden /> : <Eye size={18} aria-hidden />}
            </button>
          </div>
          {capsLock ? <div className="hint" role="status">Caps Lock is on</div> : null}
        </div>
        {error ? <div role="alert" className="form-error">{error}</div> : null}
        <button className="btn btn-primary btn-wide" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        <div className="demo-users">
          <span className="muted">Demo accounts</span>
          <div className="row">
            {DEMO_USERS.map((u) => (
              <button type="button" key={u.name} className="chip"
                      onClick={() => { setUsername(u.name); passwordRef.current?.focus(); }}>
                {u.name} <span className="muted">{u.role}</span>
              </button>
            ))}
          </div>
          <span className="muted small">Passwords are in .env.demo on the server machine.</span>
        </div>
      </motion.form>
    </div>
  );
}
