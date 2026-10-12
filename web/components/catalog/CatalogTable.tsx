"use client";

/**
 * One table — redone to `aughor-v2/CLARITY.md` (2026-10-12, the approved `design-mockups/catalog.html` frame 3): the
 * header line (catalog › schema › table · its business object · Ask about it · Tools ▾), then Overview · Columns ·
 * Sample · Findings · Docs · History. The Overview opens on four figures, then the business object's lifecycle beside
 * the columns with what each means and its marks.
 *
 * Every old tab is still here: the column list (with its type editor and each numeric column's distribution) and the
 * column profile under Columns, the sample grid under Sample, the column comments under Docs, the table's layer and
 * on/off switch under History with its schema's runs. The lifecycle shows its states and which end it — not how many
 * objects sit in each: no read this panel makes returns that, and a count is never invented.
 */
import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Card, Chip, Dot, Empty, Figure, Figures, Label, MUTED, NUM, ONE_LINE, Page, ROW, RULE } from "@/components/clarity/kit";
import {
  ColumnDistribution, FilterBox, LIST_CELL, LIST_HEAD, PAIR, PanelHead, SampleGrid, ToolsMenu, useFavorite, type ToolItem,
} from "@/components/catalog/CatalogTools";
import { GlossaryPanel } from "@/components/catalog/GlossaryPanel";
import { programLine, TableProgram } from "@/components/DatasetProgram";
import { Chevron } from "@/components/icons/catalog";
import { ColumnTypeIcon } from "@/components/icons/columnType";
import { SchemaShape } from "@/components/SchemaShape";
import { Button } from "@/components/ui/button";
import { SkeletonRows } from "@/components/ui/motion";
import { Segmented } from "@/components/ui/segmented";
import { SelectField } from "@/components/ui/select";
import { Loading, ReadFailed } from "@/components/ui/states";
import { TabStrip } from "@/components/ui/tab-strip";
import {
  alterColumn, deleteConnectionTable, getExplorationFindings, getMetrics, getOntology, getSchemaRich, getTableColumns,
  type CatalogTableInfo, type DatasetsView, type DistributionProfile, type Metric, type OntologyGraph,
  type SchemaColumn, type SchemaTable, type TableColumn,
} from "@/lib/api";
import {
  approvedMetrics, columnMarks, columnRows, findingsAbout, findingsIn, itemKey, lifecycleOf, metricsReading, objectFor,
  objectWords, objectsByTable, ofCount, type ColumnRow, type TableFinding,
} from "@/lib/catalogSummary";
import { compactNumber, countNoun, formatCount, isNumericType } from "@/lib/format";
import { dayWords } from "@/lib/home";
import { withUniqueKeys } from "@/lib/listKeys";
import { richSchemaKey, useRichSchema } from "@/lib/schema-context";
import { bare } from "@/lib/tableName";

/** The types a person may set a column to, in the Columns tab's editor. */
const TYPE_OPTIONS = [
  "VARCHAR", "TEXT", "INTEGER", "BIGINT", "SMALLINT", "TINYINT",
  "DOUBLE", "FLOAT", "DECIMAL", "NUMERIC", "BOOLEAN",
  "DATE", "TIMESTAMP", "TIME", "TIMESTAMPTZ", "INTERVAL",
  "BLOB", "JSON", "UUID",
];

type Tab = "overview" | "columns" | "sample" | "findings" | "docs" | "history";

