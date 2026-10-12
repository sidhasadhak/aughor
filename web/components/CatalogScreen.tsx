"use client";

/**
 * CatalogScreen — the catalog tree on the left, and what is chosen in it on the right.
 *
 *  Section (Catalogs)
 *    └── Catalog  (one per connection)
 *          └── Schema
 *                └── Table
 *
 * Left panel  : the collapsible tree (its look and behaviour unchanged by the 2026-10-12 redo).
 * Right panel : redone to `aughor-v2/CLARITY.md` from the approved `design-mockups/catalog.html` —
 *   nothing chosen → every catalog (`catalog/CatalogHome.tsx`)
 *   a catalog or a schema → its page (`catalog/CatalogScope.tsx`)
 *   a table → its page (`catalog/CatalogTable.tsx`)
 * What the right panel says is folded in `lib/catalogSummary.ts`.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { SkeletonRows } from "@/components/ui/motion";
import { CONNECTORS } from "@/lib/connectors.gen";
import { useSchema } from "@/lib/schema-context";
import {
  getCatalogTree, addConnection, testConnection, getDatasets, getKnowledgeStatus,
  type CatalogTree, type CatalogEntry, type CatalogSchemaInfo, type CatalogTableInfo,
  type Connection, type DatasetsView, type KnowledgeStatus,
} from "@/lib/api";
import { MaturityBars } from "@/components/DatasetProgram";
import { AddDataPanel } from "@/components/AddDataPanel";
import { ResizableSplit } from "@/components/ResizableSplit";
import { Button } from "@/components/ui/button";
import { Chevron, IcoCatalog, IcoSchema, IcoTable } from "@/components/icons/catalog";
import { Icon } from "@/components/ui/icon";
import { SelectField } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { CatalogHome } from "@/components/catalog/CatalogHome";
import { CatalogScope } from "@/components/catalog/CatalogScope";
import { CatalogTable } from "@/components/catalog/CatalogTable";
import { recents } from "@/components/catalog/CatalogTools";
import { explored, findDuplicates, itemKey, type CatalogItem } from "@/lib/catalogSummary";

/** <Button> forces child SVGs to size-4/size-3; this restores each icon's own
 *  width/height attributes (size-auto → the SVG's intrinsic attribute size). */
const SVG_SIZE_AUTO = "[&_svg:not([class*='size-'])]:size-auto";

/** A connector's name, from each engine's one declaration (`lib/connectors.gen.ts`). */
const connectorLabel = (t: string) => CONNECTORS[t]?.label ?? t;


// ── Selection type ────────────────────────────────────────────────────────────

type Sel =
  | { level: "table";   connId: string; schemaName: string; table: CatalogTableInfo }
  | { level: "schema";  connId: string; schemaName: string; entry: CatalogSchemaInfo }
  | { level: "catalog"; connId: string; entry: CatalogEntry }
  | null;


// ── Add-connection inline form ────────────────────────────────────────────────

