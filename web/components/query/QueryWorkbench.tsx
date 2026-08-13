"use client";

/**
 * SE-1 — the Query workbench: ONE surface, two modes.
 *
 * SE-1 stood the shell up with the visual composer embedded verbatim; **PR E is the
 * extraction**. The workbench now owns the three things that were duplicated across the
 * two modes:
 *
 *   1. **The connection.** One picker, for both modes. QueryBuilder had its own beside
 *      the workbench's, so the same screen asked the same question twice and only one
 *      of the answers was authoritative.
 *   2. **The catalog rail.** ONE `CatalogRail`, mounted OUTSIDE either mode pane, so
 *      switching Visual↔SQL leaves the catalog exactly where it was rather than
 *      swapping one tree for a different tree showing the same warehouse. What a row
 *      DOES is per-mode and arrives from `railProps` below.
 *   3. **The schema read.** Both modes already shared `useRichSchema`'s cache; now they
 *      share the derivation too, so what you can browse, what completes, and what the
 *      builder will join are the same list by construction.
 *
 * Both modes stay MOUNTED once opened. A SQL draft and a half-built visual query are
 * both work in progress, and a toggle that discarded either would make switching feel
 * like leaving. Hiding rather than unmounting also keeps the editor's undo history and
 * the builder's fetched state alive across a flip.
 *
 * The mode lives in the URL (`?tab=query&mode=visual|sql`) via the History API, the
 * same contract every other tab here uses — so a mode is linkable and survives reload.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { QueryBuilder, type BuilderRailBinding } from "@/components/QueryBuilder";
import { SqlMode } from "@/components/query/modes/SqlMode";
import { CatalogRail, type RailTable } from "@/components/query/CatalogRail";
import {
  SavedQueryBar, isVisualQuery, type SavedQueryBinding,
} from "@/components/query/SavedQueryBar";
import { ResizableSplit } from "@/components/ResizableSplit";
import { type Canvas, type Connection, type SavedQuery } from "@/lib/api";
import { useRichSchema } from "@/lib/schema-context";
import { Button } from "@/components/ui/button";

export type QueryMode = "visual" | "sql";

const MODES: Array<{ id: QueryMode; label: string; hint: string }> = [
  { id: "visual", label: "Visual", hint: "Compose a query without writing SQL" },
  { id: "sql",    label: "SQL",    hint: "Write SQL with completion and guards" },
];

/** Read/write `?mode=` without a router round-trip — matches page.tsx's tab sync. */
function modeFromUrl(): QueryMode | null {
  if (typeof window === "undefined") return null;
  const m = new URLSearchParams(window.location.search).get("mode");
  return m === "sql" || m === "visual" ? m : null;
}

function syncModeToUrl(mode: QueryMode): void {
  if (typeof window === "undefined") return;
  try {
    const url = new URL(window.location.href);
    url.searchParams.set("mode", mode);
    window.history.replaceState(null, "", url.toString());
  } catch { /* a URL the browser won't let us rewrite is not worth failing over */ }
}

/** Completion source for one connection: `{ "schema.table": [cols], "table": [cols] }`.
 *
 *  Table names arrive schema-qualified and CM6 reads a dotted key as a namespace path,
 *  so out of the box nothing appears until the user types "luxexperience." — and people
 *  type the table name. Each table is therefore registered under its bare name as well,
 *  but ONLY when exactly one schema owns that name; an ambiguous alias would silently
 *  bind completion to whichever schema landed last in the map, which is worse than
 *  making a genuinely ambiguous table be qualified. */
