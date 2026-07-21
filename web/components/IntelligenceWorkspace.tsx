"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { getCatalogTree } from "@/lib/api";
import { Workspace, type WorkspaceLayer } from "@/components/Workspace";

// ── Lazy panels ──────────────────────────────────────────────────────────────
// The four perspectives are heavy graph/data views — load each only when its
// layer is first opened, then keep it mounted (see keep-alive note below).
const loading = () => (
  <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg-0)" }}>
    <div style={{ width: 20, height: 20, border: "2px solid var(--bg-3)", borderTopColor: "var(--blue3)", borderRadius: "50%", animation: "aug-spin 0.7s linear infinite" }} />
  </div>
);

const BriefingPanel    = dynamic(() => import("@/components/BriefingPanel").then(m => ({ default: m.BriefingPanel })),      { ssr: false, loading });
const OntologyPanel    = dynamic(() => import("@/components/OntologyPanel").then(m => ({ default: m.OntologyPanel })),       { ssr: false, loading });
const IntelligenceHub  = dynamic(() => import("@/components/IntelligenceHub").then(m => ({ default: m.IntelligenceHub })),  { ssr: false, loading });
const OrgIntelPanel    = dynamic(() => import("@/components/OrgIntelPanel").then(m => ({ default: m.OrgIntelPanel })),      { ssr: false, loading });
const EvidencePanel    = dynamic(() => import("@/components/EvidencePanel").then(m => ({ default: m.EvidencePanel })),      { ssr: false, loading });

// Minimal inline icon set — mirrors NavIcon paths used elsewhere in the shell.
const ICONS: Record<string, string> = {
  brief:   "M3 5h18M3 9h18M3 13h12M3 17h8",
  node:    "M12 4a2 2 0 100 4 2 2 0 000-4zM6 18a2 2 0 100 4 2 2 0 000-4zm12 0a2 2 0 100 4 2 2 0 000-4zM12 6v4m0 4v4M8 19h8M14 7l4 10M10 7L6 17",
  layers:  "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
  process: "M3 6h4v12H3V6zm7-3h4v18h-4V3zm7 6h4v9h-4V9z",
  spark:   "M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6L12 2z",
  check:   "M9 12l2 2 4-4M12 3a9 9 0 100 18 9 9 0 000-18z",
};

function Icon({ name, size = 14, color = "currentColor" }: { name: string; size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
      <path d={ICONS[name]} />
    </svg>
  );
}

export type IntelLayer = "briefing" | "hub" | "ontology" | "evidence" | "org";

const LAYERS: WorkspaceLayer<IntelLayer>[] = [
  { id: "briefing", icon: "brief",   label: "Briefing", blurb: "Cross-domain synthesis" },
  { id: "hub",      icon: "layers",  label: "Hub",      blurb: "Domain knowledge & data profile" },
  { id: "ontology", icon: "node",    label: "Ontology", blurb: "Object model & relationships" },
  { id: "evidence", icon: "check",   label: "Evidence", blurb: "Claim ledger & feedback" },
  { id: "org",      icon: "spark",   label: "Org",      blurb: "Organizational knowledge" },
];

type Props = {
  connectionId: string;
  onInvestigate: (q?: string, mode?: "ask" | "investigate", insightId?: string) => void;
  /** Active layer — controlled by the shell so external nav can deep-link. */
  layer: IntelLayer;
  onLayerChange: (l: IntelLayer) => void;
  /** Briefings-enabled connections for the workspace's connection picker, and the
   *  setter to switch the active one. Omitted/short → the picker hides. */
  connections?: { id: string; name: string }[];
  onConnectionChange?: (connectionId: string) => void;
  /** When set, scope-aware layers (Briefing) reflect this Canvas's curated tables rather
   *  than the whole connection — keeps Briefing consistent with the canvas-scoped Domains. */
  canvasId?: string;
  /** Active workspace — threaded to the Briefing so a workspace-scoped currency/industry
   *  override wins in the backend (override-wins over the app default). */
  workspaceId?: string;
};

/**
 * Unified, multi-layered Intelligence workspace — a single surface that fans
 * the four formerly-separate views (Ontology / Hub / Domain Intel / Org Intel)
 * into perspective layers over one shared connection context, the way
 * Palantir's Object Explorer or Databricks' Catalog Explorer present one entity
 * through several lenses.
 *
 * An *instance* of the generic `<Workspace>` shell: it owns the Intelligence-specific
 * scope (connection + schema pickers, the five panels, the icon set); the shell owns
 * the header chrome, the perspective switcher, and the keep-alive layered body.
 */
