"use client";

/**
 * One catalog — or one schema of it — redone to `aughor-v2/CLARITY.md` (2026-10-12, the approved
 * `design-mockups/catalog.html` frame 2): a header line (name · what it is · its state · Ask about it · Tools ▾), then
 * Overview · Tables · Diagram · Docs · Settings. The Overview opens on four figures, what needs a person (only when
 * something does), rows by table beside what the platform knows, then the tables. The Diagram — the tables and the
 * joins between them — is a tab at schema scope and on a one-schema connection (2026-10-14: #610 had moved it into
 * Tools ▾, and the user read that as removed).
 *
 * Nothing the old panels did is gone: testing and removing the connection, Volumes and Permissions sit in Tools ▾;
 * the Briefings switch, the dataset program (layers, budget), a connector's sync and files in Settings; a schema's
 * profile in Tools ▾ as a tab of its own; the compiled schema documents in Docs. Reads on open are the
 * old ones plus two GETs over stores — the metrics and the ontology — never a warehouse query, never a model call; the
 * search index's status comes from the screen, which reads it once.
 */
import { useEffect, useMemo, useState } from "react";

import { Card, Chip, Empty, Figure, Figures, HBars, MUTED, NUM, NeedsRow, NeedsYou, ONE_LINE, Page, ROW, RULE } from "@/components/clarity/kit";
import {
  BriefingsToggle, ConnectorActions, FilterBox, PAIR, PanelHead, SchemaDocs, ShareBars, StateChip, TablesList, ToolsMenu,
  hasConnectorActions, useFavorite, type ToolItem,
} from "@/components/catalog/CatalogTools";
import { PermissionsPanel, VolumesPanel } from "@/components/catalog/MetastorePanels";
import { ConnectionProgram, SchemaProgram } from "@/components/DatasetProgram";
import { ERDiagram } from "@/components/ERDiagram";
import { ExplorationBadge } from "@/components/ExplorationBadge";
import { SchemaShape } from "@/components/SchemaShape";
import { Button } from "@/components/ui/button";
import { Pending } from "@/components/ui/motion";
import { Loading } from "@/components/ui/states";
import { TabStrip } from "@/components/ui/tab-strip";
import {
  deleteConnectionSchema, getMetrics, getOntology,
  type CatalogEntry, type CatalogSchemaInfo, type CatalogTableInfo, type Connection, type DatasetsView,
  type KnowledgeStatus, type Metric, type OntologyGraph, type RichSchema,
} from "@/lib/api";
import {
  duplicateWords, itemKey, scopeSummary, unsearchable, whatItIs, type Duplicate, type ScopeSummary, type ScopeTable,
} from "@/lib/catalogSummary";
import { compactNumber, countNoun, formatCount, formatTimestamp } from "@/lib/format";
import { dayWords } from "@/lib/home";
import { useRichSchema } from "@/lib/schema-context";
import { bare, schemaOf } from "@/lib/tableName";

type Tab = "overview" | "tables" | "docs" | "settings" | "diagram" | "profile" | "volumes" | "permissions";

const TAB_WORD: Record<Tab, string> = {
  overview: "Overview", tables: "Tables", docs: "Docs", settings: "Settings", diagram: "Diagram", profile: "Profile",
  volumes: "Volumes", permissions: "Permissions",
};

