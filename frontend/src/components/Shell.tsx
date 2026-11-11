import { NavLink, Outlet } from "react-router-dom";
import { useSession } from "../auth/session";
import { SOURCE_LABELS, useSource } from "../source";
import type { Source } from "../api/types";

const NAV = [
  { to: "/", label: "Overview", end: true },
  { to: "/live", label: "Live Monitoring" },
  { to: "/investigation", label: "Investigation" },
  { to: "/graph", label: "Graph Explorer" },
  { to: "/investigator", label: "AI Investigator" },
];

export function SourceSelector() {
  const { source, setSource } = useSource();
  return (
    <label className="row muted">
      Data source
      <select aria-label="Data source" value={source} onChange={(e) => setSource(e.target.value as Source)}>
        {(Object.keys(SOURCE_LABELS) as Source[]).map((s) => (
          <option key={s} value={s}>{SOURCE_LABELS[s]}</option>
        ))}
      </select>
    </label>
  );
}

export function Shell() {
  const { username, role, logout } = useSession();
  return (
    <div className="app">
      <header className="header">
        <span className="brand">SENTINEL</span>
        <nav className="nav">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? "active" : "")}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <SourceSelector />
        <span className="pill">{username} · {role}</span>
        <button className="btn" onClick={logout}>Sign out</button>
      </header>
      <main className="page"><Outlet /></main>
    </div>
  );
}