export function CatalogTable({ connId, catalogName, schemaName, table, view, onAsk, onRemoved, onProgramChanged }: {
  connId: string;
  catalogName: string;
  schemaName: string;
  table: CatalogTableInfo;
  view: DatasetsView | null | undefined;
  onAsk?: (table: string, connId: string) => void;
  onRemoved?: () => void;
  onProgramChanged: () => void;
}) {
  const [tab, setTab] = useState<Tab>("overview");
  const [colsMode, setColsMode] = useState<"list" | "profile">("list");
  const [baseCols, setBaseCols] = useState<TableColumn[]>([]);
  const [colsLoading, setColsLoading] = useState(true);
  const [richTable, setRich] = useState<SchemaTable | null>(null);
  const [distMap, setDistMap] = useState<Record<string, DistributionProfile>>({});
  const [findings, setFindings] = useState<TableFinding[] | null | undefined>(undefined);
  const [findingsRead, setFindingsRead] = useState(0);
  const [metrics, setMetrics] = useState<Metric[] | null | undefined>(undefined);
  const [graph, setGraph] = useState<OntologyGraph | null | undefined>(undefined);
  const fav = useFavorite(itemKey.table(connId, schemaName, table.name));
  // One shared read per connection, serving the columns' descriptions and FK flags.
  const { schema: catalogSchema } = useRichSchema(connId);
  const qc = useQueryClient();

  // The authoritative column list comes from the per-table reader (the Sample's path); the connection's rich schema
  // only layers on FK flags and descriptions.
  useEffect(() => {
    setColsLoading(true);
    setBaseCols([]);
    getTableColumns(connId, table.name, schemaName)
      .then(setBaseCols)
      .catch(err => { console.error("[Catalog] getTableColumns failed:", err); setBaseCols([]); })
      .finally(() => setColsLoading(false));
  }, [connId, schemaName, table.name]);

  useEffect(() => { setRich(catalogSchema?.tables.find(t => t.name === table.name) ?? null); }, [catalogSchema, table.name]);

  // The explorer's read: each numeric column's distribution, and its findings. Its distributions are keyed
  // "<table>:<column>", where <table> may be schema-qualified, so they are matched on the bare name.
  useEffect(() => {
    let alive = true;
    setDistMap({});
    setFindings(undefined);
    getExplorationFindings(connId)
      .then(f => {
        if (!alive) return;
        const m: Record<string, DistributionProfile> = {};
        const target = bare(table.name);
        for (const [key, d] of Object.entries(f.distributions ?? {})) {
          const sep = key.lastIndexOf(":");
          if (sep < 0) continue;
          const tbl = key.slice(0, sep), col = key.slice(sep + 1);
          if (bare(tbl) === target && col && d.shape !== "unknown") m[col] = d;
        }
        setDistMap(m);
        setFindings(findingsIn(f));
      })
      .catch(() => { if (alive) { setDistMap({}); setFindings(null); } });
    return () => { alive = false; };
  }, [connId, table.name, findingsRead]);

  useEffect(() => {
    let alive = true;
    setMetrics(undefined);
    getMetrics(connId).then(m => { if (alive) setMetrics(m); }).catch(() => { if (alive) setMetrics(null); });
    return () => { alive = false; };
  }, [connId]);

  useEffect(() => {
    let alive = true;
    setGraph(undefined);
    getOntology(connId, schemaName).then(g => { if (alive) setGraph(g); }).catch(() => { if (alive) setGraph(null); });
    return () => { alive = false; };
  }, [connId, schemaName]);

  // Unify: the per-table columns, enriched with the rich schema's FK flags and descriptions.
  const enrich = new Map((richTable?.columns ?? []).map(c => [c.name, c]));
  const cols: SchemaColumn[] = baseCols.length
    ? baseCols.map(b => {
        const e = enrich.get(b.name);
        const type = b.type?.trim?.() ? b.type : undefined;
        return { ...(e ?? {}), name: b.name, type: type ?? e?.type ?? "" } as SchemaColumn;
      })
    : (richTable?.columns ?? []);

  const entity = useMemo(() => (graph ? objectFor(objectsByTable([graph]), [graph], schemaName, table.name) : null),
    [graph, schemaName, table.name]);
  const rows = columnRows(cols, entity, Object.values(graph?.relationships ?? {}), table.name);
  const lifecycle = lifecycleOf(entity);
  const ds = view?.schemas.find(s => s.name === schemaName);
  const dt = ds?.tables.find(t => t.name === table.name);
  const reading = metrics ? metricsReading(approvedMetrics(metrics, schemaName), table.name) : null;
  const questions = ofCount(dt?.maturity.questions.note, "questions");
  const about = findings ? findingsAbout(findings, table.name, entity?.id ?? null) : null;
  const objectName = entity ? objectWords(entity.id, entity.display_name) : null;

  const handleSave = async (colName: string, type: string) => {
    if (!type.trim() || type.trim() === (cols.find(c => c.name === colName)?.type ?? "")) return;
    const res = await alterColumn(connId, table.name, colName, type.trim(), schemaName);
    const [refreshed, rich] = await Promise.all([
      getTableColumns(connId, table.name, schemaName),
      // Deliberately NOT the cached read: this runs right after the ALTER and needs the shape after it. The cache is
      // invalidated below so every other reader stops serving the shape from before.
      getSchemaRich(connId).then(s => s.tables.find(t => t.name === table.name) ?? null).catch(() => null),
    ]);
    qc.invalidateQueries({ queryKey: richSchemaKey(connId) });
    setBaseCols(refreshed);
    if (rich) setRich(rich);
    // Honest when the change is a display-only override (a connector that cannot ALTER).
    if (res && res.applied === false && res.message) alert(res.message);
  };

  const tools: ToolItem[] = [
    { label: "Edit column types", onSelect: () => { setTab("columns"); setColsMode("list"); }, title: "Click a column's type to change it" },
    { label: "Profile its columns", onSelect: () => { setTab("columns"); setColsMode("profile"); },
      title: "Each column's empty share, distinct values and shape" },
    { label: fav.on ? "Remove from favorites" : "Add to favorites", onSelect: fav.toggle, apart: true },
    { label: "Remove table…", danger: true, apart: true, hidden: !onRemoved, testId: "tool-remove-table", onSelect: async () => {
      if (!confirm(`Remove table "${table.name}" from the workspace? This drops the table and deletes its uploaded file.`)) return;
      try { await deleteConnectionTable(connId, table.name, schemaName); onRemoved?.(); }
      catch (e) { alert((e as Error).message); }
    } },
  ];

  const TABS: { id: Tab; label: string }[] = [
    { id: "overview", label: "Overview" }, { id: "columns", label: "Columns" }, { id: "sample", label: "Sample" },
    { id: "findings", label: about?.length ? `Findings · ${formatCount(about.length)}` : "Findings" },
    { id: "docs", label: "Docs" }, { id: "history", label: "History" },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden", background: "var(--bg-0)" }}>
      <PanelHead testId="catalog-table-head" crumbs={[catalogName, schemaName]} name={table.name} mono
        chips={<>
          {objectName && <Chip title={`The business object read from ${table.name}`} testId="catalog-table-object">{objectName}</Chip>}
        </>}
        actions={<>
          {onAsk && <Button variant="secondary" size="xs" onClick={() => onAsk(table.name, connId)}>Ask about it</Button>}
          <ToolsMenu items={tools} />
        </>} />
      <TabStrip label={`${table.name} views`} value={tab} onChange={setTab} style={{ padding: "0 14px", flexShrink: 0 }} tabs={TABS} />

      {tab === "docs" ? (
        <GlossaryPanel table={bare(table.name)} columns={cols.map(c => c.name)} schema={schemaName} connectionId={connId} />
      ) : tab === "sample" ? (
        <SampleGrid connId={connId} tableName={table.name} schemaName={schemaName} />
      ) : tab === "columns" && colsMode === "profile" ? (
        <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div style={{ padding: "12px 22px 0" }}><ColumnsMode value={colsMode} onChange={setColsMode} /></div>
          <SchemaShape connectionId={connId} schemaTables={[table.name]} />
        </div>
      ) : (
        <Page testId={`catalog-table-${tab}`}>
          {tab === "overview" && (
            <>
              <Figures testId="catalog-table-figures">
                <Figure label="Rows" value={table.row_count == null ? "—" : compactNumber(Number(table.row_count))} testId="fig-table-rows"
                  sub={table.row_count == null ? "not counted" : `${formatCount(Number(table.row_count))} in all`} />
                <Figure label="Columns" value={colsLoading ? "—" : formatCount(cols.length)} testId="fig-table-columns"
                  sub={colsLoading ? "reading…" : cols.length ? columnMarks(rows) : "could not be read"} />
                <Figure label="Metrics read it" value={reading == null ? "—" : formatCount(reading)} testId="fig-table-metrics"
                  title="Approved metrics that read this table"
                  sub={metrics === undefined ? "reading…" : reading == null ? "could not be read"
                    : !reading ? "no approved metric reads it" : dt?.maturity.time.note ?? "approved"} />
                <Figure label="Questions" value={questions ? formatCount(questions.n) : "—"} testId="fig-table-questions"
                  sub={questions ? `of ${formatCount(questions.of)} asked of it`
                    : dt ? (dt.maturity.questions.note === "no question on its own" ? "none asked of it alone" : dt.maturity.questions.note)
                    : view === undefined ? "reading…" : "not read"} />
              </Figures>
              <div style={PAIR}>
                <Card label={lifecycle ? `Lifecycle · ${lifecycle.column}` : "Lifecycle"} testId="catalog-table-lifecycle"
                  style={{ flex: "1 1 260px" }}
                  right={lifecycle ? `${lifecycle.ends} of ${countNoun(lifecycle.states.length, "state")} end it` : undefined}>
                  {graph === undefined ? <Loading what="the ontology" />
                    : graph === null ? <Empty>The ontology is not built for this schema.</Empty>
                    : !entity ? <Empty>No business object is read from this table.</Empty>
                    : !lifecycle ? <Empty>{`${objectName} has no lifecycle the platform has read.`}</Empty>
                    : (
                      <>
                        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto" }}>
                          {lifecycle.states.map((s, i) => (
                            <div key={`${i}-${s.name}`} style={{ display: "contents" }}>
                              <span className="aug-fs-sm" style={{ ...ROW, flexWrap: "nowrap", padding: "6px 0", ...(i ? RULE : {}) }}>
                                <Dot hue={s.ends ? "grey" : "blue"} />{s.name}
                              </span>
                              <span className="aug-fs-xs" style={{ ...MUTED, padding: "6px 0", textAlign: "right", ...(i ? RULE : {}) }}>
                                {s.ends ? "ends" : "open"}
                              </span>
                            </div>
                          ))}
                        </div>
                        <div className="aug-fs-xs" style={{ ...MUTED, marginTop: 8 }}>How many sit in each state is not read here.</div>
                      </>
                    )}
                </Card>
                <Card label={`Columns · ${formatCount(cols.length)}`} testId="catalog-table-columns" style={{ flex: "2 1 460px" }}>
                  {colsLoading ? <SkeletonRows rows={5} />
                    : rows.length ? <ColumnsGrid rows={rows} />
                    : <Empty>Its columns could not be read.</Empty>}
                </Card>
              </div>
            </>
          )}
          {tab === "columns" && (
            <ColumnsList cols={cols} loading={colsLoading} distMap={distMap} onSave={handleSave}
              mode={<ColumnsMode value={colsMode} onChange={setColsMode} />} />
          )}
          {tab === "findings" && (
            <Card label={about ? countNoun(about.length, "finding") : "Findings"} right="what the explorer found reading it"
              testId="catalog-table-findings">
              {findings === undefined ? <Loading what="the findings" />
                : findings === null || !about ? <ReadFailed what="the findings" onRetry={() => setFindingsRead(n => n + 1)} />
                : about.length === 0 ? <Empty>No finding has read this table yet.</Empty>
                : withUniqueKeys(about, f => f.id).map(([key, f], i) => (
                  <div key={key} data-testid="catalog-table-finding" style={{ padding: "8px 0", ...(i ? RULE : {}) }}>
                    <div style={{ ...ROW, flexWrap: "nowrap" }}>
                      <span className="aug-fs-sm" title={f.question || f.angle} style={{ ...ONE_LINE, color: "var(--t1)", fontWeight: 500 }}>
                        {f.angle && f.angle !== "pinned-question" ? f.angle : f.question || f.domain || "Finding"}
                      </span>
                      {f.domain && <Chip>{f.domain}</Chip>}
                      {f.generated_at && <span className="aug-fs-xs" style={{ ...MUTED, marginLeft: "auto", whiteSpace: "nowrap" }}>
                        {dayWords(f.generated_at)}</span>}
                    </div>
                    <div className="aug-fs-sm" title={f.finding} style={{ color: "var(--t2)", ...ONE_LINE }}>{f.finding}</div>
                  </div>
                ))}
            </Card>
          )}
          {tab === "history" && (
            <>
              <Card label="Layer and analysis" testId="catalog-table-history">
                {view === undefined ? <Loading what="its datasets" />
                  : view === null ? <Empty>Its datasets could not be read.</Empty>
                  : !dt ? <Empty>The datasets do not list this table.</Empty>
                  : <TableProgram connId={connId} schema={schemaName} t={dt} view={view} schemaOff={!!ds?.off} onChanged={onProgramChanged} />}
              </Card>
              <Card label={`Runs over ${schemaName}`} testId="catalog-table-runs">
                {ds ? (programLine(ds).length
                  ? programLine(ds).map((l, i) => (
                    <div key={`${i}-${l}`} className="aug-fs-sm" style={{ color: "var(--t2)", padding: "6px 0", ...(i ? RULE : {}) }}>{l}</div>
                  ))
                  : <Empty>Nothing has run over it yet.</Empty>)
                  : <Empty>{view === undefined ? "Reading…" : "Not read."}</Empty>}
              </Card>
            </>
          )}
        </Page>
      )}
    </div>
  );
}