export function CatalogScope({ entry, schema, view, conn, dups, status, label, onOpenTable, onOpenSchema, onOpenCatalog,
  onProgramChanged, onAsk, onTest, testing, testResult, onDelete, onRemoved, onOpenDocuments }: {
  entry: CatalogEntry;
  /** One schema of the catalog; the whole catalog when absent. */
  schema?: CatalogSchemaInfo;
  view: DatasetsView | null | undefined;
  conn?: Connection;
  dups: Duplicate[];
  /** The search index's status, read once by the screen; null — the read failed. */
  status: KnowledgeStatus | null | undefined;
  label: (connType: string) => string;
  onOpenTable: (schema: string, table: CatalogTableInfo) => void;
  onOpenSchema: (schema: CatalogSchemaInfo) => void;
  onOpenCatalog: (connId: string) => void;
  onProgramChanged: () => void;
  onAsk?: (question: string) => void;
  onTest?: () => void;
  testing?: boolean;
  testResult?: boolean;
  onDelete?: () => void;
  onRemoved?: () => void;
  onOpenDocuments?: () => void;
}) {
  const connId = entry.conn_id;
  const [tab, setTab] = useState<Tab>("overview");
  const [metrics, setMetrics] = useState<Metric[] | null | undefined>(undefined);
  const [graphs, setGraphs] = useState<OntologyGraph[] | null | undefined>(undefined);
  const fav = useFavorite(schema ? itemKey.schema(connId, schema.name) : itemKey.catalog(connId));

  const schemaNames = (schema ? [schema.name] : entry.schemas.map(s => s.name)).join("\u0000");
  useEffect(() => {
    let alive = true;
    setMetrics(undefined);
    getMetrics(connId).then(m => { if (alive) setMetrics(m); }).catch(() => { if (alive) setMetrics(null); });
    return () => { alive = false; };
  }, [connId]);
  useEffect(() => {
    let alive = true;
    const names = schemaNames ? schemaNames.split("\u0000") : [];
    setGraphs(undefined);
    // Each schema's ontology as built — a read never builds; one not built is left out, and none built says so.
    Promise.all(names.map(s => getOntology(connId, s).catch(() => null))).then(gs => {
      if (!alive) return;
      const got = gs.filter((g): g is OntologyGraph => !!g);
      setGraphs(names.length && !got.length ? null : got);
    });
    return () => { alive = false; };
  }, [connId, schemaNames]);

  const summary = useMemo(() => scopeSummary({ entry, schema: schema?.name, view, metrics, ontology: graphs }),
    [entry, schema?.name, view, metrics, graphs]);
  const copy = dups.find(d => d.copy.id === connId && (!schema || d.copy.schemas.includes(schema.name)));
  const original = dups.find(d => d.of.id === connId && (!schema || d.of.schemas.includes(schema.name)));
  const docs = unsearchable(status).filter(g => g.connId === connId && (!schema || g.schemas.includes(schema.name)));
  const real = !entry.builtin && connId !== "samples";
  const multi = !schema && entry.schemas.length > 1;
  const name = schema ? schema.name : entry.name;
  const canRemoveSchema = !!schema && !!onRemoved && schema.name.toLowerCase() !== "main";

  const tools: ToolItem[] = [
    { label: "Test connection", onSelect: () => onTest?.(), hidden: !!schema || !real || !conn || !onTest, testId: "tool-test" },
    { label: "Sync and files", onSelect: () => setTab("settings"), hidden: !!schema || !real || !hasConnectorActions(entry.conn_type) },
    { label: "Profile", onSelect: () => setTab("profile"), hidden: !schema, title: "Each column's empty share, distinct values and shape" },
    { label: "Volumes", onSelect: () => setTab("volumes"), hidden: !!schema, title: "Files kept under this catalog" },
    { label: "Permissions", onSelect: () => setTab("permissions"), hidden: !!schema, title: "Which workspaces can read this catalog" },
    { label: fav.on ? "Remove from favorites" : "Add to favorites", onSelect: fav.toggle, apart: true },
    { label: "Remove connection…", onSelect: () => onDelete?.(), danger: true, apart: true, hidden: !!schema || !real || !conn || !onDelete },
    { label: "Remove schema…", danger: true, apart: true, hidden: !canRemoveSchema, onSelect: async () => {
      if (!schema) return;
      if (!confirm(`Remove the entire "${schema.name}" schema from the workspace? This drops all ${schema.tables.length} table(s), their files, and this dataset's saved intelligence (profile + exploration).`)) return;
      try { await deleteConnectionSchema(connId, schema.name); onRemoved?.(); }
      catch (e) { alert((e as Error).message); }
    } },
  ];

  // The diagram is a view in the strip, not a tool: at schema scope, and at a one-schema connection, which IS its
  // schema (the user, 2026-10-14 — #610 had put it behind Tools ▾, and a view behind a menu reads as removed).
  const diagramSchema = schema ?? (entry.schemas.length === 1 ? entry.schemas[0] : undefined);
  const tabs: Tab[] = ["overview", "tables", ...(diagramSchema ? ["diagram" as const] : []),
    ...(real ? ["docs" as const] : []), "settings",
    ...((["profile", "volumes", "permissions"] as const).filter(t => t === tab))];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden", background: "var(--bg-0)" }}>
      <PanelHead testId="catalog-scope-head" crumbs={schema ? [entry.name] : undefined} name={name}
        what={schema ? countNoun(schema.tables.length, "table") : whatItIs(entry, label, copy?.of.name)}
        chips={<>
          <StateChip s={summary.state} percent={summary.explored?.percent} />
          {testing ? <Chip>testing…</Chip>
            : testResult === true ? <Chip tone="up">✓ connection works</Chip>
            : testResult === false ? <Chip tone="down">✗ connection failed</Chip> : null}
        </>}
        actions={<>
          {onAsk && (
            <Button variant="secondary" size="xs" onClick={() => onAsk(schema
              ? `Tell me about the ${schema.name} schema in ${entry.name}` : `Tell me about ${entry.name}`)}>
              Ask about it
            </Button>
          )}
          <ToolsMenu items={tools} />
        </>} />
      <TabStrip label={`${name} views`} value={tab} onChange={setTab} style={{ padding: "0 14px", flexShrink: 0 }}
        tabs={tabs.map(t => ({ id: t, label: t === "tables" ? `Tables · ${formatCount(summary.tables.length)}` : TAB_WORD[t] }))} />

      {tab === "volumes" ? <VolumesPanel catalogId={connId} />
        : tab === "permissions" ? <PermissionsPanel catalogId={connId} />
        : tab === "profile" && schema ? (
          <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
            <SchemaShape connectionId={connId} schemaTables={schema.tables.map(t => t.name)} />
          </div>
        )
        : tab === "diagram" && diagramSchema ? <SchemaDiagram connId={connId} schema={diagramSchema} />
        : (
          <Page testId={`catalog-scope-${tab}`}>
            {tab === "overview" && (
              <Overview summary={summary} metricsRead={metrics} multi={multi}
                needs={[
                  copy && (
                    <NeedsRow key="copy" testId="needs-listed-twice" title={duplicateWords(copy)}
                      detail={`counted once in every figure${summary.explored?.percent != null ? ` · this copy is ${summary.explored.percent}% explored` : ""}`}
                      actions={<Button size="xs" variant="secondary" onClick={() => onOpenCatalog(copy.of.id)}>Compare</Button>} />
                  ),
                  original && (
                    <NeedsRow key="original" testId="needs-listed-twice"
                      title={`Its ${countNoun(original.tables, "table")} are also listed under ${original.copy.name}`}
                      detail="the same table names and row counts, read by a second connection"
                      actions={<Button size="xs" variant="secondary" onClick={() => onOpenCatalog(original.copy.id)}>Compare</Button>} />
                  ),
                  ...docs.map(g => (
                    <NeedsRow key="docs" testId="needs-unsearchable"
                      title={`${countNoun(g.documents, "document")} for it can't be searched`}
                      detail={`registered, but ${formatCount(g.missing)} of ${formatCount(g.claimed)} parts are missing from the search index`}
                      actions={real ? <Button size="xs" variant="ghost" onClick={() => setTab("docs")}>See them</Button> : undefined} />
                  )),
                  summary.waiting.length > 0 && (
                    <NeedsRow key="layers" testId="needs-layer"
                      title={summary.waiting.length === 1 ? "1 dataset waits for its layer"
                        : `${formatCount(summary.waiting.length)} datasets wait for their layers`}
                      detail={`${summary.waiting.join(", ")} — questions start once a person sets a layer`}
                      actions={<Button size="xs" variant="secondary" onClick={() => setTab("settings")}>Set it</Button>} />
                  ),
                  summary.held && (
                    <NeedsRow key="held" title="Exploration is held" detail={summary.held}
                      actions={<Button size="xs" variant="ghost" onClick={() => setTab("settings")}>Settings</Button>} />
                  ),
                  summary.budgetSpent && (
                    <NeedsRow key="budget" title="This month's exploration budget is spent" detail={summary.budgetSpent}
                      actions={<Button size="xs" variant="ghost" onClick={() => setTab("settings")}>Settings</Button>} />
                  ),
                ].filter(Boolean)}
                onOpen={t => onOpenTable(t.schema, { name: t.name, row_count: t.rows })}
                onAll={() => setTab("tables")} />
            )}
            {tab === "tables" && (
              <TablesTab summary={summary} schemas={multi ? entry.schemas : []}
                onOpen={t => onOpenTable(t.schema, { name: t.name, row_count: t.rows })} onOpenSchema={onOpenSchema} />
            )}
            {tab === "docs" && (
              <Card label="Schema documents" right="compiled by the platform" testId="catalog-scope-docs">
                <SchemaDocs connId={connId} name={name} schema={schema?.name} onOpenDocuments={onOpenDocuments} />
              </Card>
            )}
            {tab === "settings" && (
              schema ? (
                <Card label="Layer and analysis" testId="catalog-schema-settings"
                  right={connId !== "samples" ? <ExplorationBadge connectionId={connId} className="pl-0 mt-0" /> : undefined}>
                  <SchemaProgram connId={connId} ds={view?.schemas.find(s => s.name === schema.name)} view={view ?? null}
                    onChanged={onProgramChanged} />
                  {!view && <Empty>{view === null ? "Its datasets could not be read." : "Reading its datasets…"}</Empty>}
                </Card>
              ) : (
                <>
                  {real && conn && (
                    <Card label="Connection" testId="catalog-settings-connection">
                      <div style={ROW}>
                        {onTest && <Button variant="secondary" size="xs" onClick={onTest} disabled={testing}>
                          {testing ? "Testing…" : "Test connection"}</Button>}
                        {testResult === true && <Chip tone="up">✓ connection works</Chip>}
                        {testResult === false && <Chip tone="down">✗ connection failed</Chip>}
                        {onDelete && <Button variant="destructive" size="xs" onClick={onDelete} style={{ marginLeft: "auto" }}>
                          Remove connection…</Button>}
                      </div>
                    </Card>
                  )}
                  {connId !== "samples" && (
                    <Card label="Briefing" testId="catalog-settings-briefing"><BriefingsToggle connId={connId} /></Card>
                  )}
                  {connId !== "samples" && (
                    <section aria-label="Exploration" data-testid="catalog-settings-exploration"
                      style={{ background: "var(--bg-2)", border: "1px solid var(--card-edge)", borderRadius: "var(--r3)", overflow: "hidden" }}>
                      <ConnectionProgram connId={connId} view={view ?? null} onChanged={onProgramChanged} />
                      <ExplorationBadge connectionId={connId} className="pb-3" />
                      {!view && <div style={{ padding: "0 16px 12px" }}>
                        <Empty>{view === null ? "Its datasets could not be read." : "Reading its datasets…"}</Empty></div>}
                    </section>
                  )}
                  {real && hasConnectorActions(entry.conn_type) && (
                    <Card label="Sync and files" testId="catalog-settings-connector">
                      <ConnectorActions connId={connId} connType={entry.conn_type} />
                    </Card>
                  )}
                </>
              )
            )}
          </Page>
        )}
    </div>
  );
}

