"use client";
import { BrainMapPanel } from "@/components/BrainMapPanel";
import { SkeletonRows } from "@/components/ui/motion";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { getCatalogTree, getSystemFlags } from "@/lib/api";
import { listOntologySchemas, withSchemas } from "@/lib/objectTypes";
import { Workspace, type WorkspaceLayer } from "@/components/Workspace";
import { Icon as Glyph, type IconName } from "@/components/ui/icon";
import { EmptyState as SharedEmptyState } from "@/components/ui/empty-state";
import { MetricDetailHost } from "@/components/brief/MetricDetail";
import { SelectField } from "@/components/ui/select";

// ── Lazy panels ──────────────────────────────────────────────────────────────
// The four perspectives are heavy graph/data views — load each only when its
// layer is first opened, then keep it mounted (see keep-alive note below).
const loading = () => (
  <div style={{ flex: 1, background: "var(--bg-0)", padding: 16 }}>
    <SkeletonRows rows={6} />
  </div>
);

const BriefingPanel    = dynamic(() => import("@/components/BriefingPanel").then(m => ({ default: m.BriefingPanel })),      { ssr: false, loading });
const OntologyPanel    = dynamic(() => import("@/components/OntologyPanel").then(m => ({ default: m.OntologyPanel })),       { ssr: false, loading });
const ProfileLayer     = dynamic(() => import("@/components/ProfileLayer").then(m => ({ default: m.ProfileLayer })),       { ssr: false, loading });
const OrgIntelPanel    = dynamic(() => import("@/components/OrgIntelPanel").then(m => ({ default: m.OrgIntelPanel })),      { ssr: false, loading });
const EvidencePanel    = dynamic(() => import("@/components/EvidencePanel").then(m => ({ default: m.EvidencePanel })),      { ssr: false, loading });
const DeclaredActionsPanel = dynamic(() => import("@/components/DeclaredActionsPanel").then(m => ({ default: m.DeclaredActionsPanel })), { ssr: false, loading });
const ConnectionGraphPanel = dynamic(() => import("@/components/ConnectionGraphPanel").then(m => ({ default: m.ConnectionGraphPanel })), { ssr: false, loading });
// Relocated from the former Agents workspace (Agentic Ops merge): the closed
// loop's accumulation is org-wide learning — "what Aughor knows", which is this
// section's job — not agent operations.
const MemoryPanel      = dynamic(() => import("@/components/MemoryPanel").then(m => ({ default: m.MemoryPanel })), { ssr: false, loading });
// Arc CT-7 — a person's own cockpits, a tab of their own beside the Briefing.
const BriefingCockpits = dynamic(() => import("@/components/cockpit/BriefingCockpits").then(m => ({ default: m.BriefingCockpits })), { ssr: false, loading });

// Minimal inline icon set — mirrors NavIcon paths used elsewhere in the shell.
/**
 * This screen's glyphs, by role. The drawings come from the platform icon set
 * (`components/ui/icon.tsx`); this map only says which role each local name means,
 * so the existing call sites and `LAYERS` entries keep working unchanged.
 */
const ROLE: Record<string, IconName> = {
  brief: "brief",
  node: "node",
  kgraph: "kgraph",
  layers: "layers",
  process: "process",
  spark: "spark",
  check: "ok",
  memory: "memory",
  gauge: "gauge",
};

function Icon({ name, size = 14, color = "currentColor" }: { name: string; size?: number; color?: string }) {
  return (
    <span style={{ color, display: "inline-flex", flexShrink: 0 }}>
      <Glyph name={ROLE[name] ?? "info"} size={size} />
    </span>
  );
}

export type IntelLayer = "briefing" | "cockpit" | "hub" | "ontology" | "graph" | "evidence" | "memory" | "kinetic" | "org" | "brain";

const LAYERS: WorkspaceLayer<IntelLayer>[] = [
  { id: "briefing", icon: "brief",   label: "Briefing", blurb: "Cross-domain synthesis" },
  { id: "hub",      icon: "layers",  label: "Profile",  blurb: "Domain knowledge & data profile" },
  { id: "ontology", icon: "node",    label: "Ontology", blurb: "Object model & relationships" },
  { id: "evidence", icon: "check",   label: "Evidence", blurb: "Claim ledger & feedback" },
  { id: "memory",   icon: "memory",  label: "Memory",   blurb: "What the closed loop has learned" },
  { id: "kinetic",  icon: "spark",   label: "Actions",  blurb: "Declared actions & overlay edits" },
  { id: "org",      icon: "spark",   label: "Org",      blurb: "Organizational knowledge" },
  { id: "brain",    icon: "compass", label: "Brain map", blurb: "Every store behind what Aughor knows, with live counts" },
];

// Wave C4 — the connection knowledge graph layer, inserted after Ontology (which it
// promotes). Always present: the graph surface is unconditional, and the panel itself
// reports honestly when a connection has no graph built yet.
const GRAPH_LAYER: WorkspaceLayer<IntelLayer> = { id: "graph", icon: "kgraph", label: "Graph", blurb: "Connection knowledge graph" };