function AddConnForm({ onSave, onCancel }: { onSave: () => void; onCancel: () => void }) {
  const [name, setName]     = useState("");
  const [type, setType]     = useState("postgres");
  const [dsn, setDsn]       = useState("");
  const [schema, setSchema] = useState("");
  const [err, setErr]       = useState("");
  const [loading, setLoad]  = useState(false);

  const S: React.CSSProperties = { width: "100%", fontSize: 11, padding: "5px 8px", borderRadius: 4, background: "var(--bg-0)", border: "0.5px solid var(--b2)", color: "var(--t1)", outline: "none", fontFamily: "inherit" };
  const L: React.CSSProperties = { fontSize: 11, color: "var(--t3)", marginBottom: 3, display: "block" };

  const handle = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(""); setLoad(true);
    try { await addConnection(name, type, dsn, schema || undefined); onSave(); }
    catch (ex: unknown) { setErr((ex as Error).message); }
    finally { setLoad(false); }
  };

  return (
    <form onSubmit={handle} style={{ padding: "10px 12px", background: "var(--bg-0)", borderBottom: "0.5px solid var(--b1)", display: "flex", flexDirection: "column", gap: 8 }}>
      <p style={{ fontSize: 11, fontWeight: 500, color: "var(--t2)" }}>New connection</p>
      <div><label style={L}>Name</label><Input style={S} placeholder="My database" value={name} onChange={e => setName(e.target.value)} required /></div>
      <div>
        <label style={L}>Type</label>
        <SelectField style={{ ...S, cursor: "pointer" }} value={type} onChange={e => setType(e.target.value)}>
          <option value="postgres">PostgreSQL</option>
          <option value="duckdb">DuckDB file</option>
        </SelectField>
      </div>
      <div>
        <label style={L}>{type === "postgres" ? "Connection string" : "File path"}</label>
        <Input style={S} placeholder={type === "postgres" ? "postgresql://user:pass@host/db" : "/path/to/file.duckdb"} value={dsn} onChange={e => setDsn(e.target.value)} required />
      </div>
      <div>
        <label style={L}>Schema <span style={{ color: "var(--t3)" }}>(optional)</span></label>
        <Input style={S} placeholder={type === "postgres" ? "public" : "main"} value={schema} onChange={e => setSchema(e.target.value)} />
      </div>
      {err && <p style={{ fontSize: 11, color: "var(--red4)" }}>{err}</p>}
      <div style={{ display: "flex", gap: 6 }}>
        <Button variant="ghost" type="submit" disabled={loading} className="h-auto p-0 font-normal" style={{ flex: 1, fontSize: 11, padding: "5px 0", borderRadius: 4, cursor: "pointer", background: "var(--blue1)", color: "var(--blue4)", border: "0.5px solid var(--blue2)", opacity: loading ? .5 : 1 }}>
          {loading ? "Saving…" : "Save"}
        </Button>
        <Button variant="ghost" type="button" onClick={onCancel} className="h-auto p-0 font-normal" style={{ fontSize: 11, padding: "5px 10px", borderRadius: 4, cursor: "pointer", background: "transparent", color: "var(--t3)", border: "0.5px solid var(--b1)" }}>Cancel</Button>
      </div>
    </form>
  );
}

// ── Maturity marks (the exploration principles, 2026-10-08) ──────────────────

/** "off" said beside a name — a schema or table a person turned off for analysis. */
function OffMark() {
  return <span className="aug-fs-xs" title="Turned off for analysis — never explored, never queried by Investigation or Quick analysis"
    style={{ color: "var(--t3)", border: "0.5px solid var(--b2)", padding: "0 4px", flexShrink: 0 }}>off</span>;
}

/** A schema's maturity bars and number, or "off". */
function SchemaMark({ view, schema }: { view?: DatasetsView | null; schema: string }) {
  const ds = view?.schemas.find(s => s.name === schema);
  if (!ds) return null;
  return ds.off ? <OffMark /> : <MaturityBars m={ds.maturity} />;
}

/** A table's maturity bars (no number — the schema carries it), or "off". */
function TableMark({ view, schema, table }: { view?: DatasetsView | null; schema: string; table: string }) {
  const ds = view?.schemas.find(s => s.name === schema);
  const t = ds?.tables.find(x => x.name === table);
  if (!ds || !t) return null;
  return ds.off || t.off ? <OffMark /> : <MaturityBars m={t.maturity} showNumber={false} />;
}

// ── Tree node ─────────────────────────────────────────────────────────────────