function ColumnsMode({ value, onChange }: { value: "list" | "profile"; onChange: (v: "list" | "profile") => void }) {
  return <Segmented label="Columns view" value={value} onChange={onChange}
    options={[{ value: "list", label: "List" }, { value: "profile", label: "Profile", title: "Each column's empty share, distinct values and shape" }]} />;
}

// ── The Overview's columns: what each means, and its marks ───────────────────────────────────────────────────────

const COLS_GRID = {
  display: "grid", gridTemplateColumns: "minmax(110px, 160px) minmax(70px, 100px) minmax(0, 1fr) auto",
  columnGap: 0, alignItems: "stretch",
} as const;
const HEAD = LIST_HEAD;
const CELL = { ...LIST_CELL, padding: "7px 12px 7px 2px" };

function ColumnsGrid({ rows }: { rows: ColumnRow[] }) {
  return (
    <div className="aug-fs-sm" style={COLS_GRID}>
      <span className="aug-fs-xs" style={HEAD}>Column</span>
      <span className="aug-fs-xs" style={HEAD}>Type</span>
      <span className="aug-fs-xs" style={HEAD}>Means</span>
      <span className="aug-fs-xs" style={HEAD} />
      {withUniqueKeys(rows, r => r.name).map(([key, r]) => (
        <div key={key} style={{ display: "contents" }}>
          <span style={{ ...CELL, ...ONE_LINE, fontFamily: "var(--font-mono)", color: "var(--t1)" }} title={r.name}>{r.name}</span>
          <span style={{ ...CELL, ...ONE_LINE, fontFamily: "var(--font-mono)", color: "var(--t3)" }} title={r.type}>{r.type || "—"}</span>
          <span style={{ ...CELL, ...ONE_LINE, color: r.means ? "var(--t2)" : "var(--t3)" }} title={r.means || undefined}>
            {r.means || "—"}</span>
          <span style={{ ...CELL, ...ROW, flexDirection: "row", flexWrap: "nowrap", justifyContent: "flex-end" }}>
            {r.key && <Chip>✓ key</Chip>}
            {r.link && <Chip tone="accent" title={`Links to ${r.link}`}>{`→ ${r.link}`}</Chip>}
            {r.states != null && <Chip title="Its business object's lifecycle states">{countNoun(r.states, "state")}</Chip>}
            {r.time && <Chip>time</Chip>}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Columns: the list, its type editor and each numeric column's distribution ────────────────────────────────────

function ColumnsList({ cols, loading, distMap, onSave, mode }: {
  cols: SchemaColumn[];
  loading: boolean;
  distMap: Record<string, DistributionProfile>;
  onSave: (col: string, type: string) => Promise<void>;
  mode: React.ReactNode;
}) {
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState<string | null>(null);
  const [editType, setEditType] = useState("");
  const [busy, setBusy] = useState(false);
  const q = filter.toLowerCase();
  const shown = q ? cols.filter(c => c.name.toLowerCase().includes(q) || c.type.toLowerCase().includes(q)) : cols;
  // A distribution only means something for a numeric column — gated on its live type, so a VARCHAR id never shows
  // percentiles and a column just changed to VARCHAR stops showing its stale one.
  const dist = (c: SchemaColumn) => (isNumericType(c.type) ? distMap[c.name] : undefined);
  const profiled = cols.filter(dist).length;
  const save = async (name: string) => {
    setBusy(true);
    try { await onSave(name, editType); }
    catch (e) { alert((e as Error).message || "Failed to alter column"); }
    finally { setBusy(false); setEditing(null); }
  };

  return (
    <section aria-label="Columns" data-testid="catalog-columns-list"
      style={{ background: "var(--bg-2)", border: "1px solid var(--card-edge)", borderRadius: "var(--r3)", padding: "12px 14px" }}>
      <div style={{ ...ROW, marginBottom: 8 }}>
        {mode}
        <FilterBox value={filter} onChange={setFilter} placeholder="Filter columns…" width={200} />
        <span className="aug-fs-xs" style={{ ...MUTED, marginLeft: "auto" }}>
          {profiled ? `${profiled} profiled · open a column for its distribution · click a type to change it` : "click a type to change it"}
        </span>
      </div>
      <Label right={countNoun(cols.length, "column")}>Columns</Label>
      {loading ? <SkeletonRows rows={6} />
        : shown.length === 0 ? <Empty>{q ? "No column matches that filter." : "Its columns could not be read."}</Empty>
        : withUniqueKeys(shown, c => c.name).map(([key, c], i) => {
          const d = dist(c);
          const isOpen = open.has(c.name);
          return (
            <div key={key} style={i ? RULE : undefined}>
              <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 150px 44px", alignItems: "center", padding: "6px 2px" }}>
                <div style={{ ...ROW, flexWrap: "nowrap", minWidth: 0 }} title={c.description || ""}>
                  <span style={{ width: 16, flexShrink: 0, display: "flex" }}>
                    {d && (
                      <Button variant="ghost" size="icon-xs" aria-expanded={isOpen} aria-label={`${c.name}'s distribution`}
                        onClick={() => setOpen(p => { const n = new Set(p); if (n.has(c.name)) n.delete(c.name); else n.add(c.name); return n; })}>
                        <Chevron open={isOpen} />
                      </Button>
                    )}
                  </span>
                  <ColumnTypeIcon type={c.type} size={13} />
                  <span className="aug-fs-sm" style={{ fontFamily: "var(--font-mono)", color: "var(--t1)", ...ONE_LINE }}>{c.name}</span>
                  {c.description && <span className="aug-fs-xs" style={{ ...MUTED, ...ONE_LINE, maxWidth: 260 }}>{c.description}</span>}
                </div>
                {editing === c.name ? (
                  <div style={{ ...ROW, flexWrap: "nowrap", gap: 4 }}>
                    <SelectField value={editType} onChange={e => setEditType(e.target.value)} autoFocus style={{ width: 110 }}
                      aria-label={`${c.name}'s type`}
                      onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); save(c.name); } if (e.key === "Escape") setEditing(null); }}>
                      {TYPE_OPTIONS.map(t => <option key={t} value={t}>{t}</option>)}
                    </SelectField>
                    <Button variant="secondary" size="xs" disabled={busy} onClick={() => save(c.name)}>Save</Button>
                  </div>
                ) : (
                  <Button variant="ghost" size="xs" title="Change its type" onClick={() => { setEditing(c.name); setEditType(c.type); }}
                    style={{ justifyContent: "flex-start", fontFamily: "var(--font-mono)", color: "var(--t3)", ...NUM }}>
                    {c.type || "—"}
                  </Button>
                )}
                <span style={{ justifySelf: "end" }}>{c.is_fk ? <Chip tone="accent" title="Links to another table">link</Chip> : null}</span>
              </div>
              {d && isOpen && <ColumnDistribution d={d} />}
            </div>
          );
        })}
    </section>
  );
}
