import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

const PAGES = [
  { label: "Overview", to: "/", hint: "Portfolio health at a glance" },
  { label: "Live Monitoring", to: "/live", hint: "Scored events as they arrive" },
  { label: "Investigation", to: "/investigation", hint: "Alerts, cases and evidence" },
  { label: "Graph Explorer", to: "/graph", hint: "Linked accounts, devices and merchants" },
  { label: "AI Investigator", to: "/investigator", hint: "Ask questions grounded in evidence" },
];
const ID_LIKE = /^[A-Za-z0-9_.:-]{3,}$/;

interface Item { label: string; to: string; hint: string }

/** Ctrl+K: jump to a page, or paste a transaction id to open its investigation. */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);

  useEffect(() => { if (open) { setQuery(""); setSelected(0); } }, [open]);

  const items = useMemo<Item[]>(() => {
    const q = query.trim();
    const pages = PAGES.filter((p) => p.label.toLowerCase().includes(q.toLowerCase()));
    return ID_LIKE.test(q)
      ? [...pages, { label: `Open investigation for ${q}`, to: `/investigation/${encodeURIComponent(q)}`, hint: "Transaction id" }]
      : pages;
  }, [query]);

  if (!open) return null;

  const go = (item: Item | undefined) => { if (item) { onClose(); navigate(item.to); } };
  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") { e.preventDefault(); setSelected((s) => Math.min(items.length - 1, s + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSelected((s) => Math.max(0, s - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); go(items[selected]); }
    else if (e.key === "Escape") { e.preventDefault(); onClose(); }
  }

  return (
    <div className="overlay palette-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div role="dialog" aria-modal="true" aria-label="Command palette" className="panel palette">
        <input
          autoFocus role="combobox" aria-expanded="true" aria-controls="palette-list"
          aria-label="Search pages or paste a transaction id" placeholder="Jump to a page, or paste a transaction id…"
          value={query} onChange={(e) => { setQuery(e.target.value); setSelected(0); }} onKeyDown={onKeyDown}
          aria-activedescendant={items[selected] ? `palette-item-${selected}` : undefined} />
        {items.length === 0 ? <div className="muted palette-empty">No matches</div> : (
          <ul id="palette-list" role="listbox">
            {items.map((item, i) => (
              <li key={item.to} id={`palette-item-${i}`} role="option" aria-selected={i === selected}
                  className={i === selected ? "palette-item selected" : "palette-item"}
                  onMouseEnter={() => setSelected(i)} onClick={() => go(item)}>
                <span>{item.label}</span><span className="muted">{item.hint}</span>
              </li>
            ))}
          </ul>
        )}
        <div className="muted palette-foot">↑ ↓ to move · Enter to open · Esc to close</div>
      </div>
    </div>
  );
}