function TreeRow({
  depth, icon, label, badge, count, isOpen, isSelected, hasChildren, onClick, onToggle,
}: {
  depth:       number;
  icon:        React.ReactNode;
  label:       string;
  badge?:      React.ReactNode;
  count?:      number;
  isOpen?:     boolean;
  isSelected?: boolean;
  hasChildren?: boolean;
  onClick?:    () => void;
  onToggle?:   () => void;
}) {
  return (
    <div
      onClick={onClick}
      style={{
        display: "flex", alignItems: "center", gap: 7,
        padding: `6px 10px 6px ${10 + depth * 15}px`,
        cursor: "pointer", userSelect: "none",
        background: isSelected ? "rgba(45,114,210,0.11)" : "transparent",
        borderLeft: `2px solid ${isSelected ? "var(--blue3)" : "transparent"}`,
        transition: "background .08s", minWidth: 0,
      }}
      onMouseEnter={e => { if (!isSelected) (e.currentTarget as HTMLElement).style.background = "var(--bg-hover)"; }}
      onMouseLeave={e => { if (!isSelected) (e.currentTarget as HTMLElement).style.background = "transparent"; }}
    >
      {hasChildren ? (
        <span onClick={e => { e.stopPropagation(); onToggle?.(); }} style={{ display: "flex", alignItems: "center", flexShrink: 0 }}>
          <Chevron open={!!isOpen} />
        </span>
      ) : <span style={{ width: 10, flexShrink: 0 }} />}

      <span style={{ color: isSelected ? "var(--blue4)" : "var(--t3)", display: "flex", alignItems: "center" }}>{icon}</span>

      <span style={{
        fontSize: 13, flex: 1, minWidth: 0,
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        color: isSelected ? "var(--t1)" : "var(--t2)", fontWeight: isSelected ? 500 : 400,
      }}>
        {label}
      </span>

      {badge}

      {count != null && (
        <span style={{ fontSize: 11, color: "var(--t3)", flexShrink: 0 }}>
          {count}
        </span>
      )}
    </div>
  );
}

interface Props {
  connections:      Connection[];
  selectedConn:     string;
  onSelect:         (id: string) => void;
  onDeleteConn:     (conn: Connection) => void;
  onChatWithTable?: (table: string, connId: string) => void;
  /** Ask about a catalog or a schema of it — the question in words, for the chat to answer. */
  onAsk?:           (question: string, connId: string) => void;
  /** Active workspace — scopes the catalog tree to its connections' schemas. */
  workspaceId?:     string;
  /** Open the global document corpus. Threaded from the shell rather than linked by
   *  href: this app keeps its tab in a query param, so an anchor would reload the whole
   *  client shell to move one pane. */
  onOpenDocuments?: () => void;
  /** PX — ⌘K's "Add a data source" lands HERE, on the full Add data page, rather than
   *  on the one-connector modal it used to raise over the catalog. A NONCE, not a
   *  boolean: the shell keeps this screen mounted behind the other tabs, so a boolean
   *  the shell then has to reset would either latch open or need a second callback to
   *  clear it. Every bump means "open it again", which is exactly what pressing the
   *  command twice means. */
  openAddDataNonce?: number;
}

