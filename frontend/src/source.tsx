import { createContext, useContext, useState, type ReactNode } from "react";
import type { Source } from "./api/types";

const KEY = "sentinel.source";
const VALID: Source[] = ["synthetic", "paysim", "paypal_sandbox"];
export const SOURCE_LABELS: Record<Source, string> = {
  synthetic: "Synthetic demo data", paysim: "PaySim (historical)", paypal_sandbox: "PayPal Sandbox",
};

function load(): Source {
  try {
    const v = sessionStorage.getItem(KEY) as Source | null;
    return v && VALID.includes(v) ? v : "synthetic";
  } catch { return "synthetic"; }
}

const Ctx = createContext<{ source: Source; setSource(s: Source): void } | null>(null);

export function SourceProvider({ children }: { children: ReactNode }) {
  const [source, set] = useState<Source>(load);
  const setSource = (s: Source) => {
    set(s);
    try { sessionStorage.setItem(KEY, s); } catch { /* storage unavailable */ }
  };
  return <Ctx.Provider value={{ source, setSource }}>{children}</Ctx.Provider>;
}

export function useSource() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useSource must be used inside SourceProvider");
  return v;
}