export function IntelligenceWorkspace({ connectionId, onInvestigate, layer, onLayerChange, connections, onConnectionChange, canvasId, workspaceId }: Props) {
  // Shared schema scope — one selector that filters Briefing, Hub, and Domains
  // together (a connection can expose several schemas; a canvas is already scoped).
  const [schemas, setSchemas]               = useState<string[]>([]);
  const [selectedSchema, setSelectedSchema] = useState<string | null>(null);
  // WP-5 — has the schema selector settled? The briefing auto-fetch must wait for this.
  // Otherwise the panel's first render (selectedSchema still null) fires an UNSCOPED
  // briefing request that races the SCOPED one issued once the catalog resolves — the two
  // hit different cached briefs, and the VERDICT headline visibly flips as the last lands.
  const [schemaResolved, setSchemaResolved] = useState(false);
  useEffect(() => {
    // A canvas is already table-scoped → ready immediately. But "no connection yet" is NOT
    // ready: setting resolved=true here would leak a stale `true` into the first render where
    // connectionId appears (before this effect re-runs), and the panel would fire an UNSCOPED
    // briefing request in that window — the exact race WP-5 removes.
    if (canvasId) { setSchemas([]); setSelectedSchema(null); setSchemaResolved(true); return; }
    if (!connectionId) { setSchemas([]); setSelectedSchema(null); setSchemaResolved(false); return; }
    let alive = true;
    setSchemaResolved(false);   // re-gate while this connection's schemas resolve
    getCatalogTree()
      .then(tree => {
        if (!alive) return;
        const entry = tree.sections.flatMap(s => s.entries).find(e => e.conn_id === connectionId);
        const names = entry?.schemas.map(s => s.name) ?? [];
        setSchemas(names);
        // TEMP (2026-06-26): "All schemas" removed — each schema is selected individually,
        // so default to the first concrete schema rather than the all-schemas (null) scope.
        setSelectedSchema(names[0] ?? null);
        setSchemaResolved(true);   // same callback as setSelectedSchema → one batched render
      })
      .catch(() => { if (alive) { setSchemas([]); setSchemaResolved(true); } });
    return () => { alive = false; };
  }, [connectionId, canvasId]);
  const schema = selectedSchema ?? undefined;
  const showConnPicker = !canvasId && !!onConnectionChange && (connections?.length ?? 0) > 1;
  const showSchema = !canvasId && schemas.length > 1;

  const headerControls = (showConnPicker || showSchema) ? (
    <>
      {/* Connection picker — lists only briefings-enabled connections (Catalog opt-in). */}
      {showConnPicker && (
        <label style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 10, color: "var(--t4)", textTransform: "uppercase", letterSpacing: ".06em" }}>Connection</span>
          <select
            value={connectionId}
            onChange={e => onConnectionChange?.(e.target.value)}
            aria-label="Connection"
            style={{
              fontSize: 12, color: "var(--t2)", background: "var(--bg-2)",
              border: "1px solid var(--b1)", borderRadius: "var(--r2)",
              padding: "3px 8px", cursor: "pointer", maxWidth: 200,
            }}
          >
            {connections!.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
      )}

      {/* Shared schema scope — drives Briefing / Hub / Domains together. Only shown
          when the connection exposes more than one schema (and never for a canvas). */}
      {showSchema && (
        <label style={{ marginLeft: showConnPicker ? 0 : "auto", display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 10, color: "var(--t4)", textTransform: "uppercase", letterSpacing: ".06em" }}>Schema</span>
          <select
            value={selectedSchema ?? ""}
            onChange={e => setSelectedSchema(e.target.value || null)}
            aria-label="Schema scope"
            style={{
              fontSize: 12, color: "var(--t2)", background: "var(--bg-2)",
              border: "1px solid var(--b1)", borderRadius: "var(--r2)",
              padding: "3px 8px", cursor: "pointer",
            }}
          >
            {/* TEMP (2026-06-26): "All schemas" option removed — select each schema individually. */}
            {schemas.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
      )}
    </>
  ) : undefined;

  return (
    <Workspace
      layers={LAYERS}
      layer={layer}
      onLayerChange={onLayerChange}
      ariaLabel="Intelligence layers"
      renderIcon={(name, size, color) => <Icon name={name} size={size} color={color} />}
      headerControls={headerControls}
      renderLayer={id => {
        // `key` on the scope: a schema switch REMOUNTS the brief rather than mutating it in
        // place. Without it the panel keeps every piece of per-scope state it doesn't
        // explicitly reset — which is how one schema's synthesis stayed on screen under
        // another schema's verdict. Belt to the server-side scope_key guard's braces.
        if (id === "briefing") return <BriefingPanel key={`${connectionId}:${canvasId ?? ""}:${schema ?? ""}`} connectionId={connectionId} onInvestigate={(q, insightId) => onInvestigate(q, "investigate", insightId)} canvasId={canvasId} schema={schema} schemaReady={schemaResolved} workspaceId={workspaceId} />;
        if (id === "ontology") return <OntologyPanel connectionId={connectionId} onInvestigate={q => onInvestigate(q)} schema={schema} />;
        if (id === "hub")      return <IntelligenceHub connectionId={connectionId} canvasId={canvasId} schema={schema} />;
        if (id === "evidence") return <EvidencePanel connectionId={connectionId} canvasId={canvasId} onInvestigate={q => onInvestigate(q, "investigate")} />;
        return <OrgIntelPanel />; // "org"
      }}
    />
  );
}
