"use client";

/**
 * The catalog tree — ONE presentation of schema → table → column, for every surface
 * that shows a catalog.
 *
 * It exists because there were three. `CatalogScreen` had a hierarchical tree,
 * `QueryBuilder` had a second one with row counts and join degrees, and SE-2's SQL
 * sidebar had a third that was a flat list of truncated qualified names. Same product,
 * same data, three visual languages — and the flat one taught the user that the SQL
 * editor was a different kind of place than the tab next to it.
 *
 * The conventions here are QueryBuilder's, deliberately: it is the richest of the
 * three, it already sits in this tab, and its vocabulary (a `⋈n` join degree, an
 * `isolated` badge, compact row counts, the emerald/blue/zinc type dot) is information
 * the others were simply missing.
 *
 * **Presentational only.** It takes data and renders it; it holds no fetch, no
 * connection, and no builder state. Per-table and per-column ACTIONS arrive as render
 * props, which is what will let PR E move QueryBuilder's rail onto this component
 * without dragging `primaryTable` / auto-join / `addDim` into a shared module — those
 * become the builder's own `renderTableActions`, while the SQL editor passes none.
 */
import { useMemo, useState } from "react";
import Fuse from "fuse.js";
import { compactNumber } from "@/lib/format";
import { Button } from "@/components/ui/button";

export interface CatalogColumn {
  name: string;
  type?: string;
  is_fk?: boolean;
}

export interface CatalogTable {
  /** Qualified name as the warehouse spells it — what insertion uses. */
  name: string;
  columns: CatalogColumn[];
  rowCount?: string | number | null;
  /** Number of tables this one has a detected join to. */
  joinDegree?: number;
  isolated?: boolean;
}

const isNum = (t: string) => /\b(INT|BIGINT|SMALLINT|TINYINT|HUGEINT|DOUBLE|FLOAT|DECIMAL|NUMERIC|REAL|NUMBER)\b/i.test(t);
const isDate = (t: string) => /\b(DATE|TIME|TIMESTAMP|DATETIME)\b/i.test(t);

/** The type dot, matching QueryBuilder's legend exactly (num · date · text). */
const dot = (t: string) => (isNum(t) ? "bg-emerald-500" : isDate(t) ? "bg-blue-400" : "bg-zinc-500");

function fmtRows(rc: string | number | null | undefined): string | null {
  if (rc == null || rc === "") return null;
  const n = typeof rc === "string" ? parseInt(rc.replace(/[^0-9]/g, ""), 10) : rc;
  return Number.isFinite(n) ? compactNumber(n, 1) : null;
}

/** Split "schema.table" into its parts; an unqualified name lands under "". */
function splitName(qualified: string): { schema: string; bare: string } {
  const i = qualified.lastIndexOf(".");
  return i < 0
    ? { schema: "", bare: qualified }
    : { schema: qualified.slice(0, i), bare: qualified.slice(i + 1) };
}

