"use client";

/**
 * The filter column of a dashboard made from a file: each column's values, how many rows hold each, a bar for the spread. A click
 * narrows every query card that reads the table, whatever its query says, through `queries.narrowed` on the server: the card's
 * statement is not rewritten and each value is bound. What a reader ticks is theirs and is never kept in the dashboard.
 *
 * The same context carries `changes`, which goes up when a row is added here (`AddRowPiece`), so every card reads the sheet again.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { previewDashboardQuery, type QueryNarrowing } from "@/lib/api";
import { fmtDate, formatCount } from "@/lib/format";

export interface FilterColumn { column: string; label: string; grain?: string | null }

interface Narrowing {
  table: string | null;
  narrowing: QueryNarrowing[];
  chosen: (column: string) => string[];
  toggle: (column: string, value: string, grain?: string | null) => void;
  clear: () => void;
  /** How many rows have been added on this page: a card reads the sheet again each time it goes up. */
  changes: number;
  changed: () => void;
}

const NONE: Narrowing = { table: null, narrowing: [], chosen: () => [], toggle: () => {}, clear: () => {}, changes: 0, changed: () => {} };
const Context = createContext<Narrowing>(NONE);

export const useQueryNarrowing = () => useContext(Context);

export function QueryNarrowingProvider({ table, children }: { table: string | null; children: ReactNode }) {
  const [picked, setPicked] = useState<Record<string, { values: string[]; grain?: string | null }>>({});
  const [changes, setChanges] = useState(0);
  const toggle = useCallback((column: string, value: string, grain?: string | null) => setPicked(p => {
    const held = p[column]?.values ?? [];
    const values = held.includes(value) ? held.filter(v => v !== value) : [...held, value];
    const next = { ...p, [column]: { values, grain } };
    if (!values.length) delete next[column];
    return next;
  }), []);
  const clear = useCallback(() => setPicked({}), []);
  const changed = useCallback(() => setChanges(n => n + 1), []);
  const value = useMemo<Narrowing>(() => ({
    table,
    narrowing: table ? Object.entries(picked).map(([column, f]) => ({ table, column, values: f.values, ...(f.grain ? { grain: f.grain } : {}) })) : [],
    chosen: column => picked[column]?.values ?? [],
    toggle, clear, changes, changed,
  }), [table, picked, toggle, clear, changes, changed]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

/** Whether a statement reads this table, as the server reads it for narrowing. A name inside a string is harmless: narrowing it
 *  there changes nothing, and the server checks again. */
export function readsTable(sql: string | null | undefined, table: string | null): boolean {
  if (!sql || !table) return false;
  return new RegExp(`\\b${table.replace(/[^A-Za-z0-9_]/g, "")}\\b`, "i").test(sql);
}

const ident = (name: string) => `"${name.replace(/"/g, '""')}"`;
const valueName = (value: string, grain?: string | null) => (grain === "month" ? fmtDate(`${value}-01`, "month") : value);
/** How many values a filter lists: every month of twenty years, or the commonest of a column, and it says when there are more. */
const LISTED = { month: 240, values: 40 };

function Facet({ connectionId, table, column }: { connectionId: string; table: string; column: FilterColumn }) {
  const { narrowing, chosen, toggle, changes } = useQueryNarrowing();
  const listed = column.grain === "month" ? LISTED.month : LISTED.values;
  const others = useMemo(() => narrowing.filter(n => n.column !== column.column), [narrowing, column.column]);
  const sent = JSON.stringify(others);
  const [rows, setRows] = useState<{ value: string; n: number }[] | null>(null);
  const [problem, setProblem] = useState("");
  useEffect(() => {
    let live = true;
    const target = column.grain === "month" ? `strftime(${ident(column.column)}, '%Y-%m')` : ident(column.column);
    const order = column.grain === "month" ? "value DESC" : "n DESC";     // the newest month first: what a reader most often wants
    const sql = `SELECT ${target} AS value, COUNT(*) AS n FROM ${ident(table)} WHERE ${ident(column.column)} IS NOT NULL GROUP BY 1 ORDER BY ${order} LIMIT ${listed + 1}`;
    previewDashboardQuery(connectionId, { sql, shown: { as: "table" }, filters: JSON.parse(sent) as QueryNarrowing[] }).then(p => {
      if (!live) return;
      if (p.refused?.length) { setProblem(p.refused[0]); return; }
      setProblem("");
      setRows((p.rows ?? []).map(r => ({ value: String(r[0]), n: Number(r[1]) || 0 })));
    }).catch(e => { if (live) setProblem(e instanceof Error ? e.message : String(e)); });
    return () => { live = false; };
  }, [connectionId, table, column.column, column.grain, sent, changes, listed]);
  const picked = chosen(column.column);
  const more = (rows?.length ?? 0) > listed;
  const shown = (rows ?? []).slice(0, listed);
  for (const v of picked) if (!shown.some(r => r.value === v)) shown.push({ value: v, n: 0 });
  const top = Math.max(1, ...shown.map(r => r.n));
  return (
    <div data-testid="query-facet" role="group" aria-label={column.label}>
      <div className="aug-fs-xs" style={{ color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".06em" }}>{column.label}</div>
      {problem ? <div className="aug-fs-sm" style={{ color: "var(--t3)", marginTop: 5 }}>{problem}</div>
        : !rows ? <div className="aug-fs-sm" style={{ color: "var(--t3)", marginTop: 5 }}>Reading…</div>
          : (
            <div data-testid="query-facet-rows" style={{ marginTop: 5, maxHeight: 340, overflowY: "auto" }}>
              {shown.map(r => {
                const on = picked.includes(r.value);
                return (
                  <label key={r.value} data-testid="query-facet-row" data-on={on || undefined} className="aug-fs-sm"
                    style={{ display: "grid", gridTemplateColumns: "16px minmax(0, 1fr) 52px 48px", alignItems: "center", gap: 7,
                      padding: "3px 4px", borderRadius: "var(--r2)", cursor: "pointer", background: on ? "var(--bg-sel)" : undefined }}>
                    <Checkbox checked={on} aria-label={`${column.label}: ${valueName(r.value, column.grain)}`}
                      onChange={() => toggle(column.column, r.value, column.grain)} />
                    <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: "var(--t1)" }}>{valueName(r.value, column.grain)}</span>
                    <span style={{ textAlign: "right", color: "var(--t2)", fontVariantNumeric: "tabular-nums" }}>{formatCount(r.n)}</span>
                    <span aria-hidden="true" style={{ height: 6, background: "var(--bg-4)", borderRadius: 3, overflow: "hidden" }}>
                      <span style={{ display: "block", height: "100%", width: `${(r.n / top) * 100}%`, background: "var(--chart-1)" }} />
                    </span>
                  </label>
                );
              })}
              {more && <div className="aug-fs-sm" data-testid="query-facet-more" style={{ color: "var(--t3)", padding: "3px 4px" }}>Showing the first {formatCount(listed)}. The rest are still counted.</div>}
            </div>
          )}
      {/* the box holds about this many; on a Mac its scrollbar does not show until it is used */}
      {rows && shown.length > 14 && <div className="aug-fs-sm" data-testid="query-facet-scroll" style={{ color: "var(--t3)", padding: "4px 4px 0" }}>{column.grain === "month" ? `Newest first. ${formatCount(shown.length)} months: scroll for the rest.` : `${formatCount(shown.length)} values: scroll for the rest.`}</div>}
    </div>
  );
}

