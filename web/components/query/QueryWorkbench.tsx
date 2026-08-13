"use client";

/**
 * SE-1 — the Query workbench: ONE surface, two modes.
 *
 * Stage A of the builder merge. The visual composer is not rewritten, wrapped, or
 * modified — it is embedded verbatim as Visual mode, and the SQL editor arrives beside
 * it as a peer. That is deliberate sequencing: this PR proves the shell (mode toggle,
 * connection, schema, URL contract) while the thing users already rely on keeps working
 * exactly as it did. SE-2's PR E does the extraction.
 *
 * Both modes stay MOUNTED once opened. A SQL draft and a half-built visual query are
 * both work in progress, and a toggle that discarded either would make switching feel
 * like leaving. Hiding rather than unmounting also keeps the editor's undo history and
 * the builder's fetched state alive across a flip.
 *
 * The mode lives in the URL (`?tab=query&mode=visual|sql`) via the History API, the
 * same contract every other tab here uses — so a mode is linkable and survives reload.
 *
 * The connection and schema controls render only in SQL mode, because QueryBuilder
 * carries its own and two competing pickers on one screen is worse than one picker per
 * mode. That asymmetry is a Stage-A artifact: PR E lifts the builder's controls out and
 * the workbench owns a single pair for both modes.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { QueryBuilder } from "@/components/QueryBuilder";
import { SqlMode } from "@/components/query/modes/SqlMode";
import { getSchemaRich, type Canvas, type Connection } from "@/lib/api";
import { Button } from "@/components/ui/button";

export type QueryMode = "visual" | "sql";

const MODES: Array<{ id: QueryMode; label: string; hint: string }> = [
  { id: "visual", label: "Visual", hint: "Compose a query without writing SQL" },
  { id: "sql",    label: "SQL",    hint: "Write SQL with completion and guards" },
];

/** One client for the workbench subtree (DP-3). Schema reads are the same answer for
 *  every consumer and change only when the warehouse does, so they are cached rather
 *  than refetched per mount — the workbench mounts both modes at once, which turned
 *  one logical read into several identical requests. */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60_000,
      gcTime: 10 * 60_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

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
  const { data } = useQuery({
    queryKey: ["schema-rich", connId],
    queryFn: () => getSchemaRich(connId),
    enabled: !!connId,
  });

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
    // The sidebar gets the SAME tables — one fetch, two consumers, so what you can
    // browse and what completes cannot disagree. It also carries the join topology
    // the endpoint already returns: the builder's rail has always shown `⋈n` and
    // `isolated`, and the SQL editor was dropping facts it had in hand.
    const degree = new Map<string, Set<string>>();
    for (const j of data?.joins ?? []) {
      if (!degree.has(j.t1)) degree.set(j.t1, new Set());
      if (!degree.has(j.t2)) degree.set(j.t2, new Set());
      degree.get(j.t1)!.add(j.t2);
      degree.get(j.t2)!.add(j.t1);
    }
    const isolatedSet = new Set(data?.isolated ?? []);
    const sidebarTables = tables.map(t => ({
      name: t.name,
      columns: (t.columns ?? []).map(c => ({ name: c.name, type: c.type, is_fk: c.is_fk })),
      rowCount: t.row_count,
      joinDegree: degree.get(t.name)?.size ?? 0,
      isolated: isolatedSet.has(t.name),
    }));
    return { map, sidebarTables, schemas: [...schemas].sort(), tableCount: tables.length };
  }, [data]);
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

  // An imported query (from Insights / Deep Analysis) lands in VISUAL mode, because
  // `importRequest` is QueryBuilder's existing contract and QueryBuilder is what knows
  // how to load, re-point and run it. Routing imports to the SQL editor instead would
  // be a behaviour change dressed as a refactor; it belongs with SE-2's extraction.
  useEffect(() => {
    if (importRequest?.sql) setMode("visual");
  }, [importRequest?.nonce]); // eslint-disable-line react-hooks/exhaustive-deps

  const { map: schema, sidebarTables, schemas, tableCount } = useSchemaMap(connId);

  // A schema chosen for one warehouse means nothing in the next one.
  useEffect(() => { setDefaultSchema(""); }, [connId]);

  const chooseMode = useCallback((m: QueryMode) => {
    setMode(m);
    syncModeToUrl(m);
  }, []);

  const engine = useMemo(() => {
    const c = (connections ?? []).find(x => x.id === connId);
    return c ? { conn_type: c.conn_type, dialect: (c as { dialect?: string }).dialect } : null;
  }, [connections, connId]);

  const controlStyle: React.CSSProperties = { width: "auto", cursor: "pointer", fontSize: 12 };

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
      {/* mode toggle + (SQL only) connection and schema */}
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
            title={m.hint}
            onClick={() => chooseMode(m.id)}
          >
            {m.label}
          </Button>
        ))}

        {mode === "sql" && (
          <>
            <span style={{ width: 1, height: 16, background: "var(--b1)", margin: "0 2px" }} />
            <label style={{ fontSize: 11, color: "var(--t3)" }}>Connection</label>
            <select
              className="aug-input"
              style={controlStyle}
              value={connId}
              onChange={e => setConnId(e.target.value)}
              title="The warehouse this SQL runs against"
            >
              {!connId && <option value="">Select a connection…</option>}
              {(connections ?? []).map(c => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>

            {schemas.length > 0 && (
              <>
                <label style={{ fontSize: 11, color: "var(--t3)" }}>Schema</label>
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
            <span style={{ fontSize: 11, color: "var(--t4)" }}>
              {tableCount ? `${tableCount} tables` : "no schema loaded"}
            </span>
          </>
        )}
      </div>

      {/* Both modes stay mounted; only visibility changes. `display: none` keeps
          React state, the CM6 document and the builder's fetches alive. */}
      <div style={{ flex: 1, minHeight: 0, display: mode === "visual" ? "flex" : "none",
                    flexDirection: "column" }}>
        <QueryBuilder
          initialConnId={connId || initialConnId}
          onOpenCanvas={onOpenCanvas}
          importRequest={importRequest}
          connections={connections}
        />
      </div>
      <div style={{ flex: 1, minHeight: 0, display: mode === "sql" ? "flex" : "none",
                    flexDirection: "column" }}>
        <SqlMode
          connId={connId}
          engine={engine}
          schema={schema}
          sidebarTables={sidebarTables}
          defaultSchema={defaultSchema || undefined}
        />
      </div>
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
  return (
    <QueryClientProvider client={queryClient}>
      <WorkbenchInner {...props} />
    </QueryClientProvider>
  );
}