// Arc CT-7 — the person's cockpits, beside the Briefing: the Briefing is the connection's, a
// cockpit is the person's own. Present only with `cockpit.composed` on, and never for a canvas,
// which is for questions and deep analysis. Off, the layers are exactly what they were.
const COCKPIT_LAYER: WorkspaceLayer<IntelLayer> = { id: "cockpit", icon: "gauge", label: "Cockpit", blurb: "Your own cockpits — the cards you keep watching" };

type Props = {
  connectionId: string;
  onInvestigate: (q?: string, mode?: "ask" | "investigate", insightId?: string) => void;
  /** Active layer — controlled by the shell so external nav can deep-link. */
  layer: IntelLayer;
  /** S1 — `?table=` deep link: open the graph layer straight onto one entity. */
  initialGraphTable?: string;
  onLayerChange: (l: IntelLayer) => void;
  /** Briefings-enabled connections for the workspace's connection picker, and the
   *  setter to switch the active one. Omitted/short → the picker hides. */
  connections?: { id: string; name: string; schema_name?: string | null }[];
  onConnectionChange?: (connectionId: string) => void;
  /** When set, scope-aware layers (Briefing) reflect this Canvas's curated tables rather
   *  than the whole connection — keeps Briefing consistent with the canvas-scoped Domains. */
  canvasId?: string;
  /** Active workspace — threaded to the Briefing so a workspace-scoped currency/industry
   *  override wins in the backend (override-wins over the app default). */
  workspaceId?: string;
  /** False while the shell is still resolving the workspace and its connections. An empty
   *  state renders only once this is true; before that the screen says it is finding them. */
  contextReady?: boolean;
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
export function IntelligenceWorkspace({ connectionId, onInvestigate, layer, onLayerChange, connections, onConnectionChange, canvasId, workspaceId, initialGraphTable, contextReady = true }: Props) {
  // Shared schema scope — one selector that filters Briefing, Hub, and Domains
  // together (a connection can expose several schemas; a canvas is already scoped).
  const [schemas, setSchemas]               = useState<string[]>([]);
  const [selectedSchema, setSelectedSchema] = useState<string | null>(null);
  // WP-5 — has the schema selector settled? The briefing auto-fetch must wait for this.
  // Otherwise the panel's first render (selectedSchema still null) fires an UNSCOPED
  // briefing request that races the SCOPED one issued once the catalog resolves — the two
  // hit different cached briefs, and the VERDICT headline visibly flips as the last lands.
  const [schemaResolved, setSchemaResolved] = useState(false);
  // The connection's declared schema, read out HERE so the effect below keys on the value, not on
  // `connections`: the shell rebuilds that array on every one of its renders. Keyed on the array,
  // the effect re-ran each time — ⌘K, a nav count, a layer switch — and for a connection with no
  // declared schema every re-run re-gated the scope and re-read the catalog tree. The re-gate swaps
  // the kept-alive Briefing out and back in, and a Briefing that mounts again posts its brief again,
  // on screen or behind another layer (IntelligenceWorkspace.test.tsx).
  const metaSchema = connections?.find(c => c.id === connectionId)?.schema_name ?? null;
  useEffect(() => {
    // A canvas is already table-scoped → ready immediately. But "no connection yet" is NOT
    // ready: setting resolved=true here would leak a stale `true` into the first render where
    // connectionId appears (before this effect re-runs), and the panel would fire an UNSCOPED
    // briefing request in that window — the exact race WP-5 removes.
    if (canvasId) { setSchemas([]); setSelectedSchema(null); setSchemaResolved(true); return; }
    if (!connectionId) { setSchemas([]); setSelectedSchema(null); setSchemaResolved(false); return; }
    // Fast path: a connection whose registry meta names its single schema resolves
    // INSTANTLY — the catalog tree opens EVERY connection (seconds on a cold API,
    // BigQuery included), and the schema-gated Briefing rendered blank for all of it.
    if (metaSchema) {
      setSchemas([metaSchema]); setSelectedSchema(metaSchema); setSchemaResolved(true);
      // The registry names one schema, and an ontology may be built on another the connection holds (the explorer's
      // `ecommerce` beside DuckDB's `main`). Those join the picker behind the instant answer; the selection stays.
      let live = true;
      listOntologySchemas(connectionId)
        .then(found => { if (live) setSchemas(current => withSchemas(current, found)); })
        .catch(() => undefined);   // the picker keeps the registry's schema
      return () => { live = false; };
    }
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
  }, [connectionId, canvasId, metaSchema]);
  const schema = selectedSchema ?? undefined;
  // A question handed to the Agent as a deep analysis — the Evidence layer's door and the metric drawer's.
  const askAgent = (q: string) => onInvestigate(q, "investigate");

  // Arc CT-7 — read once. Until it answers, and when it cannot, the flag is off.
  const [cockpitsOn, setCockpitsOn] = useState<boolean | null>(null);
  useEffect(() => {
    let alive = true;
    getSystemFlags().then(f => { if (alive) setCockpitsOn(!!f["cockpit.composed"]?.value); })
      .catch(() => { if (alive) setCockpitsOn(false); });
    return () => { alive = false; };
  }, []);
  const withCockpit = cockpitsOn === true && !canvasId;
  // A link to the Cockpit tab where there is none opens the Briefing instead of an empty pane.
  useEffect(() => {
    if (layer === "cockpit" && cockpitsOn !== null && !withCockpit) onLayerChange("briefing");
  }, [layer, cockpitsOn, withCockpit, onLayerChange]);

  const layers = LAYERS.flatMap(l => (l.id === "ontology" ? [l, GRAPH_LAYER]
    : l.id === "briefing" && withCockpit ? [l, COCKPIT_LAYER] : [l]));

  const showConnPicker = !canvasId && !!onConnectionChange && (connections?.length ?? 0) > 1;
  const showSchema = !canvasId && schemas.length > 1;

  const headerControls = (showConnPicker || showSchema) ? (
    <>
      {/* Connection picker — lists only briefings-enabled connections (Catalog opt-in). */}
      {showConnPicker && (
        <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span className="aug-label">Connection</span>
          <SelectField
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
          </SelectField>
        </label>
      )}

      {/* Shared schema scope — drives Briefing / Hub / Domains together. Only shown
          when the connection exposes more than one schema (and never for a canvas). */}
      {showSchema && (
        <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span className="aug-label">Schema</span>
          <SelectField
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
          </SelectField>
        </label>
      )}
    </>
  ) : undefined;

  return (
    <Workspace
      layers={layers}
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
        // Mount the brief only once the schema selector has SETTLED. The key includes
        // the schema, so mounting before it resolves meant: mount bare (fetch wave 1,
        // content paints) → schema arrives → key change REMOUNTS the panel (blank) →
        // fetch wave 2 repaints — the visible ~1s "briefing flicker", plus every
        // request issued twice under two scope keys. One settled mount, one wave.
        if (id === "briefing") return (canvasId || schemaResolved)
          ? (
            // The metric drawer: a measured figure on the Briefing opens beside it (§6 item 43).
            <MetricDetailHost connectionId={connectionId} schema={schema} workspaceId={workspaceId}
              pageKey={`briefing:${connectionId}:${canvasId ?? ""}:${schema ?? ""}`} onAskWhy={askAgent}>
              <BriefingPanel key={`${connectionId}:${canvasId ?? ""}:${schema ?? ""}`} connectionId={connectionId} onInvestigate={(q, insightId) => onInvestigate(q, "investigate", insightId)} canvasId={canvasId} schema={schema} schemaReady={schemaResolved} workspaceId={workspaceId} />
            </MetricDetailHost>
          )
          // PX-0 (§3.14) — never a SILENT pane while the schema resolves. This gate was
          // a bare grey div, and with no connection selected it held forever: the app's
          // default landing was a black void with no words on it. An empty state says
          // what is happening and, when nothing is coming, where the door is.
          : (
            <SharedEmptyState icon="brief"
              title={connectionId ? "Reading this connection's schemas…"
                : !contextReady ? "Finding your connections…"
                : "No connection selected"}>
              {connectionId
                ? "The briefing opens once its schema scope settles — a cold catalog can take a few seconds."
                : !contextReady
                ? "The workspace and its connections are still loading."
                : showConnPicker
                ? "Briefings are per connection. Choose one in the bar above."
                : "Briefings are per connection. Add one from the Catalog, then come back here."}
            </SharedEmptyState>
          );
        if (id === "cockpit")  return (
          <MetricDetailHost connectionId={connectionId} schema={schema} workspaceId={workspaceId}
            pageKey={`cockpit:${connectionId}:${schema ?? ""}`} onAskWhy={askAgent}>
            <BriefingCockpits connectionId={connectionId} schema={schema} />
          </MetricDetailHost>
        );
        if (id === "ontology") return <OntologyPanel connectionId={connectionId} onInvestigate={q => onInvestigate(q)} schema={schema} />;
        if (id === "graph")    return <ConnectionGraphPanel connectionId={connectionId} schema={schema} onInvestigate={q => onInvestigate(q)} initialTableId={initialGraphTable} />;
        if (id === "hub")      return <ProfileLayer connectionId={connectionId} canvasId={canvasId} schema={schema} workspaceId={workspaceId} />;
        if (id === "evidence") return <EvidencePanel connectionId={connectionId} canvasId={canvasId} onInvestigate={askAgent} />;
        if (id === "memory")   return <MemoryPanel />;
        if (id === "kinetic")  return <DeclaredActionsPanel connectionId={connectionId} />;
        if (id === "brain")    return <BrainMapPanel connectionId={connectionId} workspaceId={workspaceId} contextReady={contextReady} />;
        return <OrgIntelPanel />; // "org"
      }}
    />
  );
}
