import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { createClient, type ApiClient } from "../api/client";
import type { Role } from "../api/types";

const KEY = "sentinel.session";
interface Stored { token: string | null; role: Role | null; username: string | null }
const EMPTY: Stored = { token: null, role: null, username: null };

function load(): Stored {
  try {
    const raw = sessionStorage.getItem(KEY);
    return raw ? { ...EMPTY, ...JSON.parse(raw) } : EMPTY;
  } catch { return EMPTY; }
}
function save(s: Stored | null) {
  try { if (s) sessionStorage.setItem(KEY, JSON.stringify(s)); else sessionStorage.removeItem(KEY); }
  catch { /* storage unavailable */ }
}

export interface SessionValue extends Stored {
  login(username: string, password: string): Promise<void>;
  logout(): void;
  client: ApiClient;
}
const Ctx = createContext<SessionValue | null>(null);

export function SessionProvider({ children, fetchImpl }: { children: ReactNode; fetchImpl?: typeof fetch }) {
  const [state, setState] = useState<Stored>(load);
  const tokenRef = useRef<string | null>(state.token);

  const logout = useCallback(() => { save(null); tokenRef.current = null; setState(EMPTY); }, []);
  const client = useMemo(
    () => createClient({ getToken: () => tokenRef.current, onUnauthorized: logout, fetchImpl }),
    [logout, fetchImpl]);
  const login = useCallback(async (username: string, password: string) => {
    const r = await client.post<{ access_token: string; role: Role }>("/auth/login", { username, password });
    const next = { token: r.access_token, role: r.role, username };
    save(next); tokenRef.current = next.token; setState(next);
  }, [client]);

  const value = useMemo(() => ({ ...state, login, logout, client }), [state, login, logout, client]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): SessionValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useSession must be used inside SessionProvider");
  return v;
}
