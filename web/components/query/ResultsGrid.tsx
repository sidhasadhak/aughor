"use client";

/**
 * SE-3 G — the results grid, now TanStack Table + Virtual behind the SE-1 seam.
 *
 * The seam existed for exactly this: SE-1 wrapped the antd `SqlResultTable` and said
 * the swap would be "a change to ONE file rather than to every caller". It was. The
 * contract above it is unchanged — `columns`, `columnsTyped`, `rows`, `maxHeight` —
 * and both things that layer owns are still owned here:
 *
 * **Nulls survive as nulls.** The typed endpoint distinguishes a SQL NULL from an
 * empty string, and that distinction is the whole reason `format:"typed"` exists.
 * NULL renders as `∅`, never as a blank cell that reads as an empty string.
 *
 * **Numerics right-align from the DECLARED type**, not from sniffing rendered text,
 * so a numeric column of all-nulls still aligns as a number.
 *
 * **Why virtualize.** The old grid mounted a DOM node per cell, so a 10k-row result —
 * which SE-3's raised limit makes ordinary — was ~100k nodes and a locked tab. Only
 * the visible window is mounted now, so cost tracks the viewport instead of the result.
 *
 * **v9, not v8.** `@tanstack/react-table@9` removed `useReactTable` and the
 * `getCoreRowModel` family; it is `useTable`, `tableFeatures({...})` with features
 * registered explicitly, `createSortedRowModel()`, and `table.FlexRender`. Written
 * from the package's own shipped docs after checking the installed exports — v8
 * idioms from memory compile to nothing here, the same way the Langfuse v2 calls did.
 */
import { useMemo, useRef, useState } from "react";
import {
  createColumnHelper,
  createSortedRowModel,
  columnResizingFeature,
  columnSizingFeature,
  rowSortingFeature,
  tableFeatures,
  useTable,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { isNumericType } from "@/lib/format";
import type { TypedColumn } from "@/lib/api";

/** The glyph for a real SQL NULL. Distinct from "" on purpose. */
export const NULL_GLYPH = "∅";

type Cell = string | number | boolean | null;
type Row = Record<string, Cell>;

/** Only the features this grid actually uses — v9 requires them declared, and an
 *  unregistered feature is dead weight in the table model. */
const features = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  columnSizingFeature,
  columnResizingFeature,
});

const helper = createColumnHelper<typeof features, Row>();

const ROW_HEIGHT = 30;