function useSchemaMap(connId: string) {
  const { schema: data, loading } = useRichSchema(connId);

  return useMemo(() => {
    const tables = data?.tables ?? [];
    const bareOwners = new Map<string, number>();
    for (const t of tables) {
      const bare = t.name.split(".").pop() ?? t.name;
      bareOwners.set(bare, (bareOwners.get(bare) ?? 0) + 1);
    }
    const map: Record<string, string[]> = {};
    const schemas = new Set<string>();
    for (const t of tables) {
      const cols = (t.columns ?? []).map(c => c.name);
      map[t.name] = cols;
      const parts = t.name.split(".");
      const bare = parts.pop() ?? t.name;
      if (parts.length) schemas.add(parts.join("."));
      if (bare !== t.name && bareOwners.get(bare) === 1) map[bare] = cols;
    }
    // The RAIL gets the SAME tables — one fetch, three consumers (completion, the rail,
    // and the builder that reads this cache itself), so what you can browse, what
    // completes and what the builder will join cannot disagree. It also carries the join
    // topology the endpoint already returns: the builder's rail has always shown `⋈n`
    // and `isolated`, and the SQL editor was dropping facts it had in hand.
    const degree = new Map<string, Set<string>>();
    for (const j of data?.joins ?? []) {
      if (!degree.has(j.t1)) degree.set(j.t1, new Set());
      if (!degree.has(j.t2)) degree.set(j.t2, new Set());
      degree.get(j.t1)!.add(j.t2);
      degree.get(j.t2)!.add(j.t1);
    }
    const isolatedSet = new Set(data?.isolated ?? []);
    const railTables: RailTable[] = tables.map(t => ({
      name: t.name,
      columns: (t.columns ?? []).map(c => ({ name: c.name, type: c.type, is_fk: c.is_fk })),
      rowCount: t.row_count,
      joinDegree: degree.get(t.name)?.size ?? 0,
      isolated: isolatedSet.has(t.name),
    }));
    return { map, railTables, schemas: [...schemas].sort(), tableCount: tables.length, loading };
  }, [data, loading]);
}

