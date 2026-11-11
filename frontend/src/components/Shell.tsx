import { motion, useReducedMotion } from "framer-motion";
import { Search } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useSession } from "../auth/session";
import { SOURCE_LABELS, useSource } from "../source";
import type { Source } from "../api/types";
import { CommandPalette } from "./CommandPalette";
import { ErrorBoundary } from "./ErrorBoundary";

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
  const location = useLocation();
  const reduceMotion = useReducedMotion();
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPaletteOpen((o) => !o); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

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
        <button className="btn search-btn" aria-label="Search or jump to" onClick={() => setPaletteOpen(true)}>
          <Search size={14} aria-hidden /> <span className="muted">Search</span> <kbd>Ctrl K</kbd>
        </button>
        <SourceSelector />
        <span className="pill">{username} · {role}</span>
        <button className="btn" onClick={logout}>Sign out</button>
      </header>
      <main className="page">
        <ErrorBoundary key={location.key}>
          <motion.div key={location.pathname} initial={reduceMotion ? false : { opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
            <Outlet />
          </motion.div>
        </ErrorBoundary>
      </main>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}