export function ResultsGrid({
  columns,
  columnsTyped,
  rows,
  maxHeight,
}: {
  columns: string[];
  columnsTyped?: TypedColumn[];
  rows: Cell[][];
  /** Omit to FILL the parent and scroll internally — which is what virtualization
   *  needs. The virtualizer measures the element it is told to scroll; if that
   *  element never scrolls (because an ancestor does, or because the height is
   *  effectively unbounded) it sees a viewport as tall as the data and mounts every
   *  row. Measured: 500 rows returned, 500 rows in the DOM. */
  maxHeight?: number;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [sorting, setSorting] = useState<{ id: string; desc: boolean }[]>([]);

  const numeric = useMemo(() => {
    const out = new Set<string>();
    for (const c of columnsTyped ?? []) if (isNumericType(c.type)) out.add(c.name);
    return out;
  }, [columnsTyped]);

  // Rows arrive positionally; the table model is keyed. Index-based keys rather than
  // column names, because a result set may legally repeat a name (`SELECT a, a`) and
  // an object would silently drop the duplicate.
  const data = useMemo<Row[]>(
    () => rows.map(r => {
      const o: Row = {};
      r.forEach((v, i) => { o[String(i)] = v; });
      return o;
    }),
    [rows],
  );

  const cols = useMemo(
    () => helper.columns(columns.map((name, i) => helper.accessor(String(i), {
      id: String(i),
      header: name,
      // A number lands wider than a flag; guessing from the header alone gets `n`
      // wrong. The declared type is what we have before any row is measured.
      size: numeric.has(name) ? 120 : 180,
      minSize: 64,
    }))),
    [columns, numeric],
  );

  const table = useTable({
    features,
    columns: cols,
    data,
    state: { sorting },
    onSortingChange: setSorting,
    columnResizeMode: "onChange",
  });

  const modelRows = table.getRowModel().rows;
  const virtualizer = useVirtualizer({
    count: modelRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    getItemKey: index => modelRows[index].id,
    overscan: 12,
  });

  const totalWidth = table.getTotalSize();
  const cellBase: React.CSSProperties = {
    padding: "0 10px", lineHeight: `${ROW_HEIGHT}px`, height: ROW_HEIGHT,
    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
    borderBottom: "1px solid var(--b0)",
  };

  return (
    <div
      ref={scrollRef}
      style={maxHeight === undefined
        ? { flex: 1, minHeight: 0, overflow: "auto", position: "relative" }
        : { maxHeight, overflow: "auto", position: "relative" }}
      className="aug-fs-ui"
    >
      <div style={{ width: totalWidth, minWidth: "100%" }}>
        {/* Sticky header. `position: sticky` on the scroll container's own child keeps
            the column names visible through a 10k-row scroll — the thing that made the
            old grid unreadable past the first screen. */}
        {table.getHeaderGroups().map(group => (
          <div
            key={group.id}
            style={{
              display: "flex", position: "sticky", top: 0, zIndex: 2,
              background: "var(--bg-1)", borderBottom: "1px solid var(--b1)",
            }}
          >
            {group.headers.map(header => {
              const sorted = header.column.getIsSorted();
              return (
                <div
                  key={header.id}
                  style={{
                    ...cellBase, width: header.getSize(), flexShrink: 0,
                    borderBottom: "none", position: "relative",
                    display: "flex", alignItems: "center", gap: 4,
                    justifyContent: numeric.has(String(header.column.columnDef.header))
                      ? "flex-end" : "flex-start",
                    color: "var(--t3)", fontWeight: 600, cursor: "pointer",
                    userSelect: "none",
                  }}
                  onClick={header.column.getToggleSortingHandler()}
                  title={`${header.column.columnDef.header} — click to sort`}
                >
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
                    {header.isPlaceholder ? null : <table.FlexRender header={header} />}
                  </span>
                  {/* The arrow is drawn only when a sort is active: a permanent pair of
                      faded arrows on every column is noise on a wide result. */}
                  {sorted && <span style={{ color: "var(--t4)" }}>{sorted === "desc" ? "↓" : "↑"}</span>}
                  <div
                    onMouseDown={header.getResizeHandler?.()}
                    onTouchStart={header.getResizeHandler?.()}
                    onClick={e => e.stopPropagation()}   // resizing is not sorting
                    style={{
                      position: "absolute", right: 0, top: 0, height: "100%",
                      width: 5, cursor: "col-resize", touchAction: "none",
                    }}
                  />
                </div>
              );
            })}
          </div>
        ))}

        <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
          {virtualizer.getVirtualItems().map(item => {
            const row = modelRows[item.index];
            return (
              <div
                key={row.id}
                data-index={item.index}
                style={{
                  position: "absolute", top: 0, left: 0, display: "flex",
                  width: "100%", transform: `translateY(${item.start}px)`,
                }}
              >
                {row.getAllCells().map(cell => {
                  const value = cell.getValue() as Cell;
                  const isNull = value === null;
                  const name = String(cell.column.columnDef.header);
                  return (
                    <div
                      key={cell.id}
                      style={{
                        ...cellBase, width: cell.column.getSize(), flexShrink: 0,
                        textAlign: numeric.has(name) ? "right" : "left",
                        fontVariantNumeric: numeric.has(name) ? "tabular-nums" : undefined,
                        color: isNull ? "var(--t4)" : "var(--t2)",
                        fontFamily: "var(--font-code, monospace)",
                      }}
                      title={isNull ? "NULL" : String(value)}
                    >
                      {isNull ? NULL_GLYPH : String(value)}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