/** How many rows the filters leave, of how many the sheet holds. */
function SetSize({ connectionId, table }: { connectionId: string; table: string }) {
  const { narrowing, clear, changes } = useQueryNarrowing();
  const sent = JSON.stringify(narrowing);
  const [left, setLeft] = useState<number | null>(null);
  const [whole, setWhole] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    const sql = `SELECT COUNT(*) AS n FROM ${ident(table)}`;
    const read = (filters: QueryNarrowing[]) => previewDashboardQuery(connectionId, { sql, shown: { as: "table" }, filters })
      .then(p => Number(p.rows?.[0]?.[0] ?? 0));
    read(JSON.parse(sent) as QueryNarrowing[]).then(n => { if (live) setLeft(n); }).catch(() => { if (live) setLeft(null); });
    read([]).then(n => { if (live) setWhole(n); }).catch(() => { if (live) setWhole(null); });
    return () => { live = false; };
  }, [connectionId, table, sent, changes]);
  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8 }}>
        <span className="aug-fs-ui" data-testid="query-filters-left" style={{ fontWeight: 500, fontVariantNumeric: "tabular-nums" }}>{left === null ? "…" : formatCount(left)}</span>
        <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>of {whole === null ? "…" : formatCount(whole)} rows</span>
      </div>
      {narrowing.length > 0 && <Button size="xs" variant="ghost" style={{ marginTop: 6 }} data-testid="query-filters-clear" onClick={clear}>Clear filters</Button>}
    </div>
  );
}

export function QueryFiltersPiece({ connectionId, table, columns }: { connectionId: string; table: string; columns: FilterColumn[] }) {
  return (
    <aside data-testid="query-filters" aria-label="Filters" style={{
      background: "var(--bg-2)", border: "1px solid var(--card-edge)", borderRadius: "var(--r3)", padding: "10px 12px",
      display: "flex", flexDirection: "column", gap: 14, alignSelf: "start", position: "sticky", top: 12,
    }}>
      <SetSize connectionId={connectionId} table={table} />
      {columns.map(c => <Facet key={c.column} connectionId={connectionId} table={table} column={c} />)}
    </aside>
  );
}
