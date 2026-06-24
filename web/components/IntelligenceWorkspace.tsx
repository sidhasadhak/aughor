"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { getCatalogTree } from "@/lib/api";

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

const LAYERS: { id: IntelLayer; icon: string; label: string; blurb: string }[] = [
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
 * Keep-alive: a layer is mounted the first time it's opened and then stays
 * mounted (display toggled), so graph zoom/scroll/fetch state survives layer
 * switches. Layers that have never been visited aren't mounted at all.
 */
export function IntelligenceWorkspace({ connectionId, onInvestigate, layer, onLayerChange, connections, onConnectionChange, canvasId, workspaceId }: Props) {
  // Mount a layer the first time it becomes active, then keep it mounted.
  const [visited, setVisited] = useState<Set<IntelLayer>>(() => new Set([layer]));
  useEffect(() => {
    setVisited(prev => (prev.has(layer) ? prev : new Set(prev).add(layer)));
  }, [layer]);

  // Shared schema scope — one selector that filters Briefing, Hub, and Domains
  // together (a connection can expose several schemas; a canvas is already scoped).
  const [schemas, setSchemas]               = useState<string[]>([]);
  const [selectedSchema, setSelectedSchema] = useState<string | null>(null);
  useEffect(() => {
    if (canvasId || !connectionId) { setSchemas([]); setSelectedSchema(null); return; }
    let alive = true;
    getCatalogTree()
      .then(tree => {
        if (!alive) return;
        const entry = tree.sections.flatMap(s => s.entries).find(e => e.conn_id === connectionId);
        const names = entry?.schemas.map(s => s.name) ?? [];
        setSchemas(names);
        setSelectedSchema(names.length === 1 ? names[0] : null);
      })
      .catch(() => { if (alive) setSchemas([]); });
    return () => { alive = false; };
  }, [connectionId, canvasId]);
  const schema = selectedSchema ?? undefined;
  const showConnPicker = !canvasId && !!onConnectionChange && (connections?.length ?? 0) > 1;
  const showSchema = !canvasId && schemas.length > 1;

  const active = LAYERS.find(l => l.id === layer)!;

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-0)" }}>
      {/* Workspace header — title + perspective switcher */}
      <div className="aug-content-header" style={{ gap: 14 }}>
        <Icon name={active.icon} size={14} color="var(--t3)" />
        <span style={{ fontSize: 13, fontWeight: 500 }}>{active.label}</span>
        <span style={{ fontSize: 11, color: "var(--t3)" }}>· {active.blurb}</span>

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
              <option value="">All schemas</option>
              {schemas.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
        )}

        {/* Layer switcher — segmented control */}
        <div
          role="tablist"
          aria-label="Intelligence layers"
          style={{
            marginLeft: (showConnPicker || showSchema) ? 0 : "auto",
            display: "flex",
            gap: 2,
            padding: 2,
            background: "var(--bg-2)",
            border: "1px solid var(--b1)",
            borderRadius: "var(--r3)",
          }}
        >
          {LAYERS.map(l => {
            const on = l.id === layer;
            return (
              <button
                key={l.id}
                role="tab"
                aria-selected={on}
                onClick={() => onLayerChange(l.id)}
                title={l.blurb}
                className="aug-btn"
                style={{
                  padding: "4px 11px",
                  borderRadius: "var(--r2)",
                  border: "1px solid transparent",
                  background: on ? "var(--bg-sel)" : "transparent",
                  color: on ? "var(--blue5)" : "var(--t2)",
                  fontWeight: on ? 500 : 400,
                }}
              >
                <Icon name={l.icon} size={13} color={on ? "var(--blue4)" : "currentColor"} />
                {l.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Layered body — visited layers stay mounted; only the active one shows. */}
      <div style={{ flex: 1, position: "relative", overflow: "hidden", minHeight: 0 }}>
        {visited.has("briefing") && (
          <Layer show={layer === "briefing"}>
            <BriefingPanel connectionId={connectionId} onInvestigate={(q, insightId) => onInvestigate(q, "investigate", insightId)} canvasId={canvasId} schema={schema} workspaceId={workspaceId} />
          </Layer>
        )}
        {visited.has("ontology") && (
          <Layer show={layer === "ontology"}>
            <OntologyPanel connectionId={connectionId} onInvestigate={q => onInvestigate(q)} />
          </Layer>
        )}
        {visited.has("hub") && (
          <Layer show={layer === "hub"}>
            <IntelligenceHub connectionId={connectionId} canvasId={canvasId} schema={schema} />
          </Layer>
        )}
        {visited.has("evidence") && (
          <Layer show={layer === "evidence"}>
            <EvidencePanel connectionId={connectionId} canvasId={canvasId} onInvestigate={q => onInvestigate(q, "investigate")} />
          </Layer>
        )}
        {visited.has("org") && (
          <Layer show={layer === "org"}>
            <OrgIntelPanel />
          </Layer>
        )}
      </div>
    </div>
  );
}

function Layer({ show, children }: { show: boolean; children: React.ReactNode }) {
  return (
    <div
      className={show ? "aug-anim-fade" : undefined}
      style={{
        position: "absolute",
        inset: 0,
        display: show ? "flex" : "none",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      {children}
    </div>
  );
}
