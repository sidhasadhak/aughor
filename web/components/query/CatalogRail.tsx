"use client";

/**
 * SE-2 PR E — the catalog rail, for the whole Query workbench.
 *
 * This was `SchemaSidebar`, a frame the SQL editor owned while the visual builder drew
 * its own 220-line tree beside it. Both modes now hang off this one rail, mounted by the
 * workbench OUTSIDE either mode pane, so switching Visual↔SQL leaves the catalog exactly
 * where it was — same scroll position, same expanded tables, same search — instead of
 * swapping one rail for a different rail showing the same warehouse.
 *
 * The frame is deliberately thin. Everything visible belongs to `CatalogTree`: the
 * hierarchy, the search, the type legend, the root node. What differs per mode arrives
 * as props from the workbench — insertion in SQL mode, add-to-query and drag in Visual
 * mode — so this file has no opinion about which mode is up.
 *
 * The one thing it draws itself is the mode hint under the header, because "drag to
 * auto-join" is true in Visual mode and a lie in SQL mode, and an affordance line that
 * lies is worse than no line.
 *
 * It does NOT set its own width. The rail lives inside a `ResizableSplit`, and a pane
 * that hardcodes a width silently wins against the drag handle above it — the reason
 * this panel was unadjustable when it looked like it should not be.
 */
import { CatalogTree, type CatalogTable, type CatalogColumn } from "@/components/query/CatalogTree";

export type RailTable = CatalogTable;
export type RailColumn = CatalogColumn;

export function CatalogRail({
  tables,
  connectionName,
  loading,
  hint,
  onSelectTable,
  onSelectColumn,
  renderTableActions,
  renderColumnActions,
  onColumnDragStart,
  isTableActive,
  actionLabel,
}: {
  tables: RailTable[];
  /** The connection this catalog belongs to — the tree's root node. */
  connectionName?: string;
  loading?: boolean;
  /** One line naming what this mode lets you do with a row. Omitted when there is
   *  nothing true to say. */
  hint?: string;
  onSelectTable?: (qualifiedName: string) => void;
  onSelectColumn?: (columnName: string, qualifiedTable: string) => void;
  renderTableActions?: (table: RailTable) => React.ReactNode;
  renderColumnActions?: (column: RailColumn, table: RailTable) => React.ReactNode;
  onColumnDragStart?: (e: React.DragEvent, column: RailColumn, table: RailTable) => void;
  isTableActive?: (table: RailTable) => boolean;
  actionLabel?: (name: string, kind: "table" | "column") => string;
}) {
  return (
    <div
      style={{
        flex: 1, minWidth: 0, display: "flex", flexDirection: "column",
        borderRight: "1px solid var(--b1)", background: "var(--bg-1)", overflow: "hidden",
      }}
    >
      {hint && (
        <p
          className="aug-fs-ui"
          style={{ padding: "8px 10px 0", color: "var(--t4)", flexShrink: 0 }}
        >
          {hint}
        </p>
      )}
      <CatalogTree
        tables={tables}
        catalogName={connectionName}
        loading={loading}
        onSelectTable={onSelectTable}
        onSelectColumn={onSelectColumn}
        renderTableActions={renderTableActions}
        renderColumnActions={renderColumnActions}
        onColumnDragStart={onColumnDragStart}
        isTableActive={isTableActive}
        actionLabel={actionLabel}
        emptyLabel="No schema loaded."
      />
    </div>
  );
}
