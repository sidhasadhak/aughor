"use client";

/**
 * SE-2 PR D — the schema rail beside the SQL editor.
 *
 * A thin frame around the shared `CatalogTree`. The tree owns the hierarchy, the
 * search and every visual convention; this file owns only the rail's chrome and the
 * insertion behaviour, so the SQL editor's catalog is the SAME catalog the Catalog
 * screen and Visual mode show rather than a lookalike that drifts.
 *
 * It does NOT set its own width. The rail lives inside a `ResizableSplit`, and a pane
 * that hardcodes a width silently wins against the drag handle above it — the reason
 * this panel was unadjustable when it looked like it should not be.
 *
 * Clicking a table inserts its QUALIFIED name; clicking a column inserts the bare
 * column name — because that is what each one means where the cursor is. A qualified
 * table is unambiguous in a FROM clause, and a schema-qualified column would be wrong
 * in a SELECT list against an aliased table.
 */
import { CatalogTree, type CatalogTable } from "@/components/query/CatalogTree";

export type SidebarTable = CatalogTable;

export function SchemaSidebar({
  tables,
  connectionName,
  onInsert,
}: {
  tables: SidebarTable[];
  /** The connection this catalog belongs to — the tree's root node. */
  connectionName?: string;
  /** Insert `text` at the editor's cursor. */
  onInsert: (text: string) => void;
}) {
  return (
    <div
      style={{
        flex: 1, minWidth: 0, display: "flex", flexDirection: "column",
        borderRight: "1px solid var(--b1)", background: "var(--bg-1)", overflow: "hidden",
      }}
    >
      <CatalogTree
        tables={tables}
        catalogName={connectionName}
        onSelectTable={onInsert}
        onSelectColumn={col => onInsert(col)}
        emptyLabel="No schema loaded."
      />
    </div>
  );
}