export function CatalogScreen({ connections, selectedConn, onSelect, onDeleteConn, onChatWithTable, onAsk, workspaceId, onOpenDocuments, openAddDataNonce = 0 }: Props) {
  const { refresh: refreshSchema } = useSchema();
  const [tree, setTree]         = useState<CatalogTree | null>(null);
  const [treeLoading, setTreeL] = useState(true);
  // A failed read of the tree is said on the right, with a retry — never "Loading the catalog…" for ever.
  const [treeError, setTreeError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set(["section:connections", "catalog:workspace", "schema:workspace:ecommerce"]));
  const [sel, setSel]           = useState<Sel>(null);
  const [showAddData, setShowAddData] = useState(false);
  const [search, setSearch]     = useState("");
  const [testing, setTesting]   = useState<string | null>(null);
  const [testRes, setTestRes]   = useState<Record<string, boolean>>({});
  const q = search.toLowerCase();
  const selConn = connections.find(c => c.id === selectedConn);
  // Each catalog's datasets — layer, off, maturity, budget. Read for every catalog once the tree is in (the overview
  // says how far each is explored), and again after a change; absent is "being read", null is "the read failed".
  const [datasets, setDatasets] = useState<Record<string, DatasetsView | null>>({});
  const inFlight = useRef(new Set<string>());
  const loadDatasets = (connId: string) => {
    if (connId === "samples") return;
    inFlight.current.add(connId);
    getDatasets(connId)
      .then(v => setDatasets(prev => ({ ...prev, [connId]: v })))
      .catch(err => { console.error("[CatalogScreen] datasets read failed:", err); setDatasets(prev => ({ ...prev, [connId]: null })); })
      .finally(() => inFlight.current.delete(connId));
  };
  const loadDatasetsOnce = (connId: string) => {
    if (!(connId in datasets) && !inFlight.current.has(connId)) loadDatasets(connId);
  };

  const loadTree = () => {
    setTreeL(true);
    return getCatalogTree(workspaceId)
      .then(t => {
        setTree(t);
        setTreeError(null);
        const uc = t.sections.find(s => s.id === "connections");
        if (uc && uc.entries.length > 0) {
          const first = uc.entries[0];
          setExpanded(prev => {
            const n = new Set(prev);
            n.add(`catalog:${first.conn_id}`);
            if (first.schemas.length === 1) n.add(`schema:${first.conn_id}:${first.schemas[0].name}`);
            return n;
          });
        }
        return t;   // callers await this to confirm a new connection is really listed
      })
      .catch(err => { console.error("[CatalogScreen] tree load failed:", err); setTreeError(String(err?.message ?? err)); return null; })
      .finally(() => setTreeL(false));
  };

  // Refetch when the set of connections changes, not only on workspace switch. The tree
  // is built server-side from the registry, and this screen stays mounted behind the
  // other tabs — so a connection added while it was mounted (the demo seed, or + Add)
  // never appeared until a full page reload.
  const connKey = connections.map(c => c.id).join(",");
  useEffect(() => { loadTree(); }, [workspaceId, connKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // The shell asked for the Add data page (⌘K ▸ "Add a data source"). Guarded on > 0 so
  // the initial mount does not open it.
  useEffect(() => { if (openAddDataNonce > 0) setShowAddData(true); }, [openAddDataNonce]);

  const toggle = (key: string) => setExpanded(prev => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n; });
  const isOpen = (key: string) => expanded.has(key);
  useEffect(() => {
    const open = [...expanded].filter(k => k.startsWith("catalog:")).map(k => k.slice("catalog:".length));
    if (sel?.connId) open.push(sel.connId);
    for (const id of new Set(open)) loadDatasetsOnce(id);
  }, [expanded, sel?.connId]); // eslint-disable-line react-hooks/exhaustive-deps

  // The search index's status — which documents it cannot search — read ONCE while this screen is mounted: the read
  // probes the embedder with one embedding call, so a panel must not repeat it on every selection.
  const [indexStatus, setIndexStatus] = useState<KnowledgeStatus | null | undefined>(undefined);
  useEffect(() => {
    let alive = true;
    getKnowledgeStatus().then(s => { if (alive) setIndexStatus(s); }).catch(() => { if (alive) setIndexStatus(null); });
    return () => { alive = false; };
  }, []);

  const entries = useMemo(() => tree?.sections.flatMap(s => s.entries) ?? [], [tree]);
  useEffect(() => { for (const e of entries) loadDatasetsOnce(e.conn_id); }, [entries]); // eslint-disable-line react-hooks/exhaustive-deps
  // Two connections listing the same tables with the same row counts; the one explored less is the copy.
  const dups = useMemo(() => findDuplicates(entries, id => {
    const v = datasets[id];
    return v ? explored(v.schemas).percent : null;
  }), [entries, datasets]);

  const handleDelete = (id: string) => {
    const conn = connections.find(c => c.id === id);
    if (conn) onDeleteConn(conn);
  };

  const handleTest = async (id: string) => {
    setTesting(id);
    try { const r = await testConnection(id); setTestRes(p => ({ ...p, [id]: r.ok })); }
    catch { setTestRes(p => ({ ...p, [id]: false })); }
    finally { setTesting(null); }
  };

  const matches = (s: string) => !q || s.toLowerCase().includes(q);

  const renderTree = () => {
    if (!tree) return null;
    const nodes: React.ReactNode[] = [];

    tree.sections.forEach(section => {
      nodes.push(
        <div key={`sec-${section.id}`} style={{ padding: "14px 12px 5px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: "var(--t3)", textTransform: "uppercase", letterSpacing: "0.09em" }}>
              {section.label}
            </span>
          </div>
          {section.id === "connections" && (
            <Button variant="ghost" onClick={() => setShowAddData(true)}
              className={`h-auto p-0 font-normal ${SVG_SIZE_AUTO}`}
              style={{ display: "flex", alignItems: "center", gap: 3, fontSize: 11, padding: "2px 6px", borderRadius: 3, cursor: "pointer", background: "transparent", color: "var(--t3)", border: "0.5px solid var(--b1)" }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "var(--t2)"; }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "var(--t3)"; }}
            >
              <Icon name="plus" size={11} />
              Add
            </Button>
          )}
        </div>
      );

      if (section.entries.length === 0 && section.id === "connections") {
        nodes.push(<p key="empty" style={{ fontSize: 11, color: "var(--t3)", padding: "6px 12px 10px" }}>No connections yet.</p>);
      }

      section.entries.forEach(entry => {
        const catalogKey = `catalog:${entry.conn_id}`;
        const catOpen    = isOpen(catalogKey);
        const isSamples  = entry.conn_id === "samples";
        const catMatch   = matches(entry.name) || entry.schemas.some(sc => matches(sc.name) || sc.tables.some(t => matches(t.name)));
        if (!catMatch) return;

        void isSamples;
        nodes.push(
          <div key={catalogKey} style={{ position: "relative" }}>
            <TreeRow
              depth={0}
              icon={<IcoCatalog color="var(--t2)" />}
              label={entry.name}
              count={entry.schemas.reduce((s, sc) => s + sc.tables.length, 0) || undefined}
              isOpen={catOpen}
              isSelected={sel?.level === "catalog" && sel.connId === entry.conn_id}
              hasChildren={entry.schemas.length > 0}
              onClick={() => { setSel({ level: "catalog", connId: entry.conn_id, entry }); onSelect(entry.conn_id); toggle(catalogKey); }}
              onToggle={() => toggle(catalogKey)}
            />
          </div>
        );

        if (!catOpen) return;

        entry.schemas.forEach(schema => {
          const schemaKey = `schema:${entry.conn_id}:${schema.name}`;
          const schOpen   = isOpen(schemaKey);
          const schMatch  = matches(entry.name) || matches(schema.name) || schema.tables.some(t => matches(t.name));
          if (!schMatch) return;

          nodes.push(
            <TreeRow key={schemaKey} depth={1}
              icon={<IcoSchema color="var(--blue3)" />}
              label={schema.name}
              badge={<SchemaMark view={datasets[entry.conn_id]} schema={schema.name} />}
              count={schema.tables.length}
              isOpen={schOpen}
              isSelected={sel?.level === "schema" && sel.connId === entry.conn_id && sel.schemaName === schema.name}
              hasChildren={schema.tables.length > 0}
              onClick={() => { setSel({ level: "schema", connId: entry.conn_id, schemaName: schema.name, entry: schema }); toggle(schemaKey); }}
              onToggle={() => toggle(schemaKey)}
            />
          );

          if (!schOpen) return;

          schema.tables.forEach(table => {
            if (!matches(table.name) && !matches(schema.name) && !matches(entry.name)) return;
            const tableKey = `table:${entry.conn_id}:${schema.name}:${table.name}`;
            const isSel = sel?.level === "table" && sel.connId === entry.conn_id && sel.schemaName === schema.name && sel.table.name === table.name;

            nodes.push(
              <TreeRow key={tableKey} depth={2}
                icon={<IcoTable active={isSel} />}
                label={table.name}
                badge={<TableMark view={datasets[entry.conn_id]} schema={schema.name} table={table.name} />}
                isSelected={isSel}
                hasChildren={false}
                onClick={() => { recents.push(itemKey.table(entry.conn_id, schema.name, table.name)); setSel({ level: "table", connId: entry.conn_id, schemaName: schema.name, table }); }}
              />
            );
          });
        });
      });
    });
    return nodes;
  };

  const entryOf = (connId: string) => entries.find(e => e.conn_id === connId);
  const expand = (...keys: string[]) => setExpanded(p => { const n = new Set(p); keys.forEach(k => n.add(k)); return n; });
  const removed = () => { setSel(null); loadTree(); refreshSchema(); };

  const openCatalog = (connId: string) => {
    const cat = entryOf(connId);
    if (!cat) return;
    setSel({ level: "catalog", connId, entry: cat });
    onSelect(connId);
    expand(`catalog:${connId}`);
  };
  const openSchema = (connId: string, sc: CatalogSchemaInfo) => {
    setSel({ level: "schema", connId, schemaName: sc.name, entry: sc });
    expand(`catalog:${connId}`, `schema:${connId}:${sc.name}`);
  };
  const openTable = (connId: string, schemaName: string, table: CatalogTableInfo) => {
    // The tree's own table, so the row it highlights is the one opened.
    const tb = entryOf(connId)?.schemas.find(s => s.name === schemaName)?.tables.find(t => t.name === table.name) ?? table;
    recents.push(itemKey.table(connId, schemaName, tb.name));
    setSel({ level: "table", connId, schemaName, table: tb });
    expand(`catalog:${connId}`, `schema:${connId}:${schemaName}`);
  };
  const pick = (it: CatalogItem) => {
    onSelect(it.connId);
    const cat = entryOf(it.connId);
    if (!cat) return;
    expand(`catalog:${it.connId}`, ...(it.schemaName ? [`schema:${it.connId}:${it.schemaName}`] : []));
    if (it.type === "Table" && it.schemaName && it.tableName) {
      const tb = cat.schemas.find(s => s.name === it.schemaName)?.tables.find(t => t.name === it.tableName);
      if (tb) openTable(it.connId, it.schemaName, tb);
    } else if (it.type === "Schema" && it.schemaName) {
      const sc = cat.schemas.find(s => s.name === it.schemaName);
      if (sc) openSchema(it.connId, sc);
    } else {
      setSel({ level: "catalog", connId: it.connId, entry: cat });
    }
  };

  const renderDetail = () => {
    if (!sel) return (
      <CatalogHome tree={tree} treeError={treeError} onRetryTree={() => { loadTree(); }} views={datasets} dups={dups}
        status={indexStatus}
        label={connectorLabel} onOpenCatalog={openCatalog} onRetryViews={loadDatasets} onPick={pick} />
    );
    if (sel.level === "table") return (
      <CatalogTable key={`${sel.connId}:${sel.schemaName}:${sel.table.name}`} connId={sel.connId}
        catalogName={entryOf(sel.connId)?.name ?? sel.connId} schemaName={sel.schemaName} table={sel.table}
        view={datasets[sel.connId]} onAsk={onChatWithTable} onRemoved={removed}
        onProgramChanged={() => loadDatasets(sel.connId)} />
    );
    const entry: CatalogEntry = entryOf(sel.connId) ?? (sel.level === "catalog" ? sel.entry
      : { conn_id: sel.connId, name: sel.connId, conn_type: "", builtin: false, schemas: [sel.entry] });
    const schema = sel.level === "schema" ? (entry.schemas.find(s => s.name === sel.schemaName) ?? sel.entry) : undefined;
    return (
      <CatalogScope key={`${sel.connId}:${schema?.name ?? ""}`} entry={entry} schema={schema}
        view={datasets[sel.connId]} conn={connections.find(c => c.id === sel.connId)} dups={dups} label={connectorLabel}
        status={indexStatus}
        onOpenTable={(sch, t) => openTable(sel.connId, sch, t)} onOpenSchema={sc => openSchema(sel.connId, sc)}
        onOpenCatalog={openCatalog} onProgramChanged={() => loadDatasets(sel.connId)}
        onAsk={onAsk ? question => onAsk(question, sel.connId) : undefined}
        onTest={() => handleTest(sel.connId)} testing={testing === sel.connId} testResult={testRes[sel.connId]}
        onDelete={() => handleDelete(sel.connId)} onRemoved={removed} onOpenDocuments={onOpenDocuments} />
    );
  };

  if (showAddData) {
    return (
      <AddDataPanel
        workspaceId={workspaceId}
        onClose={() => setShowAddData(false)}
        onAdded={async (connId?: string) => {
          const t = await loadTree();
          refreshSchema();
          if (!connId) return true;
          // "Visible" means the gate that hides connections let this one through —
          // the exact check that used to fail silently.
          return !!t?.sections.some(s => s.entries.some(e => e.conn_id === connId));
        }}
      />
    );
  }

  return (
    <div style={{ position: "relative", display: "flex", height: "100%", overflow: "hidden", background: "var(--bg-0)" }}>
      <ResizableSplit storageKey="catalog" initial={340} min={240} max={560} style={{ flex: 1, height: "100%" }}
        left={
      /* ── Left: Tree navigator ── */
      <div style={{ borderRight: "0.5px solid var(--b1)", display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-1)", height: "100%", width: "100%" }}>
        {/* Top bar */}
        <div style={{ display: "flex", alignItems: "center", padding: "10px 12px 8px", borderBottom: "0.5px solid var(--b1)", flexShrink: 0, gap: 8 }}>
          <Button variant="ghost" onClick={() => setSel(null)} title="Catalog home"
            className="h-auto p-0 justify-start"
            style={{ fontSize: 12, fontWeight: 600, color: sel ? "var(--t3)" : "var(--t1)", textTransform: "uppercase", letterSpacing: "0.06em", flex: 1, textAlign: "left", background: "none", border: "none", padding: 0, cursor: "pointer", fontFamily: "inherit" }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.color = "var(--t1)"}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.color = sel ? "var(--t3)" : "var(--t1)"}
          >Catalog</Button>
          <Button variant="ghost" onClick={() => setShowAddData(true)} title="Add data"
            className={`h-auto p-0 ${SVG_SIZE_AUTO}`}
            style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 22, height: 22, borderRadius: 4, cursor: "pointer", background: "var(--blue1)", color: "var(--blue5)", border: "0.5px solid var(--blue2)", padding: 0 }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = "var(--blue2)"}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "var(--blue1)"}
          >
            <Icon name="plus" size={11} />
          </Button>
          <Button variant="ghost" onClick={() => { loadTree(); refreshSchema(); }} title="Refresh schema"
            className={`h-auto p-0 ${SVG_SIZE_AUTO}`}
            style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 22, height: 22, borderRadius: 4, cursor: "pointer", background: "transparent", color: "var(--t3)", border: "0.5px solid var(--b1)", padding: 0 }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.color = "var(--t2)"}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.color = "var(--t3)"}
          >
            <Icon name="refresh" size={12} />
          </Button>
        </div>

        {/* Search */}
        <div style={{ padding: "8px 10px", borderBottom: "0.5px solid var(--b1)", flexShrink: 0, position: "relative" }}>
          <span style={{ position: "absolute", left: 18, top: "50%", transform: "translateY(-50%)", color: "var(--t3)", pointerEvents: "none", display: "inline-flex" }}>
            <Icon name="search" size={11} />
          </span>
          <Input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search catalog…"
            style={{ width: "100%" }} />
        </div>

        {/* Tree body */}
        <div style={{ flex: 1, overflowY: "auto", padding: "4px 0 12px" }}>
          {treeLoading && (
            <div style={{ padding: "4px 12px" }} aria-label="Loading catalog">
              <SkeletonRows rows={6} />
            </div>
          )}
          {!treeLoading && renderTree()}
        </div>
      </div>
        }
        right={
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0, height: "100%" }}>
        {renderDetail()}
      </div>
        }
      />
    </div>
  );
}
