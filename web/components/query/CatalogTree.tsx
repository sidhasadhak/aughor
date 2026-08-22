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
 * props, which is what lets PR E serve QueryBuilder's rail from this component without
 * dragging `primaryTable` / auto-join / `addDim` into a shared module — those are the
 * builder's own `renderTableActions` / `renderColumnActions`, while the SQL editor
 * passes none and gets the plain catalog.
 *
 * PR E added five props, each standing for one affordance the builder's rail had and
 * this tree did not: a column's drag payload (`onColumnDragStart`), the D/M buttons
 * (`renderColumnActions`), the resolved-table highlight (`isTableActive`), the verb a
 * row's tooltip uses (`actionLabel`), and `loading`. They are all optional and all
 * inert for a caller that passes none — the SQL editor's rail renders as it did.
 *
 * The builder's fifth affordance, an on-demand column fetch, is deliberately NOT here.
 * It existed because that rail listed tables from `/catalog/tree`, which knows table
 * names and no columns. This tree is fed from the rich schema, where a table arrives
 * WITH its columns, so the fetch had nothing left to fetch — the SQL sidebar has run
 * without it since SE-2. An empty column list is now reported, not papered over.
 */
import { useMemo, useState } from "react";
import Fuse from "fuse.js";
import { compactNumber } from "@/lib/format";
import { Chevron, IcoCatalog, IcoSchema, IcoTable } from "@/components/icons/catalog";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";

export interface CatalogColumn {
  name: string;
  type?: string;
  is_fk?: boolean;
}

export interface CatalogTable {
  /** Qualified name as the warehouse spells it — what insertion uses. */
  name: string;
  /** The schema this table groups under, when the caller already knows it.
   *
   *  Without it the schema is parsed back out of `name`, which is fine for a caller
   *  whose names are qualified and wrong for one whose names are not. The builder keys
   *  tables by their BARE name and records the schema separately, so making it re-encode
   *  the schema into the name purely for this tree to split apart again would be a lie
   *  told to a parser — state the fact instead. */
  schema?: string;
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

/** Where a table groups, and what its row is labelled — the caller's `schema` wins
 *  over anything parsed out of the name. */
function placeOf(t: CatalogTable): { schema: string; bare: string } {
  const split = splitName(t.name);
  return t.schema == null ? split : { schema: t.schema, bare: split.bare };
}

/** The drag-handle dots, shown only on a column the caller made draggable — an
 *  affordance with no drag behind it is a promise the surface cannot keep. */
const GrabDots = () => (
  <span style={{ flexShrink: 0, color: "var(--t4)", display: "inline-flex" }}>
    <Icon name="grip" size={12} />
  </span>
);

export function CatalogTree({
  tables,
  catalogName,
  onSelectTable,
  onSelectColumn,
  renderTableActions,
  renderColumnActions,
  onColumnDragStart,
  isTableActive,
  actionLabel = name => `Insert ${name} at the cursor`,
  loading = false,
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
   *  this component never learns what a "primary table" is.
   *
   *  When given it REPLACES the default `isolated` badge rather than sitting beside it:
   *  the builder's status is one exclusive chain (primary → joined → isolated → add),
   *  and a row showing both "isolated" and "+ add" would be stating a fact and offering
   *  its contradiction in the same breath. `⋈n` is unaffected — a join degree is a
   *  catalog fact, true on every surface. */
  renderTableActions?: (table: CatalogTable) => React.ReactNode;
  /** Per-column affordances (the builder's D / M buttons). Rendered as a SIBLING of the
   *  column's click target, never inside it — a button nested in a button is invalid
   *  markup and the inner one's clicks would fight the outer one's. */
  renderColumnActions?: (column: CatalogColumn, table: CatalogTable) => React.ReactNode;
  /** Makes columns draggable and lets the caller write the payload. The wire format
   *  (`application/x-col`) stays with the builder that reads it — this tree knows only
   *  that a column can be picked up. */
  onColumnDragStart?: (e: React.DragEvent, column: CatalogColumn, table: CatalogTable) => void;
  /** Tables already in the caller's query: highlighted, and expanded by default so the
   *  columns you are working with are the ones in front of you. */
  isTableActive?: (table: CatalogTable) => boolean;
  /** What clicking a row DOES, for its tooltip. Insertion is the default because that is
   *  what the SQL editor does; Visual mode adds the row to the query instead, and a
   *  tooltip promising to insert at a cursor there would describe a different product. */
  actionLabel?: (name: string, kind: "table" | "column") => string;
  /** The catalog itself is still arriving. Distinct from an EMPTY catalog, which is a
   *  finished answer — showing "no tables" while they load reads as a broken connection. */
  loading?: boolean;
  emptyLabel?: string;
}) {
  const [search, setSearch] = useState("");
  const [catalogOpen, setCatalogOpen] = useState(true);
  // Records, not Sets: a node has THREE states — opened, closed, and never touched —
  // and only a record can tell the last two apart. A Set would make "not opened" and
  // "deliberately closed" the same value, so a default-open rule could never be
  // overridden by the user closing the thing.
  const [openSchemas, setOpenSchemas] = useState<Record<string, boolean>>({});
  const [openTables, setOpenTables] = useState<Record<string, boolean>>({});

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
      const { schema } = placeOf(t);
      const list = map.get(schema);
      if (list) list.push(t); else map.set(schema, [t]);
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [visible]);

