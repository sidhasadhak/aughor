"use client";

/**
 * SE-2 PR D — the schema rail beside the SQL editor.
 *
 * A thin frame around the shared `CatalogTree`. The tree owns the hierarchy, the
 * search and every visual convention; this file owns only the rail's width, border
 * and the insertion behaviour, so the SQL editor's catalog is the SAME catalog the
 * Query tab's Visual mode shows rather than a lookalike that drifts.
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
  onInsert,
}: {
  tables: SidebarTable[];
  /** Insert `text` at the editor's cursor. */
  onInsert: (text: string) => void;
}) {
  return (
    <div
      style={{
        width: 260, flexShrink: 0, display: "flex", flexDirection: "column",
        borderRight: "1px solid var(--b1)", background: "var(--bg-1)", overflow: "hidden",
      }}
    >
      <CatalogTree
        tables={tables}
        onSelectTable={onInsert}
        onSelectColumn={col => onInsert(col)}
        emptyLabel="No schema loaded."
      />
    </div>
  );
}