// ── The Overview ──────────────────────────────────────────────────────────────────────────────────────────────────

const OVERVIEW_ROWS = 12;

function Overview({ summary: s, metricsRead, multi, needs, onOpen, onAll }: {
  summary: ScopeSummary;
  metricsRead: Metric[] | null | undefined;
  multi: boolean;
  needs: React.ReactNode[];
  onOpen: (t: ScopeTable) => void;
  onAll: () => void;
}) {
  const counted = s.tables.filter(t => t.rows != null);
  const last = s.lastRun;
  return (
    <>
      <Figures testId="catalog-scope-figures">
        <Figure label="Tables" value={formatCount(s.tables.length)} testId="fig-scope-tables"
          sub={s.stages || (s.state.word === "reading…" ? "reading…" : s.state.word === "not read" ? "its maturity could not be read" : "")} />
        <Figure label="Rows" value={s.rows == null ? "—" : compactNumber(s.rows)} testId="fig-scope-rows"
          sub={s.rows == null ? (s.tables.length ? "not counted" : "no table")
            : `${formatCount(s.rows)} in all${s.uncounted ? ` · ${formatCount(s.uncounted)} not counted` : ""}`} />
        <Figure label="Metrics" value={s.metrics == null ? "—" : formatCount(s.metrics)} testId="fig-scope-metrics"
          title="Approved metrics that read it"
          sub={metricsRead === undefined ? "reading…" : s.metrics == null ? "could not be read"
            : !s.metrics ? "no approved metric reads it"
            : s.newest ? `approved · newest ${s.newest.grain} ${dayWords(s.newest.through)}` : "approved · none watched yet"} />
        <Figure label="Last explored" value={last ? dayWords(last.at) : "—"} testId="fig-scope-explored"
          title={last ? formatTimestamp(last.at) : undefined}
          sub={last ? `${countNoun(last.newFindings, "new finding")} · ${last.outcome === "complete"
            ? (last.failures ? `${countNoun(last.failures, "failure")}` : "nothing failed") : `the run ${last.outcome}`}`
            : s.state.word === "reading…" ? "reading…" : "not explored yet"} />
      </Figures>

      {needs.length > 0 && <NeedsYou testId="catalog-scope-needs" right={countNoun(needs.length, "item")}>{needs}</NeedsYou>}

      <div style={PAIR}>
        <Card label="Rows by table" testId="catalog-scope-rows" style={{ flex: "1 1 340px" }}
          right={s.uncounted ? `${formatCount(s.uncounted)} not counted` : "by rows"}>
          {counted.length ? (
            <HBars bars={counted.slice(0, 10).map(t => ({
              key: t.key, name: <span style={{ fontFamily: "var(--font-mono)" }}>{t.name}</span>,
              meta: t.object?.words ?? (multi ? t.schema : undefined), value: t.rows as number,
              shown: compactNumber(t.rows as number), tip: `${t.schema}.${t.name}: ${formatCount(t.rows)} rows`,
            }))} />
          ) : <Empty>None of its tables carries a row count.</Empty>}
          {counted.length > 10 && <div className="aug-fs-xs" style={{ ...MUTED, marginTop: 8 }}>
            {`and ${countNoun(counted.length - 10, "smaller table")}`}</div>}
        </Card>
        <Card label="What the platform knows" testId="catalog-scope-knows" style={{ flex: "1 1 340px" }}>
          <ShareBars rows={s.knows} />
          {s.newest && (
            <div className="aug-fs-xs" style={{ ...MUTED, marginTop: 10 }}>
              {`Newest ${s.newest.grain}: ${dayWords(s.newest.through)} · read ${formatTimestamp(s.newest.readAt, "short")}`}
            </div>
          )}
        </Card>
      </div>

      <Card label={countNoun(s.tables.length, "table")} right="by rows" testId="catalog-scope-tables">
        <TablesList tables={s.tables.slice(0, OVERVIEW_ROWS)} onOpen={onOpen} showSchema={multi} />
        {s.tables.length > OVERVIEW_ROWS && (
          <div style={{ ...ROW, paddingTop: 8 }}>
            <Button variant="ghost" size="xs" onClick={onAll}>{`All ${formatCount(s.tables.length)} tables`}</Button>
          </div>
        )}
      </Card>
    </>
  );
}

