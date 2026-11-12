import type { ColDef, GridApi, GridReadyEvent, RowClassParams, RowClickedEvent } from "ag-grid-community";
import { Download, Search } from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { HIGH_PLUS, type Action, type Level } from "../../api/types";
import { LevelCell, ScoreCell, TxnLinkCell, levelComparator } from "../../components/grid/cells";
import { SentinelGrid } from "../../components/grid/SentinelGrid";
import { actionLabel, fmtMoney, fmtTime } from "../../format";

export interface LiveRow {
  id: string; ts: string; account: string; amount: number; level: Level | null; score: number | null;
  action: Action | null; cluster: string | null; fresh: boolean; // fresh = arrived over the live stream
}

const isHighPlus = (r?: LiveRow) => !!r?.level && HIGH_PLUS.includes(r.level);

/**
 * The live feed as an AG Grid. New events arrive as row updates keyed by transaction id, so the grid keeps the
 * analyst's sort, column filters and quick search while events keep streaming in.
 */
export function LiveEventsGrid({ rows }: { rows: LiveRow[] }) {
  const navigate = useNavigate();
  const apiRef = useRef<GridApi<LiveRow> | null>(null);
  const [search, setSearch] = useState("");
  const [shown, setShown] = useState(rows.length);

  const columns = useMemo<ColDef<LiveRow>[]>(() => [
    { field: "id", headerName: "Transaction", cellRenderer: TxnLinkCell, minWidth: 130, flex: 1.2 },
    { field: "ts", headerName: "Time", valueFormatter: (p) => fmtTime(String(p.value)), minWidth: 150, flex: 1.3, sort: undefined },
    { field: "account", headerName: "Account", minWidth: 110, flex: 1 },
    { field: "amount", headerName: "Amount", filter: "agNumberColumnFilter", valueFormatter: (p) => fmtMoney(Number(p.value)), minWidth: 90, flex: 0.8 },
    { field: "level", headerName: "Level", cellRenderer: LevelCell, comparator: levelComparator, enableCellChangeFlash: true, minWidth: 110, flex: 0.9 },
    { field: "score", headerName: "Risk score", cellRenderer: ScoreCell, filter: "agNumberColumnFilter", enableCellChangeFlash: true, minWidth: 130, flex: 1 },
    { field: "action", headerName: "Action", valueFormatter: (p) => (p.value ? actionLabel(String(p.value)) : "—"), minWidth: 120, flex: 1 },
    { field: "cluster", headerName: "Cluster", valueFormatter: (p) => p.value ?? "—", minWidth: 130, flex: 1.1 },
  ], []);

  const onReady = useCallback((e: GridReadyEvent<LiveRow>) => { apiRef.current = e.api; setShown(e.api.getDisplayedRowCount()); }, []);
  const refreshCount = useCallback(() => { if (apiRef.current) setShown(apiRef.current.getDisplayedRowCount()); }, []);
  const onRowClicked = useCallback((e: RowClickedEvent<LiveRow>) => {
    if (!e.data || (e.event?.target as HTMLElement | null)?.closest("a")) return;
    navigate(`/investigation/${encodeURIComponent(e.data.id)}`);
  }, [navigate]);
  const rowClass = useCallback((p: RowClassParams<LiveRow>) => [
    isHighPlus(p.data) ? "row-high-plus" : "", p.data?.fresh ? "row-new" : "", p.data?.fresh && isHighPlus(p.data) ? "row-pulse" : "",
  ].filter(Boolean), []);

  return (
    <div className="grid-block">
      <div className="grid-toolbar">
        <label className="search-box"><Search size={15} aria-hidden />
          <input type="search" aria-label="Search events" placeholder="Search events…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </label>
        <span className="muted" role="status">Showing {shown} of {rows.length} events</span>
        <button className="btn" onClick={() => apiRef.current?.exportDataAsCsv({ fileName: "sentinel-live-events.csv" })}>
          <Download size={15} aria-hidden /> Export CSV
        </button>
      </div>
      <div className="live-grid">
        <SentinelGrid<LiveRow>
          rowData={rows} columnDefs={columns} getRowId={(p) => p.data.id}
          defaultColDef={{ sortable: true, resizable: true, filter: true }}
          quickFilterText={search} rowClass="" getRowClass={rowClass}
          onGridReady={onReady} onModelUpdated={refreshCount} onRowClicked={onRowClicked}
        />
      </div>
    </div>
  );
}
