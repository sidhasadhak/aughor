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
import { Chevron, IcoCatalog, IcoSchema, IcoTable } from "@/components/icons/catalog";
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
  catalogName,
  onSelectTable,
  onSelectColumn,
  renderTableActions,
  emptyLabel = "No tables in this connection.",
}: {
  tables: CatalogTable[];
  /** The CONNECTION this catalog belongs to, rendered as the tree's root.
   *
   *  Without it the tree began at schema level, so the SQL editor showed
   *  `luxexperience` with nothing saying which warehouse that was — while the Catalog
   *  screen and Visual mode both root at the connection. Two schemas in different
   *  connections can share a name, so the root is not decoration: it is the only thing
   *  on screen that says what you are querying. */
  catalogName?: string;
  onSelectTable?: (qualifiedName: string) => void;
  onSelectColumn?: (columnName: string, qualifiedTable: string) => void;
  /** Builder-specific affordances (add-to-query, primary/joined chips) go here, so
   *  this component never learns what a "primary table" is. */
  renderTableActions?: (table: CatalogTable) => React.ReactNode;
  emptyLabel?: string;
}) {
  const [search, setSearch] = useState("");
  const [catalogOpen, setCatalogOpen] = useState(true);
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
        <div className="flex items-center gap-2 rounded-md px-3 py-2" style={{ border: "1px solid var(--b1)", background: "var(--bg-2)" }}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--t4)" strokeWidth="2" strokeLinecap="round">
            <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            placeholder="Search tables &amp; columns…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="aug-fs-sm w-full bg-transparent outline-none placeholder-zinc-500" style={{ color: "var(--t2)" }}
          />
          {search && (
            <Button
              variant="ghost" size="xs" onClick={() => setSearch("")}
              className="h-auto p-0 font-normal leading-none hover:bg-transparent dark:hover:bg-transparent" style={{ color: "var(--t4)" }}
            >
              ✕
            </Button>
          )}
        </div>
        {/* The same legend the builder shows, so a dot means one thing product-wide. */}
        <div className="mt-2.5 flex items-center gap-3">
          {([["bg-emerald-500", "num"], ["bg-blue-400", "date"], ["bg-zinc-500", "text"]] as const).map(([d, l]) => (
            <span key={l} className="aug-fs-xs flex items-center gap-1.5" style={{ color: "var(--t4)" }}>
              <span className={`h-2 w-2 rounded-[var(--r-pill)] ${d}`} />{l}
            </span>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto py-1">
        {tables.length === 0 && (
          <p className="aug-fs-sm px-4 py-4" style={{ color: "var(--t4)" }}>{emptyLabel}</p>
        )}
        {tables.length > 0 && visible.length === 0 && (
          <p className="aug-fs-sm px-4 py-4" style={{ color: "var(--t4)" }}>No match.</p>
        )}

        {catalogName && (
          <Button
            variant="ghost"
            onClick={() => setCatalogOpen(o => !o)}
            className="h-auto w-full justify-start gap-2 px-2 py-1.5 font-normal hover:bg-[var(--bg-hover)]"
          >
            <Chevron open={catalogOpen} />
            <IcoCatalog color="var(--t2)" size={14} />
            <span className="aug-fs-sm truncate font-medium" style={{ color: "var(--t1)" }}>
              {catalogName}
            </span>
            <span className="aug-fs-xs ml-auto shrink-0" style={{ color: "var(--t4)" }}>
              {tables.length}
            </span>
          </Button>
        )}

        {(!catalogName || catalogOpen) && grouped.map(([schema, schemaTables]) => {
          const sOpen = searching || openSchemas.has(schema) || schema === "";
          return (
            <div key={schema || "(root)"}>
              {schema !== "" && (
                <Button
                  variant="ghost"
                  onClick={() => toggle(openSchemas, schema, setOpenSchemas)}
                  className={`h-auto w-full justify-start gap-2 py-1.5 pr-2 font-normal hover:bg-[var(--bg-hover)] ${catalogName ? "pl-6" : "pl-3"}`}
                >
                  <Chevron open={sOpen} />
                  <IcoSchema color="var(--blue3)" />
                  {/* Rendered as STORED, not uppercased. The Catalog screen shows
                      `luxexperience`; QueryBuilder shows `LUXEXPERIENCE`; they are the
                      same schema. Beyond the inconsistency, a schema name is an
                      identifier — in several dialects its case is significant, so
                      shouting it is a small lie about what you would have to type. */}
                  <span className="aug-fs-sm truncate font-mono" style={{ color: "var(--t2)" }}>
                    {schema}
                  </span>
                  <span className="aug-fs-xs ml-auto shrink-0" style={{ color: "var(--t4)" }}>
                    {schemaTables.length}
                  </span>
                </Button>
              )}

              {sOpen && schemaTables.map(t => {
                const tOpen = searching || openTables.has(t.name);
                const { bare } = splitName(t.name);
                const rc = fmtRows(t.rowCount);
                return (
                  <div key={t.name}>
                    <div className={`group/tbl flex w-full items-center gap-2 py-1.5 pr-2 transition hover:bg-[var(--bg-hover)] ${catalogName ? "pl-11" : "pl-7"}`}>
                      <Button
                        variant="ghost"
                        onClick={() => toggle(openTables, t.name, setOpenTables)}
                        title={tOpen ? "Collapse columns" : "Expand columns"}
                        className="h-auto p-0 font-normal hover:bg-transparent dark:hover:bg-transparent"
                      >
                        <Chevron open={tOpen} />
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => onSelectTable?.(t.name)}
                        title={onSelectTable ? `Insert ${t.name} at the cursor` : t.name}
                        className="h-auto min-w-0 flex-1 justify-start gap-2 p-0 font-normal hover:bg-transparent dark:hover:bg-transparent"
                      >
                        <IcoTable />
                        <span className="aug-fs-sm truncate font-mono" style={{ color: "var(--t1)" }}>{bare}</span>
                        {rc && <span className="aug-fs-xs shrink-0" style={{ color: "var(--t4)" }}>{rc}</span>}
                      </Button>
                      {(t.joinDegree ?? 0) > 0 && (
                        <span
                          title={`${t.joinDegree} related table${(t.joinDegree ?? 0) > 1 ? "s" : ""}`}
                          className="aug-fs-xs hidden shrink-0 items-center gap-0.5 sm:flex" style={{ color: "var(--t4)" }}
                        >
                          ⋈{t.joinDegree}
                        </span>
                      )}
                      {t.isolated && (
                        <span title="No detected joins to other tables" className="aug-fs-xs shrink-0" style={{ color: "var(--t4)" }}>
                          isolated
                        </span>
                      )}
                      {renderTableActions?.(t)}
                    </div>

                    {tOpen && t.columns.map(c => (
                      <div key={c.name} className={`border-l pl-2 ${catalogName ? "ml-12" : "ml-7"}`} style={{ borderColor: "var(--b0)" }}>
                        <Button
                          variant="ghost"
                          onClick={() => onSelectColumn?.(c.name, t.name)}
                          title={onSelectColumn
                            ? `Insert ${c.name} at the cursor${c.type ? ` (${c.type})` : ""}`
                            : `${c.name}${c.type ? ` (${c.type})` : ""}`}
                          className="group h-auto w-full justify-start gap-2 px-3 py-1 font-normal hover:bg-[var(--bg-hover)]"
                        >
                          <span className={`h-2 w-2 shrink-0 rounded-[var(--r-pill)] ${dot(c.type ?? "")}`} />
                          <span className="aug-fs-sm flex-1 truncate text-left font-mono" style={{ color: "var(--t2)" }}>{c.name}</span>
                          {c.type && (
                            <span className="aug-fs-xs hidden shrink-0 font-mono uppercase group-hover:inline" style={{ color: "var(--t4)" }}>
                              {c.type.split(" ")[0].slice(0, 6)}
                            </span>
                          )}
                          {c.is_fk && <span className="aug-fs-xs shrink-0" style={{ color: "var(--t4)" }}>FK</span>}
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
