"use client";

/**
 * SE-1 — the Query workbench: ONE surface, two modes.
 *
 * Stage A of the builder merge. The visual composer is not rewritten, wrapped, or
 * modified — it is embedded verbatim as Visual mode, and the SQL editor arrives beside
 * it as a peer. That is deliberate sequencing: this PR proves the shell (mode toggle,
 * connection, URL contract) while the thing users already rely on keeps working
 * exactly as it did. SE-2's PR E does the extraction.
 *
 * Both modes stay MOUNTED once opened. A SQL draft and a half-built visual query are
 * both work in progress, and a toggle that discarded either would make switching feel
 * like leaving. Hiding rather than unmounting also keeps the editor's undo history and
 * the builder's fetched state alive across a flip.
 *
 * The mode lives in the URL (`?tab=query&mode=visual|sql`) via the History API, the
 * same contract every other tab here uses — so a mode is linkable and survives reload.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { QueryBuilder } from "@/components/QueryBuilder";
import { SqlMode } from "@/components/query/modes/SqlMode";
import { getSchemaRich, type Canvas, type Connection } from "@/lib/api";
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

export function QueryWorkbench({
  initialConnId,
  onOpenCanvas,
  importRequest,
  connections,
}: {
  initialConnId?: string;
  onOpenCanvas?: (canvas: Canvas) => void;
  importRequest?: { connId: string; sql: string; nonce: number };
  connections?: Connection[];
}) {
  const [mode, setMode] = useState<QueryMode>("visual");
  const [connId, setConnId] = useState(initialConnId ?? "");
  const [schema, setSchema] = useState<Record<string, string[]>>({});

  // URL → mode, in an effect (never during render — same hydration rule as drafts).
  useEffect(() => { const m = modeFromUrl(); if (m) setMode(m); }, []);

  useEffect(() => { if (initialConnId) setConnId(initialConnId); }, [initialConnId]);

  // An imported query (from Insights / Deep Analysis) lands in VISUAL mode, because
  // `importRequest` is QueryBuilder's existing contract and QueryBuilder is what knows
  // how to load, re-point and run it. Routing imports to the SQL editor instead would
  // be a behaviour change dressed as a refactor; it belongs with SE-2's extraction,
  // where the editor takes ownership of the import path deliberately.
  useEffect(() => {
    if (importRequest?.sql) setMode("visual");
  }, [importRequest?.nonce]); // eslint-disable-line react-hooks/exhaustive-deps

  const chooseMode = useCallback((m: QueryMode) => {
    setMode(m);
    syncModeToUrl(m);
  }, []);

  // Completion source: tables and their columns for this connection. Fetched once per
  // connection and handed to the editor — the editor never fetches, so "what can be
  // completed" and "what the workbench knows" cannot disagree. Failure is silent and
  // total: no schema means keyword-only completion, which is a degraded editor rather
  // than a broken one.
  useEffect(() => {
    let cancelled = false;
    if (!connId) { setSchema({}); return; }
    getSchemaRich(connId)
      .then(rich => {
        if (cancelled) return;
        const tables = rich.tables ?? [];

        // Table names arrive schema-qualified ("luxexperience.customers"), and CM6
        // reads a dotted key as a namespace path — so out of the box the user must
        // type "luxexperience." before any table appears. People type the table name.
        //
        // So each table is registered under BOTH its qualified name and its bare one,
        // and the bare alias is added only when exactly one schema owns that name.
        // Registering an ambiguous bare name would silently bind completion to
        // whichever schema happened to be last, which is worse than making the user
        // qualify a genuinely ambiguous table.
        const bareOwners = new Map<string, number>();
        for (const t of tables) {
          const bare = t.name.split(".").pop() ?? t.name;
          bareOwners.set(bare, (bareOwners.get(bare) ?? 0) + 1);
        }

        const map: Record<string, string[]> = {};
        for (const t of tables) {
          const cols = (t.columns ?? []).map(c => c.name);
          map[t.name] = cols;
          const bare = t.name.split(".").pop() ?? t.name;
          if (bare !== t.name && bareOwners.get(bare) === 1) map[bare] = cols;
        }
        setSchema(map);
      })
      .catch(() => { if (!cancelled) setSchema({}); });
    return () => { cancelled = true; };
  }, [connId]);

  const engine = useMemo(() => {
    const c = (connections ?? []).find(x => x.id === connId);
    return c ? { conn_type: c.conn_type, dialect: (c as { dialect?: string }).dialect } : null;
  }, [connections, connId]);

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
      {/* mode toggle */}
      <div
        style={{
          display: "flex", alignItems: "center", gap: 6,
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
        <SqlMode connId={connId} engine={engine} schema={schema} />
      </div>
    </div>
  );
}