// ── Tables: a filter column of schemas, the list beside it ───────────────────────────────────────────────────────

function TablesTab({ summary, schemas, onOpen, onOpenSchema }: {
  summary: ScopeSummary; schemas: CatalogSchemaInfo[]; onOpen: (t: ScopeTable) => void;
  onOpenSchema: (s: CatalogSchemaInfo) => void;
}) {
  const [filter, setFilter] = useState("");
  const [only, setOnly] = useState<string | null>(null);
  const q = filter.toLowerCase();
  const list = summary.tables.filter(t => (!only || t.schema === only)
    && (!q || t.name.toLowerCase().includes(q) || (t.object?.words.toLowerCase().includes(q) ?? false)));
  const max = Math.max(1, ...schemas.map(s => s.tables.length));
  const chosen = schemas.find(s => s.name === only);
  const listCard = (
    <Card label={list.length === summary.tables.length ? countNoun(list.length, "table") : `${formatCount(list.length)} of ${formatCount(summary.tables.length)} tables`}
      right={<FilterBox value={filter} onChange={setFilter} placeholder="Filter tables…" width={200} />} testId="catalog-tables-tab"
      style={{ flex: "1 1 480px" }}>
      {list.length ? <TablesList tables={list} onOpen={onOpen} showSchema={schemas.length > 1} />
        : <Empty>{q ? "No table matches that filter." : "No tables."}</Empty>}
    </Card>
  );
  if (schemas.length < 2) return listCard;
  return (
    <div style={PAIR}>
      <Card label="Schemas" testId="catalog-tables-schemas" style={{ flex: "0 1 230px" }}>
        {[{ name: null as string | null, n: summary.tables.length }, ...schemas.map(s => ({ name: s.name as string | null, n: s.tables.length }))]
          .map((row, i) => {
            const on = only === row.name;
            return (
              <Button key={row.name ?? "\u0000all"} variant="ghost" onClick={() => setOnly(row.name)} aria-pressed={on}
                style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: "3px 8px", width: "100%", height: "auto",
                  padding: "6px 8px", margin: 0, textAlign: "left", fontWeight: 400, borderRadius: "var(--r2)",
                  background: on ? "var(--blue1)" : undefined, ...(i ? {} : { marginBottom: 4 }) }}>
                <span className="aug-fs-sm" style={{ ...ONE_LINE, color: "var(--t1)" }}>{row.name ?? "All schemas"}</span>
                <span className="aug-fs-xs" style={{ ...MUTED, ...NUM }}>{formatCount(row.n)}</span>
                {row.name && (
                  <span aria-hidden style={{ gridColumn: "1 / span 2", display: "block", height: 6, borderRadius: 3, background: "var(--bg-3)" }}>
                    <i style={{ display: "block", height: "100%", borderRadius: 3, width: `${(row.n / max) * 100}%`,
                      background: on ? "var(--blue3)" : "var(--chart-deemph)" }} />
                  </span>
                )}
              </Button>
            );
          })}
        {chosen && (
          <div style={{ ...RULE, paddingTop: 8, marginTop: 6 }}>
            <Button variant="secondary" size="xs" onClick={() => onOpenSchema(chosen)}>{`Open ${chosen.name}`}</Button>
          </div>
        )}
      </Card>
      {listCard}
    </div>
  );
}