export function CatalogTree({
  tables,
  onSelectTable,
  onSelectColumn,
  renderTableActions,
  emptyLabel = "No tables in this connection.",
}: {
  tables: CatalogTable[];
  onSelectTable?: (qualifiedName: string) => void;
  onSelectColumn?: (columnName: string, qualifiedTable: string) => void;
  /** Builder-specific affordances (add-to-query, primary/joined chips) go here, so
   *  this component never learns what a "primary table" is. */
  renderTableActions?: (table: CatalogTable) => React.ReactNode;
  emptyLabel?: string;
}) {
  const [search, setSearch] = useState("");
  const [openSchemas, setOpenSchemas] = useState<Set<string>>(new Set());
  const [openTables, setOpenTables] = useState<Set<string>>(new Set());

  const fuse = useMemo(
    () => new Fuse(tables, { keys: ["name", "columns.name"], threshold: 0.35, ignoreLocation: true }),
    [tables],
  );

  const visible = useMemo(() => {
    const q = search.trim();
    return q ? fuse.search(q).map(r => r.item) : tables;
  }, [search, tables, fuse]);

  /** schema → its tables, in catalog order. */
  const grouped = useMemo(() => {
    const map = new Map<string, CatalogTable[]>();
    for (const t of visible) {
      const { schema } = splitName(t.name);
      const list = map.get(schema);
      if (list) list.push(t); else map.set(schema, [t]);
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [visible]);

  // A search narrows to what matched, so everything it found should be visible without
  // a second click — expanding on search is the difference between a filter and a hunt.
  const searching = !!search.trim();
  const toggle = (set: Set<string>, key: string, apply: (s: Set<string>) => void) => {
    const next = new Set(set);
    if (next.has(key)) next.delete(key); else next.add(key);
    apply(next);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0, flex: 1 }}>
      <div style={{ padding: "8px 10px 6px", flexShrink: 0 }}>
        <div className="flex items-center gap-2 rounded-md border border-zinc-700 bg-zinc-800/70 px-3 py-2">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--t4)" strokeWidth="2" strokeLinecap="round">
            <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            placeholder="Search tables &amp; columns…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="aug-fs-sm w-full bg-transparent text-zinc-300 outline-none placeholder-zinc-500"
          />
          {search && (
            <Button
              variant="ghost" size="xs" onClick={() => setSearch("")}
              className="h-auto p-0 font-normal leading-none text-zinc-500 hover:bg-transparent dark:hover:bg-transparent"
            >
              ✕
            </Button>
          )}
        </div>
        {/* The same legend the builder shows, so a dot means one thing product-wide. */}
        <div className="mt-2.5 flex items-center gap-3">
          {([["bg-emerald-500", "num"], ["bg-blue-400", "date"], ["bg-zinc-500", "text"]] as const).map(([d, l]) => (
            <span key={l} className="aug-fs-xs flex items-center gap-1.5 text-zinc-500">
              <span className={`h-2 w-2 rounded-[var(--r-pill)] ${d}`} />{l}
            </span>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto py-1">
        {tables.length === 0 && (
          <p className="aug-fs-sm px-4 py-4 text-zinc-500">{emptyLabel}</p>
        )}
        {tables.length > 0 && visible.length === 0 && (
          <p className="aug-fs-sm px-4 py-4 text-zinc-500">No match.</p>
        )}

        {grouped.map(([schema, schemaTables]) => {
          const sOpen = searching || openSchemas.has(schema) || schema === "";
          return (
            <div key={schema || "(root)"}>
              {schema !== "" && (
                <Button
                  variant="ghost"
                  onClick={() => toggle(openSchemas, schema, setOpenSchemas)}
                  className="h-auto w-full justify-start gap-2 px-3 py-1.5 font-normal hover:bg-zinc-800/40"
                >
                  <svg width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="var(--t3)" strokeWidth="1.5"
                    strokeLinecap="round" className={`shrink-0 transition-transform duration-150 ${sOpen ? "rotate-90" : ""}`}>
                    <polyline points="2,1 6,4 2,7" />
                  </svg>
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="var(--t3)" strokeWidth="1.7"
                    strokeLinecap="round" className="shrink-0">
                    <path d="M3 7l9-4 9 4-9 4-9-4z" /><path d="M3 12l9 4 9-4M3 17l9 4 9-4" />
                  </svg>
                  <span className="aug-fs-xs truncate font-semibold uppercase tracking-wide text-zinc-300">
                    {schema}
                  </span>
                  <span className="aug-fs-xs ml-auto shrink-0 text-zinc-500">{schemaTables.length}</span>
                </Button>
              )}

              {sOpen && schemaTables.map(t => {
                const tOpen = searching || openTables.has(t.name);
                const { bare } = splitName(t.name);
                const rc = fmtRows(t.rowCount);
                return (
                  <div key={t.name}>
                    <div className="group/tbl flex w-full items-center gap-2 py-1.5 pl-7 pr-2 transition hover:bg-zinc-800/40">
                      <Button
                        variant="ghost"
                        onClick={() => toggle(openTables, t.name, setOpenTables)}
                        title={tOpen ? "Collapse columns" : "Expand columns"}
                        className="h-auto p-0 font-normal hover:bg-transparent dark:hover:bg-transparent"
                      >
                        <svg width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="var(--t3)" strokeWidth="1.5"
                          strokeLinecap="round" className={`shrink-0 transition-transform duration-150 ${tOpen ? "rotate-90" : ""}`}>
                          <polyline points="2,1 6,4 2,7" />
                        </svg>
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => onSelectTable?.(t.name)}
                        title={onSelectTable ? `Insert ${t.name} at the cursor` : t.name}
                        className="h-auto min-w-0 flex-1 justify-start gap-2 p-0 font-normal hover:bg-transparent dark:hover:bg-transparent"
                      >
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="var(--t2)" strokeWidth="1.7"
                          strokeLinecap="round" className="shrink-0">
                          <rect x="3" y="3" width="18" height="18" rx="2" /><line x1="3" y1="9" x2="21" y2="9" />
                          <line x1="9" y1="9" x2="9" y2="21" />
                        </svg>
                        <span className="aug-fs-sm truncate font-mono text-zinc-200">{bare}</span>
                        {rc && <span className="aug-fs-xs shrink-0 text-zinc-500">{rc}</span>}
                      </Button>
                      {(t.joinDegree ?? 0) > 0 && (
                        <span
                          title={`${t.joinDegree} related table${(t.joinDegree ?? 0) > 1 ? "s" : ""}`}
                          className="aug-fs-xs hidden shrink-0 items-center gap-0.5 text-zinc-500 sm:flex"
                        >
                          ⋈{t.joinDegree}
                        </span>
                      )}
                      {t.isolated && (
                        <span title="No detected joins to other tables" className="aug-fs-xs shrink-0 text-zinc-500">
                          isolated
                        </span>
                      )}
                      {renderTableActions?.(t)}
                    </div>

                    {tOpen && t.columns.map(c => (
                      <div key={c.name} className="ml-7 border-l border-zinc-700/40 pl-2">
                        <Button
                          variant="ghost"
                          onClick={() => onSelectColumn?.(c.name, t.name)}
                          title={onSelectColumn
                            ? `Insert ${c.name} at the cursor${c.type ? ` (${c.type})` : ""}`
                            : `${c.name}${c.type ? ` (${c.type})` : ""}`}
                          className="group h-auto w-full justify-start gap-2 px-3 py-1 font-normal hover:bg-zinc-800/60"
                        >
                          <span className={`h-2 w-2 shrink-0 rounded-[var(--r-pill)] ${dot(c.type ?? "")}`} />
                          <span className="aug-fs-sm flex-1 truncate text-left font-mono text-zinc-200">{c.name}</span>
                          {c.type && (
                            <span className="aug-fs-xs hidden shrink-0 font-mono uppercase text-zinc-500 group-hover:inline">
                              {c.type.split(" ")[0].slice(0, 6)}
                            </span>
                          )}
                          {c.is_fk && <span className="aug-fs-xs shrink-0 text-zinc-500">FK</span>}
                        </Button>
                      </div>
                    ))}
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}
