import type * as React from "react"
import { Table as ThemesTable } from "@radix-ui/themes"

/**
 * The dense table, on Radix Themes: its size-1 table — 36px rows, ruled by the Theme's own
 * line — drawn without a frame, so it sits on whatever holds it. Give a numeric column
 * `className="num"`: right-aligned, tabular (app/globals.css, `[data-slot="table"]`).
 */
function Table(props: Omit<React.ComponentProps<typeof ThemesTable.Root>, "size" | "variant">) {
  return <ThemesTable.Root data-slot="table" size="1" variant="ghost" {...props} />
}

function TableHeader(props: React.ComponentProps<typeof ThemesTable.Header>) {
  return <ThemesTable.Header data-slot="table-header" {...props} />
}

function TableBody(props: React.ComponentProps<typeof ThemesTable.Body>) {
  return <ThemesTable.Body data-slot="table-body" {...props} />
}

function TableRow(props: React.ComponentProps<typeof ThemesTable.Row>) {
  return <ThemesTable.Row data-slot="table-row" {...props} />
}

function TableHead(props: React.ComponentProps<typeof ThemesTable.ColumnHeaderCell>) {
  return <ThemesTable.ColumnHeaderCell data-slot="table-head" {...props} />
}

function TableCell(props: React.ComponentProps<typeof ThemesTable.Cell>) {
  return <ThemesTable.Cell data-slot="table-cell" {...props} />
}

export { Table, TableHeader, TableBody, TableHead, TableRow, TableCell }