// ── A schema's diagram ────────────────────────────────────────────────────────────────────────────────────────────

/** The schema's tables and their joins, from the one rich-schema read the catalog shares. The rich schema names tables
 *  fully qualified while the tree lists bare names, so they are matched on the bare name within this schema. */
function SchemaDiagram({ connId, schema }: { connId: string; schema: CatalogSchemaInfo }) {
  const { schema: full, loading, error } = useRichSchema(connId);
  const scoped = useMemo<RichSchema | null>(() => {
    if (!full) return null;
    const allowed = new Set(schema.tables.map(t => bare(t.name)));
    const inSchema = (n: string) => {
      const s = schemaOf(n);
      return (!s || s === schema.name.toLowerCase()) && allowed.has(bare(n));
    };
    return {
      tables: full.tables.filter(t => inSchema(t.name)),
      joins: full.joins.filter(j => inSchema(j.t1) && inSchema(j.t2)),
      isolated: full.isolated?.filter(n => inSchema(n)) ?? [],
      warnings: full.warnings ?? [],
    };
  }, [full, schema]);
  if (loading) return <div style={{ ...ROW, justifyContent: "center", flex: 1 }}><Pending /><Loading what="the diagram" inline /></div>;
  if (error || !scoped) return <div style={{ padding: "16px 22px" }}><Empty>{error ? "The diagram could not be read." : "No diagram for this schema."}</Empty></div>;
  return <div style={{ flex: 1, minHeight: 0, overflow: "hidden" }}><ERDiagram schema={scoped} /></div>;
}
