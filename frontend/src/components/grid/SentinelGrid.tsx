import { AllCommunityModule, ModuleRegistry, colorSchemeDarkBlue, themeQuartz } from "ag-grid-community";
import { AgGridReact, type AgGridReactProps } from "ag-grid-react";

// AG Grid Community only (MIT). Nothing from the paid Enterprise tier is used.
ModuleRegistry.registerModules([AllCommunityModule]);

/** The app's navy and sky-blue palette, expressed through AG Grid's theming API. */
export const sentinelTheme = themeQuartz.withPart(colorSchemeDarkBlue).withParams({
  backgroundColor: "#0d1730",
  foregroundColor: "#e8edf7",
  headerBackgroundColor: "#132442",
  headerTextColor: "#94a3c0",
  borderColor: "#1f3358",
  accentColor: "#38bdf8",
  oddRowBackgroundColor: "#0f1b36",
  rowHoverColor: "rgba(56, 189, 248, 0.09)",
  selectedRowBackgroundColor: "rgba(47, 107, 255, 0.25)",
  fontFamily: ["Inter Variable", "system-ui", "Segoe UI", "sans-serif"],
  fontSize: 13,
  headerFontWeight: 600,
  borderRadius: 10,
  wrapperBorderRadius: 12,
  spacing: 6,
});

// jsdom has no layout, so tests render every row and column instead of only the visible ones
const TESTING = import.meta.env.MODE === "test";

export function SentinelGrid<T>(props: AgGridReactProps<T>) {
  return (
    <div className="grid-shell" style={{ height: "100%" }}>
      <AgGridReact<T>
        theme={sentinelTheme}
        animateRows={!TESTING}
        suppressRowVirtualisation={TESTING}
        suppressColumnVirtualisation={TESTING}
        suppressCellFocus
        {...props}
      />
    </div>
  );
}
