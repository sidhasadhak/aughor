"use client";

/**
 * SE-1 — the results grid SEAM.
 *
 * Today this wraps the existing `SqlResultTable`; SE-3 replaces the body with TanStack
 * Table + Virtual for bulk rendering. The seam exists so that swap is a change to ONE
 * file rather than to every caller — and so the typed contract (real nulls, per-column
 * types) is established now, while the renderer behind it is still the old one.
 *
 * Two things this layer owns, because they are contract, not rendering:
 *
 * **Nulls survive as nulls.** The typed endpoint distinguishes a SQL NULL from an
 * empty string, and that distinction is the whole reason `format:"typed"` exists.
 * `SqlResultTable` takes `string[][]`, so the conversion happens here and renders NULL
 * as the `∅` glyph — never as a blank cell that reads as an empty string, which is a
 * different fact about the data.
 *
 * **Numerics right-align** from the column's declared type rather than from sniffing
 * the rendered text, so a numeric column of all-nulls still aligns as a number.
 */
import { useMemo } from "react";
import { SqlResultTable } from "@/components/AugTable";
import { isNumericType } from "@/lib/format";
import type { TypedColumn } from "@/lib/api";

/** The glyph for a real SQL NULL. Distinct from "" on purpose. */
export const NULL_GLYPH = "∅";

export function ResultsGrid({
  columns,
  columnsTyped,
  rows,
  maxHeight = 420,
}: {
  columns: string[];
  columnsTyped?: TypedColumn[];
  rows: (string | number | boolean | null)[][];
  maxHeight?: number;
}) {
  // Cells → strings for the current renderer, with NULL made visible rather than
  // flattened into "". When SE-3 swaps the body, this conversion goes away and the
  // grid consumes the typed cells directly.
  const textRows = useMemo(
    () => rows.map(r => r.map(cell => (cell === null ? NULL_GLYPH : String(cell)))),
    [rows],
  );

  const columnOverrides = useMemo(() => {
    const out: Record<string, { align?: "left" | "right" }> = {};
    for (const c of columnsTyped ?? []) {
      if (isNumericType(c.type)) out[c.name] = { align: "right" };
    }
    return out;
  }, [columnsTyped]);

  return (
    <SqlResultTable
      columns={columns}
      rows={textRows}
      columnOverrides={columnOverrides}
      maxHeight={maxHeight}
      totals={false}
    />
  );
}