function WorkbenchInner({
  initialConnId, onOpenCanvas, importRequest, connections, initialMode,
}: {
  initialConnId?: string;
  onOpenCanvas?: (canvas: Canvas) => void;
  importRequest?: { connId: string; sql: string; nonce: number };
  connections?: Connection[];
  /** Set by a legacy `?tab=builder` deep link, which meant the visual builder. */
  initialMode?: QueryMode;
}) {
  // SQL is the default mode: the surface is called the SQL Editor, and landing in a
  // visual composer would contradict its own name. Two things still override it, in
  // this order — an explicit `?mode=` (the user said which one), then the legacy
  // `?tab=builder` deep link, which MEANT the visual builder and should keep meaning
  // it rather than silently redirecting every old bookmark to a different tool.
  const [mode, setMode] = useState<QueryMode>("sql");
  const [connId, setConnId] = useState(initialConnId ?? "");
  const [defaultSchema, setDefaultSchema] = useState("");
  const [showCatalog, setShowCatalog] = useState(true);
  // Visual mode's rail behaviours, published by QueryBuilder. Null until it mounts, so
  // the rail is a plain catalog rather than a broken builder rail in the meantime.
  const [railBinding, setRailBinding] = useState<BuilderRailBinding | null>(null);
  // SQL mode's insertion point. A ref, not state: the rail's handlers read it at CLICK
  // time, so the workbench has nothing to re-render when the editor mounts.
  const insertAtCursor = useRef<((text: string) => void) | null>(null);

  // BOTH modes' saved bindings, not just the active one: loading a saved query switches
  // to the mode that query belongs to and then loads it there, so the binding for the
  // mode you are NOT in has to be reachable. Both modes stay mounted, so both exist.
  const [savedBindings, setSavedBindings] = useState<Record<QueryMode, SavedQueryBinding | null>>(
    { visual: null, sql: null },
  );
  const [savable, setSavable] = useState<Record<QueryMode, boolean>>({ visual: false, sql: false });
  const [activeSaved, setActiveSaved] = useState<SavedQuery | null>(null);

  // Stable callbacks — a fresh identity here would re-fire each mode's publish effect
  // on every workbench render.
  const bindVisual = useCallback((b: SavedQueryBinding) => setSavedBindings(p => ({ ...p, visual: b })), []);
  const bindSql = useCallback((b: SavedQueryBinding) => setSavedBindings(p => ({ ...p, sql: b })), []);
  const savableVisual = useCallback((v: boolean) => setSavable(p => (p.visual === v ? p : { ...p, visual: v })), []);
  const savableSql = useCallback((v: boolean) => setSavable(p => (p.sql === v ? p : { ...p, sql: v })), []);

  // URL → mode, in an effect (never during render — same hydration rule as drafts).
  // `initialMode` carries the legacy-link intent from page.tsx rather than being
  // sniffed from the URL here: the tab resolver rewrites `?tab=builder` to `?tab=data`
  // before this component mounts, so by the time we could look, the evidence is gone.
  useEffect(() => {
    const m = modeFromUrl();
    if (m) { setMode(m); return; }
    if (initialMode) setMode(initialMode);
  }, [initialMode]);
  useEffect(() => { if (initialConnId) setConnId(initialConnId); }, [initialConnId]);

  // Land on a real connection rather than an empty picker. QueryBuilder used to do this
  // for itself; now that the workbench owns the control it owns the defaulting too, or
  // Visual mode would come up on nothing. It also re-points when the workspace's list
  // stops containing the current connection — a stale id queries a warehouse this
  // workspace is not allowed to see.
  useEffect(() => {
    const list = connections ?? [];
    if (!list.length) { setConnId(""); return; }
    if (!connId || !list.some(c => c.id === connId)) setConnId(list[0].id);
  }, [connections, connId]);

  // An imported query (from Insights / Deep Analysis) lands in VISUAL mode, because
  // `importRequest` is QueryBuilder's existing contract and QueryBuilder is what knows
  // how to load, re-point and run it. Routing imports to the SQL editor instead would
  // be a behaviour change dressed as a refactor; it belongs with SE-2's extraction.
  useEffect(() => {
    if (importRequest?.sql) setMode("visual");
  }, [importRequest?.nonce]); // eslint-disable-line react-hooks/exhaustive-deps

  const { map: schema, railTables, schemas, loading: schemaLoading } = useSchemaMap(connId);

  // A schema chosen for one warehouse means nothing in the next one.
  useEffect(() => { setDefaultSchema(""); }, [connId]);

  const chooseMode = useCallback((m: QueryMode) => {
    setMode(m);
    syncModeToUrl(m);
  }, []);

  // A saved query opens in the mode it was AUTHORED in, not the one you happen to be
  // standing in. Both modes are mounted, so the target's binding is already published.
  const openSaved = useCallback((q: SavedQuery) => {
    const target: QueryMode = isVisualQuery(q) ? "visual" : "sql";
    chooseMode(target);
    savedBindings[target]?.load(q);
  }, [chooseMode, savedBindings]);

  const engine = useMemo(() => {
    const c = (connections ?? []).find(x => x.id === connId);
    return c ? { conn_type: c.conn_type, dialect: (c as { dialect?: string }).dialect } : null;
  }, [connections, connId]);

  const controlStyle: React.CSSProperties = { width: "auto", cursor: "pointer", fontSize: 13 };
  const controlLabel: React.CSSProperties = { fontSize: 13, color: "var(--t3)", flexShrink: 0 };

  // What a rail row DOES, per mode. The rail itself is one instance either way — only
  // the meaning of a click changes, which is the whole reason the actions are props.
  //
  // SQL mode inserts: a TABLE goes in qualified (unambiguous in a FROM clause) and a
  // COLUMN goes in bare (a schema-qualified column would be wrong in a SELECT list
  // against an aliased table). Visual mode's behaviours come from the builder.
  // In Visual mode before the builder has published its binding, the rows are INERT —
  // never the SQL handlers. Falling through to those would send a click meant for the
  // visual query into the SQL editor's document, where the user cannot even see it land.
  const railProps = mode === "visual"
    ? (railBinding ?? {})
    : {
      onSelectTable: (name: string) => insertAtCursor.current?.(name),
      onSelectColumn: (col: string) => insertAtCursor.current?.(col),
    };

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
      {/* mode toggle, then the controls BOTH modes share */}
      <div
        style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "8px 12px", borderBottom: "1px solid var(--b1)", flexShrink: 0,
        }}
      >
        {MODES.map(m => (
          <Button
            key={m.id}
            variant={mode === m.id ? "secondary" : "ghost"}
            size="xs"
            className="aug-fs-ui"
            title={m.hint}
            onClick={() => chooseMode(m.id)}
          >
            {m.label}
          </Button>
        ))}

        <span style={{ width: 1, height: 16, background: "var(--b1)", margin: "0 2px" }} />
        <label style={controlLabel}>Connection</label>
        <select
          className="aug-input"
          style={controlStyle}
          value={connId}
          onChange={e => setConnId(e.target.value)}
          title="The warehouse this workbench queries, in both modes"
        >
          {!connId && <option value="">Select a connection…</option>}
          {(connections ?? []).map(c => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>

        {/* Schema stays SQL-only: it sets what completes without qualifying, and Visual
            mode qualifies every name it generates, so the control would do nothing. */}
        {mode === "sql" && schemas.length > 0 && (
          <>
            <label style={controlLabel}>Schema</label>
            <select
              className="aug-input"
              style={controlStyle}
              value={defaultSchema}
              onChange={e => setDefaultSchema(e.target.value)}
              title="Tables in this schema complete and resolve without qualifying them"
            >
              <option value="">(all — qualify names)</option>
              {schemas.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </>
        )}

        <div style={{ flex: 1 }} />

        {/* One saved surface for both modes — the SQL editor could not save at all. */}
        <SavedQueryBar
          connId={connId}
          mode={mode}
          binding={savedBindings[mode]}
          savable={savable[mode]}
          onLoaded={openSaved}
          onActiveChange={setActiveSaved}
        />

        <Button
          variant="ghost"
          size="xs"
          className="aug-fs-ui"
          onClick={() => setShowCatalog(s => !s)}
          title="Show or hide the catalog"
        >
          {showCatalog ? "Hide catalog" : "Catalog"}
        </Button>
      </div>

      {/* Catalog ▸ modes. ONE rail, outside both panes, so a mode switch does not
          rebuild the tree the user just navigated — and `collapsed` rather than a
          conditional split, so hiding the rail does not remount the modes beside it. */}
      <ResizableSplit
        storageKey="workbench.catalog"
        initial={280}
        min={200}
        max={560}
        collapsed={!showCatalog}
        style={{ flex: 1, minWidth: 0, minHeight: 0 }}
        left={
          <CatalogRail
            tables={railTables}
            connectionName={(connections ?? []).find(c => c.id === connId)?.name}
            loading={schemaLoading}
            hint={mode === "visual"
              ? "Click to add · drag a column onto Dimensions or Metrics"
              : "Click to insert at the cursor"}
            {...railProps}
          />
        }
        right={
          <>
            {/* Both modes stay mounted; only visibility changes. `display: none` keeps
                React state, the CM6 document and the builder's fetches alive. */}
            <div style={{ flex: 1, minHeight: 0, display: mode === "visual" ? "flex" : "none",
                          flexDirection: "column" }}>
              <QueryBuilder
                connId={connId}
                onConnIdChange={setConnId}
                onOpenCanvas={onOpenCanvas}
                importRequest={importRequest}
                onRailBinding={setRailBinding}
                onSavedBinding={bindVisual}
                onSavableChange={savableVisual}
                savedName={activeSaved?.name}
              />
            </div>
            <div style={{ flex: 1, minHeight: 0, display: mode === "sql" ? "flex" : "none",
                          flexDirection: "column" }}>
              <SqlMode
                connId={connId}
                engine={engine}
                schema={schema}
                defaultSchema={defaultSchema || undefined}
                onInsertReady={fn => { insertAtCursor.current = fn; }}
                onSavedBinding={bindSql}
                onSavableChange={savableSql}
              />
            </div>
          </>
        }
      />
    </div>
  );
}

export function QueryWorkbench(props: {
  initialConnId?: string;
  onOpenCanvas?: (canvas: Canvas) => void;
  importRequest?: { connId: string; sql: string; nonce: number };
  connections?: Connection[];
  initialMode?: QueryMode;
}) {
  // No provider of its own: the app mounts one QueryClient (app/providers.tsx), and a
  // second client here would mean a second cache — reintroducing exactly the duplicate
  // requests this consolidation removed.
  return <WorkbenchInner {...props} />;
}
