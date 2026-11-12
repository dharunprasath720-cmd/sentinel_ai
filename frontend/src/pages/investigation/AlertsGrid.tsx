import type { ColDef, GridApi, GridReadyEvent, RowSelectionOptions } from "ag-grid-community";
import { Download, Search } from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import type { Alert } from "../../api/types";
import { LevelCell, TxnLinkCell, levelComparator } from "../../components/grid/cells";
import { SentinelGrid } from "../../components/grid/SentinelGrid";

/**
 * The alert list as a triage grid: sort by severity, filter, search, tick many rows, then open one case from the
 * selection. Selection lives in the grid; the page only hears which alert ids are ticked.
 */
export function AlertsGrid({ alerts, selectable, onSelectionChange }:
  { alerts: Alert[]; selectable: boolean; onSelectionChange: (ids: number[]) => void }) {
  const apiRef = useRef<GridApi<Alert> | null>(null);
  const [search, setSearch] = useState("");

  const columns = useMemo<ColDef<Alert>[]>(() => [
    { field: "txn_external_id", headerName: "Transaction", cellRenderer: TxnLinkCell, flex: 1.4, minWidth: 120 },
    { field: "level", headerName: "Level", cellRenderer: LevelCell, comparator: levelComparator, flex: 1, minWidth: 118 },
  ], []);

  const selection = useMemo<RowSelectionOptions<Alert> | undefined>(
    () => (selectable ? { mode: "multiRow", checkboxes: true, headerCheckbox: true, enableClickSelection: false } : undefined), [selectable]);
  const onReady = useCallback((e: GridReadyEvent<Alert>) => { apiRef.current = e.api; }, []);
  const onSelected = useCallback(() => {
    onSelectionChange((apiRef.current?.getSelectedRows() ?? []).map((a) => a.id));
  }, [onSelectionChange]);

  return (
    <div className="grid-block">
      <div className="grid-toolbar">
        <label className="search-box"><Search size={15} aria-hidden />
          <input type="search" aria-label="Search alerts" placeholder="Search alerts…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </label>
        {selectable ? (
          <button className="btn" aria-label="Export selected alerts as CSV"
                  onClick={() => apiRef.current?.exportDataAsCsv({ onlySelected: true, fileName: "sentinel-selected-alerts.csv" })}>
            <Download size={15} aria-hidden /> CSV
          </button>
        ) : null}
      </div>
      <div className="alerts-grid">
        <SentinelGrid<Alert>
          rowData={alerts} columnDefs={columns} getRowId={(p) => String(p.data.id)}
          defaultColDef={{ sortable: true, resizable: true, filter: true }}
          rowSelection={selection} quickFilterText={search}
          onGridReady={onReady} onSelectionChanged={onSelected}
        />
      </div>
    </div>
  );
}