  /** Schemas that own a table the caller is already querying. Such a table is drawn
   *  highlighted, and a highlight inside a collapsed parent is invisible. */
  const activeSchemas = useMemo(() => {
    if (!isTableActive) return new Set<string>();
    return new Set(visible.filter(isTableActive).map(t => placeOf(t).schema));
  }, [visible, isTableActive]);

  // A lone schema tier is pure friction: it says nothing you cannot already see and
  // costs a click to get past. Two or more IS a summary worth showing collapsed, so
  // the rule is the degenerate case rather than a threshold picked out of the air.
  const soleSchema = grouped.length === 1;

  // A search narrows to what matched, so everything it found should be visible without
  // a second click — expanding on search is the difference between a filter and a hunt.
  const searching = !!search.trim();
  const toggle = (
    open: Record<string, boolean>,
    key: string,
    fallback: boolean,
    apply: (next: Record<string, boolean>) => void,
  ) => apply({ ...open, [key]: !(open[key] ?? fallback) });

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0, flex: 1 }}>
      <div style={{ padding: "8px 10px 6px", flexShrink: 0 }}>
        <div className="flex items-center gap-2 rounded-md px-3 py-2" style={{ border: "1px solid var(--b1)", background: "var(--bg-2)" }}>
          <span style={{ color: "var(--t4)", display: "inline-flex" }}><Icon name="search" size={12} /></span>
          <input
            placeholder="Search tables &amp; columns…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="aug-fs-ui w-full bg-transparent outline-none placeholder-zinc-500" style={{ color: "var(--t2)" }}
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
            <span key={l} className="aug-fs-ui flex items-center gap-1.5" style={{ color: "var(--t4)" }}>
              <span className={`h-2 w-2 rounded-[var(--r-pill)] ${d}`} />{l}
            </span>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto py-1">
        {loading && tables.length === 0 && (
          <p className="aug-fs-ui animate-pulse px-4 py-4" style={{ color: "var(--t4)" }}>Loading catalog…</p>
        )}
        {!loading && tables.length === 0 && (
          <p className="aug-fs-ui px-4 py-4" style={{ color: "var(--t4)" }}>{emptyLabel}</p>
        )}
        {tables.length > 0 && visible.length === 0 && (
          <p className="aug-fs-ui px-4 py-4" style={{ color: "var(--t4)" }}>No match.</p>
        )}

        {catalogName && (
          <Button
            variant="ghost"
            onClick={() => setCatalogOpen(o => !o)}
            className="h-auto w-full justify-start gap-2 px-2 py-1.5 font-normal hover:bg-[var(--bg-hover)]"
          >
            <Chevron open={catalogOpen} />
            <IcoCatalog color="var(--t2)" size={14} />
            <span className="aug-fs-ui truncate font-medium" style={{ color: "var(--t1)" }}>
              {catalogName}
            </span>
            <span className="aug-fs-ui ml-auto shrink-0" style={{ color: "var(--t4)" }}>
              {tables.length}
            </span>
          </Button>
        )}

        {(!catalogName || catalogOpen) && grouped.map(([schema, schemaTables]) => {
          const sFallback = soleSchema || activeSchemas.has(schema) || schema === "";
          const sOpen = searching || (openSchemas[schema] ?? sFallback);
          return (
            <div key={schema || "(root)"}>
              {schema !== "" && (
                <Button
                  variant="ghost"
                  onClick={() => toggle(openSchemas, schema, sFallback, setOpenSchemas)}
                  className={`h-auto w-full justify-start gap-2 py-1.5 pr-2 font-normal hover:bg-[var(--bg-hover)] ${catalogName ? "pl-6" : "pl-3"}`}
                >
                  <Chevron open={sOpen} />
                  <IcoSchema color="var(--blue3)" />
                  {/* Rendered as STORED, not uppercased. The Catalog screen shows
                      `luxexperience`; QueryBuilder shows `LUXEXPERIENCE`; they are the
                      same schema. Beyond the inconsistency, a schema name is an
                      identifier — in several dialects its case is significant, so
                      shouting it is a small lie about what you would have to type. */}
                  <span className="aug-fs-ui truncate font-mono" style={{ color: "var(--t2)" }}>
                    {schema}
                  </span>
                  <span className="aug-fs-ui ml-auto shrink-0" style={{ color: "var(--t4)" }}>
                    {schemaTables.length}
                  </span>
                </Button>
              )}

              {sOpen && schemaTables.map(t => {
                const active = isTableActive?.(t) ?? false;
                const tOpen = searching || (openTables[t.name] ?? active);
                const { bare } = placeOf(t);
                const rc = fmtRows(t.rowCount);
                return (
                  <div key={t.name} style={active ? { background: "var(--bg-2)" } : undefined}>
                    <div className={`group/tbl flex w-full items-center gap-2 py-1.5 pr-2 transition hover:bg-[var(--bg-hover)] ${catalogName ? "pl-11" : "pl-7"}`}>
                      <Button
                        variant="ghost"
                        onClick={() => toggle(openTables, t.name, active, setOpenTables)}
                        title={tOpen ? "Collapse columns" : "Expand columns"}
                        className="h-auto p-0 font-normal hover:bg-transparent dark:hover:bg-transparent"
                      >
                        <Chevron open={tOpen} />
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => onSelectTable?.(t.name)}
                        title={onSelectTable ? actionLabel(t.name, "table") : t.name}
                        className="h-auto min-w-0 flex-1 justify-start gap-2 p-0 font-normal hover:bg-transparent dark:hover:bg-transparent"
                      >
                        <IcoTable active={active} />
                        <span
                          className={`aug-fs-ui truncate font-mono ${active ? "font-semibold" : ""}`}
                          style={{ color: "var(--t1)" }}
                        >
                          {bare}
                        </span>
                        {rc && <span className="aug-fs-ui shrink-0" style={{ color: "var(--t4)" }}>{rc}</span>}
                      </Button>
                      {(t.joinDegree ?? 0) > 0 && (
                        <span
                          title={`${t.joinDegree} related table${(t.joinDegree ?? 0) > 1 ? "s" : ""}`}
                          className="aug-fs-ui hidden shrink-0 items-center gap-0.5 sm:flex" style={{ color: "var(--t4)" }}
                        >
                          ⋈{t.joinDegree}
                        </span>
                      )}
                      {renderTableActions
                        ? renderTableActions(t)
                        : t.isolated && (
                          <span title="No detected joins to other tables" className="aug-fs-ui shrink-0" style={{ color: "var(--t4)" }}>
                            isolated
                          </span>
                        )}
                    </div>

                    {tOpen && t.columns.length === 0 && (
                      <div className={`py-1.5 ${catalogName ? "pl-14" : "pl-9"}`}>
                        <span className="aug-fs-ui" style={{ color: "var(--t4)" }}>
                          No columns available — the schema may need a refresh.
                        </span>
                      </div>
                    )}

                    {tOpen && t.columns.map(c => (
                      <div
                        key={c.name}
                        className={`group/col flex items-center border-l pr-2 transition hover:bg-[var(--bg-hover)] ${catalogName ? "ml-12" : "ml-7"} ${onColumnDragStart ? "cursor-grab select-none active:cursor-grabbing" : ""}`}
                        style={{ borderColor: "var(--b0)" }}
                        draggable={!!onColumnDragStart}
                        onDragStart={onColumnDragStart ? e => onColumnDragStart(e, c, t) : undefined}
                      >
                        <Button
                          variant="ghost"
                          onClick={() => onSelectColumn?.(c.name, t.name)}
                          title={onSelectColumn
                            ? `${actionLabel(c.name, "column")}${c.type ? ` (${c.type})` : ""}`
                            : `${c.name}${c.type ? ` (${c.type})` : ""}`}
                          className="h-auto min-w-0 flex-1 justify-start gap-2 py-1 pl-3 pr-0 font-normal hover:bg-transparent dark:hover:bg-transparent"
                        >
                          {onColumnDragStart && <GrabDots />}
                          <span className={`h-2 w-2 shrink-0 rounded-[var(--r-pill)] ${dot(c.type ?? "")}`} />
                          <span className="aug-fs-ui flex-1 truncate text-left font-mono" style={{ color: "var(--t2)" }}>{c.name}</span>
                          {c.type && (
                            <span className="aug-fs-ui hidden shrink-0 font-mono uppercase group-hover/col:inline" style={{ color: "var(--t4)" }}>
                              {c.type.split(" ")[0].slice(0, 6)}
                            </span>
                          )}
                          {c.is_fk && <span className="aug-fs-ui shrink-0" style={{ color: "var(--t4)" }}>FK</span>}
                        </Button>
                        {renderColumnActions?.(c, t)}
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
