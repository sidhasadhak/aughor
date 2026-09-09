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
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { formatCount, isNumericType } from "@/lib/format";
import { cellStats, selectionToTsv, statText, type Cell as StatCell } from "@/lib/query/cellStats";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
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
/** The sticky header's height — the scroll maths has to allow for it. */
const HEADER_H = 30;

// ── The data editor's own state ──────────────────────────────────────────────

/** A rectangular block of cells, in row/column indices of the RENDERED grid. */
interface Sel { r0: number; c0: number; r1: number; c1: number }

const norm = (s: Sel) => ({
  top: Math.min(s.r0, s.r1), bottom: Math.max(s.r0, s.r1),
  left: Math.min(s.c0, s.c1), right: Math.max(s.c0, s.c1),
});

/** How many rows transpose will show. Transposing a 500-row result would produce 500
 *  columns, which is not a view of anything; DataGrip transposes a page for the same
 *  reason. The cap is STATED on screen rather than silently applied. */
const TRANSPOSE_ROWS = 30;

/** Pretty-print for the value viewer: JSON gets indented, everything else is shown
 *  exactly as it came back. No trimming — the viewer exists precisely for the values
 *  the cell had to truncate. */
function viewerText(v: Cell): string {
  if (v === null || v === undefined) return NULL_GLYPH;
  const s = String(v);
  const t = s.trim();
  if ((t.startsWith("{") && t.endsWith("}")) || (t.startsWith("[") && t.endsWith("]"))) {
    try { return JSON.stringify(JSON.parse(t), null, 2); } catch { /* not JSON after all */ }
  }
  return s;
}

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
  // ── SE-6: the data-editor state ────────────────────────────────────────────
  const [sel, setSel] = useState<Sel | null>(null);
  const dragging = useRef(false);
  const [hidden, setHidden] = useState<Set<string>>(() => new Set());
  const [showColumnMenu, setShowColumnMenu] = useState(false);
  const [transposed, setTransposed] = useState(false);
  const [showValue, setShowValue] = useState(false);
  const [copied, setCopied] = useState(false);
  // SE-7 — find-on-page and go-to-row, the grid's own ⌘F / ⌘G. The result filter bar
  // above NARROWS the rows; this one MOVES you to a cell and leaves the result alone.
  // They answer different questions ("which rows match" vs "where is that value") and
  // conflating them means you cannot see a match in its context.
  const [find, setFind] = useState<string | null>(null);
  const [findIdx, setFindIdx] = useState(0);
  const [goto, setGoto] = useState<string | null>(null);
  const findRef = useRef<HTMLInputElement>(null);

  const numeric = useMemo(() => {
    const out = new Set<string>();
    for (const c of columnsTyped ?? []) if (isNumericType(c.type)) out.add(c.name);
    return out;
  }, [columnsTyped]);

  // A new result is a new grid: a selection or a hidden column carried over from the
  // previous one would point at cells that no longer exist.
  const shapeKey = `${columns.join("\u0000")}|${rows.length}`;
  useEffect(() => {
    setSel(null); setHidden(new Set()); setTransposed(false); setShowValue(false);
  }, [shapeKey]);

  // ── Transpose ──────────────────────────────────────────────────────────────
  // Column names become the first column; each source row becomes a column. Done on
  // the DATA, before the table model, so sorting/virtualization/selection all keep
  // working on whatever is on screen without knowing which way round it is.
  const view = useMemo(() => {
    if (!transposed) return { columns, rows, numeric, transposeCut: 0 };
    const take = Math.min(rows.length, TRANSPOSE_ROWS);
    const cols = ["column", ...Array.from({ length: take }, (_, i) => `row ${i + 1}`)];
    const out = columns.map((name, c) => [name, ...rows.slice(0, take).map(r => r[c])] as Cell[]);
    // Nothing is numeric in a transposed grid: every column now mixes the types of
    // whatever fields the source rows held, so right-aligning any of it would lie.
    return { columns: cols, rows: out, numeric: new Set<string>(), transposeCut: rows.length - take };
  }, [transposed, columns, rows, numeric]);

  const visibleIdx = useMemo(
    () => view.columns.map((_, i) => i).filter(i => !hidden.has(String(i))),
    [view.columns, hidden],
  );

  // Rows arrive positionally; the table model is keyed. Index-based keys rather than
  // column names, because a result set may legally repeat a name (`SELECT a, a`) and
  // an object would silently drop the duplicate.
  const data = useMemo<Row[]>(
    () => view.rows.map(r => {
      const o: Row = {};
      r.forEach((v, i) => { o[String(i)] = v; });
      return o;
    }),
    [view.rows],
  );

  const cols = useMemo(
    () => helper.columns(visibleIdx.map(i => helper.accessor(String(i), {
      id: String(i),
      header: view.columns[i],
      // A number lands wider than a flag; guessing from the header alone gets `n`
      // wrong. The declared type is what we have before any row is measured.
      size: view.numeric.has(view.columns[i]) ? 120 : 180,
      minSize: 64,
    }))),
    [visibleIdx, view.columns, view.numeric],
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

  // ── Selection ──────────────────────────────────────────────────────────────
  // Indices are into the RENDERED grid (`modelRows` order, `visibleIdx` order), so a
  // sort or a hidden column moves the selection with what the eye sees rather than
  // leaving it pointing at the underlying array.
  const cellAt = useCallback((r: number, c: number): Cell => {
    const row = modelRows[r];
    if (!row) return null;
    return (row.original as Row)[String(visibleIdx[c])] ?? null;
  }, [modelRows, visibleIdx]);

  const selBlock = useMemo(() => {
    if (!sel) return null;
    const { top, bottom, left, right } = norm(sel);
    const grid: Cell[][] = [];
    for (let r = top; r <= bottom; r++) {
      const line: Cell[] = [];
      for (let c = left; c <= right; c++) line.push(cellAt(r, c));
      grid.push(line);
    }
    const allNumeric = Array.from({ length: right - left + 1 }, (_, i) =>
      view.numeric.has(view.columns[visibleIdx[left + i]])).every(Boolean);
    return { grid, stats: cellStats(grid.flat() as StatCell[], allNumeric) };
  }, [sel, cellAt, view.numeric, view.columns, visibleIdx]);

  const copySelection = useCallback(() => {
    if (!selBlock) return;
    navigator.clipboard?.writeText(selectionToTsv(selBlock.grid as StatCell[][]))
      .then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200); })
      .catch(() => {});
  }, [selBlock]);

  const move = useCallback((dr: number, dc: number, extend: boolean) => {
    setSel(prev => {
      const base = prev ?? { r0: 0, c0: 0, r1: 0, c1: 0 };
      const r1 = Math.max(0, Math.min(modelRows.length - 1, base.r1 + dr));
      const c1 = Math.max(0, Math.min(visibleIdx.length - 1, base.c1 + dc));
      return extend ? { ...base, r1, c1 } : { r0: r1, c0: c1, r1, c1 };
    });
  }, [modelRows.length, visibleIdx.length]);

  const onKeyDown = useCallback((e: React.KeyboardEvent) => {
    const k = e.key;
    if (k === "Escape") { setSel(null); setShowValue(false); setFind(null); setGoto(null); return; }
    if ((e.metaKey || e.ctrlKey) && (k === "f" || k === "F")) {
      e.preventDefault();
      setFind(f => f ?? "");
      setTimeout(() => findRef.current?.focus(), 0);
      return;
    }
    if ((e.metaKey || e.ctrlKey) && (k === "g" || k === "G")) { e.preventDefault(); setGoto(g => g ?? ""); return; }
    if ((e.metaKey || e.ctrlKey) && (k === "c" || k === "C")) { e.preventDefault(); copySelection(); return; }
    if ((e.metaKey || e.ctrlKey) && (k === "a" || k === "A")) {
      e.preventDefault();
      setSel({ r0: 0, c0: 0, r1: modelRows.length - 1, c1: visibleIdx.length - 1 });
      return;
    }
    // Shift+Enter opens the value viewer — DataGrip's own binding for "show me this
    // cell properly", which is the whole reason a truncated cell is tolerable.
    if (k === "Enter" && e.shiftKey) { e.preventDefault(); setShowValue(v => !v); return; }
    const step: Record<string, [number, number]> = {
      ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1],
      PageUp: [-20, 0], PageDown: [20, 0],
    };
    if (step[k]) { e.preventDefault(); move(step[k][0], step[k][1], e.shiftKey); return; }
    if (k === "Home") { e.preventDefault(); move(0, -visibleIdx.length, e.shiftKey); return; }
    if (k === "End") { e.preventDefault(); move(0, visibleIdx.length, e.shiftKey); return; }
  }, [copySelection, move, modelRows.length, visibleIdx.length]);

  // Keep the focused cell on screen when the keyboard moved it out of view.
  useEffect(() => {
    if (!sel || !scrollRef.current) return;
    const top = sel.r1 * ROW_HEIGHT;
    const el = scrollRef.current;
    if (top < el.scrollTop) el.scrollTop = top;
    else if (top + ROW_HEIGHT > el.scrollTop + el.clientHeight - HEADER_H) {
      el.scrollTop = top + ROW_HEIGHT - el.clientHeight + HEADER_H;
    }
  }, [sel]);

  // Every cell matching the find query, in reading order. Computed over the MODEL, not
  // the DOM: only ~30 rows are mounted at a time, so a DOM search would find matches
  // only in what you can already see.
  const matches = useMemo(() => {
    const q = (find ?? "").trim().toLowerCase();
    if (!q) return [] as { r: number; c: number }[];
    const out: { r: number; c: number }[] = [];
    for (let r = 0; r < modelRows.length; r++) {
      for (let c = 0; c < visibleIdx.length; c++) {
        const v = cellAt(r, c);
        if (v !== null && v !== undefined && String(v).toLowerCase().includes(q)) out.push({ r, c });
      }
    }
    return out;
  }, [find, modelRows.length, visibleIdx.length, cellAt]);

  const gotoMatch = useCallback((i: number) => {
    if (!matches.length) return;
    const n = ((i % matches.length) + matches.length) % matches.length;
    setFindIdx(n);
    const m = matches[n];
    setSel({ r0: m.r, c0: m.c, r1: m.r, c1: m.c });
  }, [matches]);

  // A new query starts from the top rather than wherever the last one ended.
  useEffect(() => { if (matches.length) gotoMatch(0); }, [matches, gotoMatch]);

  const focused = sel ? cellAt(sel.r1, sel.c1) : null;
  const focusedName = sel ? view.columns[visibleIdx[sel.c1]] : "";
  const cellBase: React.CSSProperties = {
    padding: "0 10px", lineHeight: `${ROW_HEIGHT}px`, height: ROW_HEIGHT,
    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
    borderBottom: "1px solid var(--b0)",
  };

  const st = selBlock?.stats;
  const controlBar = (
    <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0,
      padding: "4px 10px", borderBottom: "1px solid var(--b0)", background: "var(--bg-1)",
      position: "relative" }}>
      <Button size="xs" variant={transposed ? "secondary" : "ghost"}
        // `hidden` is keyed by column INDEX, and transposing changes what an index
        // means — keeping it would hide a different column than the one the user
        // ticked. Cleared with the selection, for the same reason.
        onClick={() => { setTransposed(t => !t); setSel(null); setHidden(new Set()); }}
        title="Swap rows and columns — read one record down the page instead of across it"
        data-testid="grid-transpose">
        <Icon name="flow" size={12} /> Transpose
      </Button>
      <Button size="xs" variant={hidden.size ? "secondary" : "ghost"}
        onClick={() => setShowColumnMenu(m => !m)} data-testid="grid-columns">
        <Icon name="column" size={12} />
        {hidden.size ? `Columns · ${hidden.size} hidden` : "Columns"}
      </Button>
      {showColumnMenu && (
        <>
          <div style={{ position: "fixed", inset: 0, zIndex: 8 }} onClick={() => setShowColumnMenu(false)} />
          <div className="aug-fs-sm" style={{ position: "absolute", top: "100%", left: 60, zIndex: 9,
            maxHeight: 280, overflowY: "auto", minWidth: 200, padding: 6,
            background: "var(--bg-2)", border: "1px solid var(--b2)",
            borderRadius: "var(--r2)", boxShadow: "var(--shadow-md)" }}>
            {view.columns.map((name, i) => (
              <label key={i} style={{ display: "flex", alignItems: "center", gap: 7,
                padding: "3px 6px", cursor: "pointer", color: "var(--t2)" }}>
                <input type="checkbox" checked={!hidden.has(String(i))}
                  onChange={() => setHidden(prev => {
                    const next = new Set(prev);
                    // Never hide the last one: a grid with no columns is not a view.
                    if (next.has(String(i))) next.delete(String(i));
                    else if (view.columns.length - next.size > 1) next.add(String(i));
                    return next;
                  })} />
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{name}</span>
              </label>
            ))}
            {hidden.size > 0 && (
              <Button size="xs" variant="ghost" onClick={() => setHidden(new Set())}
                style={{ width: "100%", marginTop: 4 }}>Show all</Button>
            )}
          </div>
        </>
      )}
      {sel && (
        <Button size="xs" variant={showValue ? "secondary" : "ghost"}
          onClick={() => setShowValue(v => !v)}
          title="Show this cell in full — ⇧↵" data-testid="grid-value-viewer">
          <Icon name="text" size={12} /> Value
        </Button>
      )}
      <Button size="xs" variant={find !== null ? "secondary" : "ghost"}
        onClick={() => { setFind(f => (f === null ? "" : null)); setTimeout(() => findRef.current?.focus(), 0); }}
        title="Find a value in these rows — ⌘F" data-testid="grid-find-toggle">
        <Icon name="search" size={12} /> Find
      </Button>
      {find !== null && (
        <>
          <input
            ref={findRef}
            className="aug-fs-sm"
            value={find}
            onChange={e => setFind(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter") { e.preventDefault(); gotoMatch(findIdx + (e.shiftKey ? -1 : 1)); }
              if (e.key === "Escape") { e.preventDefault(); setFind(null); scrollRef.current?.focus(); }
            }}
            placeholder="Find in these rows"
            data-testid="grid-find"
            style={{ width: 180, background: "var(--bg-0)", border: "1px solid var(--b1)",
              borderRadius: "var(--r1)", color: "var(--t1)", padding: "2px 7px", outline: "none" }}
          />
          <span className="aug-fs-xs" style={{ color: find.trim() && !matches.length ? "var(--amb4)" : "var(--t4)",
            whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }} data-testid="grid-find-count">
            {!find.trim() ? "" : matches.length ? `${findIdx + 1} of ${formatCount(matches.length)}` : "no match"}
          </span>
          <Button size="xs" variant="ghost" onClick={() => gotoMatch(findIdx - 1)}
            disabled={!matches.length} title="Previous match — ⇧↵"><Icon name="chevu" size={12} /></Button>
          <Button size="xs" variant="ghost" onClick={() => gotoMatch(findIdx + 1)}
            disabled={!matches.length} title="Next match — ↵"><Icon name="chevd" size={12} /></Button>
        </>
      )}
      {goto !== null && (
        <input
          autoFocus
          className="aug-fs-sm"
          value={goto}
          onChange={e => setGoto(e.target.value.replace(/[^0-9]/g, ""))}
          onKeyDown={e => {
            if (e.key === "Enter") {
              const n = parseInt(goto, 10);
              // 1-based, like the row numbers a person reads off the screen.
              if (Number.isFinite(n) && n >= 1) {
                const r = Math.min(modelRows.length, n) - 1;
                setSel({ r0: r, c0: 0, r1: r, c1: 0 });
              }
              setGoto(null);
              scrollRef.current?.focus();
            }
            if (e.key === "Escape") { setGoto(null); scrollRef.current?.focus(); }
          }}
          placeholder={`Row 1–${modelRows.length}`}
          data-testid="grid-goto"
          style={{ width: 120, background: "var(--bg-0)", border: "1px solid var(--b1)",
            borderRadius: "var(--r1)", color: "var(--t1)", padding: "2px 7px", outline: "none" }}
        />
      )}
      <span style={{ flex: 1 }} />
      {/* The aggregate readout — the thing that replaces writing a second query.
          Shown only for a real selection: repeating "1 cell" beside every click is
          noise, and a single cell has no statistics worth the name. */}
      {st && st.count > 1 && (
        <span className="aug-fs-xs" style={{ color: "var(--t3)", fontFamily: "var(--font-mono)",
          display: "flex", gap: 10, whiteSpace: "nowrap", overflow: "hidden" }}
          data-testid="grid-aggregate">
          <span>{statText(st.count)} cells</span>
          <span>{statText(st.distinct)} distinct</span>
          {st.nulls > 0 && <span style={{ color: "var(--amb4)" }}>{statText(st.nulls)} null</span>}
          {st.numeric && <>
            <span>Σ {statText(st.numeric.sum)}</span>
            <span>x̄ {statText(st.numeric.avg)}</span>
            <span>min {statText(st.numeric.min)}</span>
            <span>max {statText(st.numeric.max)}</span>
          </>}
        </span>
      )}
      {sel && (
        <Button size="xs" variant="ghost" onClick={copySelection} title="Copy the selection as TSV — ⌘C">
          <Icon name="copy" size={12} /> {copied ? "Copied" : "Copy"}
        </Button>
      )}
    </div>
  );

  const grid = (
    <div
      ref={scrollRef}
      tabIndex={0}
      onKeyDown={onKeyDown}
      onMouseUp={() => { dragging.current = false; }}
      onMouseLeave={() => { dragging.current = false; }}
      style={{
        ...(maxHeight === undefined
          ? { flex: 1, minHeight: 0, overflow: "auto" }
          : { maxHeight, overflow: "auto" }),
        position: "relative",
        outline: "none",
        // The browser's own text selection has to be off, or a shift-click paints a
        // second, different highlight across every column between the two cells —
        // measured on screen: the cell selection was one column of 13, and the page
        // showed three columns highlighted. Two selection models on one grid, one of
        // them invisible to the code. ⌘C is handled here, so nothing is lost.
        userSelect: "none",
      }}
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
                    justifyContent: view.numeric.has(String(header.column.columnDef.header))
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
                {row.getAllCells().map((cell, ci) => {
                  const value = cell.getValue() as Cell;
                  const isNull = value === null;
                  const name = String(cell.column.columnDef.header);
                  const box = sel ? norm(sel) : null;
                  const inSel = !!box && item.index >= box.top && item.index <= box.bottom
                    && ci >= box.left && ci <= box.right;
                  const isFocus = !!sel && sel.r1 === item.index && sel.c1 === ci;
                  return (
                    <div
                      key={cell.id}
                      // mousedown, not click: a drag has to start selecting before the
                      // button comes back up, which is what makes "drag across a column
                      // and read the sum" work at all.
                      onMouseDown={e => {
                        e.preventDefault();          // no native drag-select
                        dragging.current = true;
                        scrollRef.current?.focus();  // arrows and ⌘C need the focus
                        setShowColumnMenu(false);
                        setSel(prev => (e.shiftKey && prev)
                          ? { ...prev, r1: item.index, c1: ci }
                          : { r0: item.index, c0: ci, r1: item.index, c1: ci });
                      }}
                      onMouseEnter={() => {
                        if (dragging.current) setSel(prev => prev ? { ...prev, r1: item.index, c1: ci } : prev);
                      }}
                      onDoubleClick={() => setShowValue(true)}
                      style={{
                        ...cellBase, width: cell.column.getSize(), flexShrink: 0,
                        textAlign: view.numeric.has(name) ? "right" : "left",
                        fontVariantNumeric: view.numeric.has(name) ? "tabular-nums" : undefined,
                        color: isNull ? "var(--t4)" : "var(--t2)",
                        fontFamily: "var(--font-code, monospace)",
                        cursor: "cell",
                        background: inSel ? "var(--bg-sel)" : undefined,
                        boxShadow: isFocus ? "inset 0 0 0 1px var(--blue4)" : undefined,
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

  return (
    <div style={maxHeight === undefined
      ? { flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }
      : { display: "flex", flexDirection: "column" }}>
      {controlBar}
      {transposed && view.transposeCut > 0 && (
        <div className="aug-fs-xs" style={{ padding: "3px 10px", color: "var(--t4)",
          background: "var(--bg-1)", borderBottom: "1px solid var(--b0)" }}>
          Showing the first {TRANSPOSE_ROWS} rows as columns — {formatCount(view.transposeCut)} more
          are in the result but not in this view.
        </div>
      )}
      {grid}
      {/* ── The value viewer ────────────────────────────────────────────────
          A cell is one line high and clips; this is where a JSON blob, a long
          description or a stack trace is actually readable. Pinned to the bottom of
          the grid rather than floating over it, so the row it came from stays on
          screen beside it. */}
      {showValue && sel && (
        <div style={{ flexShrink: 0, borderTop: "1px solid var(--b1)", background: "var(--bg-1)",
          display: "flex", flexDirection: "column", maxHeight: 220 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 10px" }}>
            <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{focusedName}</span>
            <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>
              row {sel.r1 + 1}{focused === null ? " · NULL" : ` · ${formatCount(String(focused).length)} chars`}
            </span>
            <span style={{ flex: 1 }} />
            <Button size="xs" variant="ghost"
              onClick={() => { navigator.clipboard?.writeText(focused === null ? "" : String(focused)).catch(() => {}); }}>
              <Icon name="copy" size={12} /> Copy value
            </Button>
            <Button size="xs" variant="ghost" onClick={() => setShowValue(false)} aria-label="Close">
              <Icon name="close" size={12} />
            </Button>
          </div>
          <pre className="aug-fs-sm" data-testid="grid-value-text" style={{ margin: 0, padding: "0 10px 10px",
            overflow: "auto", whiteSpace: "pre-wrap", wordBreak: "break-word",
            fontFamily: "var(--font-mono)", color: focused === null ? "var(--t4)" : "var(--t2)" }}>
            {viewerText(focused)}
          </pre>
        </div>
      )}
    </div>
  );
}
