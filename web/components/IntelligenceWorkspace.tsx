"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";

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
const ExplorationPanel = dynamic(() => import("@/components/ExplorationPanel").then(m => ({ default: m.ExplorationPanel })),{ ssr: false, loading });
const OrgIntelPanel    = dynamic(() => import("@/components/OrgIntelPanel").then(m => ({ default: m.OrgIntelPanel })),      { ssr: false, loading });

// Minimal inline icon set — mirrors NavIcon paths used elsewhere in the shell.
const ICONS: Record<string, string> = {
  brief:   "M3 5h18M3 9h18M3 13h12M3 17h8",
  node:    "M12 4a2 2 0 100 4 2 2 0 000-4zM6 18a2 2 0 100 4 2 2 0 000-4zm12 0a2 2 0 100 4 2 2 0 000-4zM12 6v4m0 4v4M8 19h8M14 7l4 10M10 7L6 17",
  layers:  "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
  process: "M3 6h4v12H3V6zm7-3h4v18h-4V3zm7 6h4v9h-4V9z",
  spark:   "M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6L12 2z",
};

function Icon({ name, size = 14, color = "currentColor" }: { name: string; size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
      <path d={ICONS[name]} />
    </svg>
  );
}

export type IntelLayer = "briefing" | "hub" | "ontology" | "domains" | "org";

const LAYERS: { id: IntelLayer; icon: string; label: string; blurb: string }[] = [
  { id: "briefing", icon: "brief",   label: "Briefing", blurb: "Cross-domain synthesis" },
  { id: "hub",      icon: "layers",  label: "Hub",      blurb: "Domain knowledge profiles" },
  { id: "ontology", icon: "node",    label: "Ontology", blurb: "Object model & relationships" },
  { id: "domains",  icon: "process", label: "Domains",  blurb: "Process & data intelligence" },
  { id: "org",      icon: "spark",   label: "Org",      blurb: "Organizational knowledge" },
];

type Props = {
  connectionId: string;
  onInvestigate: (q?: string, mode?: "ask" | "investigate") => void;
  /** Active layer — controlled by the shell so external nav can deep-link. */
  layer: IntelLayer;
  onLayerChange: (l: IntelLayer) => void;
  /** ExplorationPanel deep-link section, applied when the Domains layer mounts. */
  domainSection?: "nulls" | "lifecycles" | "distributions" | "insights" | "intelligence";
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
export function IntelligenceWorkspace({ connectionId, onInvestigate, layer, onLayerChange, domainSection }: Props) {
  // Mount a layer the first time it becomes active, then keep it mounted.
  const [visited, setVisited] = useState<Set<IntelLayer>>(() => new Set([layer]));
  useEffect(() => {
    setVisited(prev => (prev.has(layer) ? prev : new Set(prev).add(layer)));
  }, [layer]);

  const active = LAYERS.find(l => l.id === layer)!;

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-0)" }}>
      {/* Workspace header — title + perspective switcher */}
      <div className="aug-content-header" style={{ gap: 14 }}>
        <Icon name={active.icon} size={14} color="var(--t3)" />
        <span style={{ fontSize: 13, fontWeight: 500 }}>{active.label}</span>
        <span style={{ fontSize: 11, color: "var(--t3)" }}>· {active.blurb}</span>

        {/* Layer switcher — segmented control */}
        <div
          role="tablist"
          aria-label="Intelligence layers"
          style={{
            marginLeft: "auto",
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
            <BriefingPanel connectionId={connectionId} onInvestigate={q => onInvestigate(q, "investigate")} />
          </Layer>
        )}
        {visited.has("ontology") && (
          <Layer show={layer === "ontology"}>
            <OntologyPanel connectionId={connectionId} onInvestigate={q => onInvestigate(q)} />
          </Layer>
        )}
        {visited.has("hub") && (
          <Layer show={layer === "hub"}>
            <IntelligenceHub connectionId={connectionId} />
          </Layer>
        )}
        {visited.has("domains") && (
          <Layer show={layer === "domains"}>
            <ExplorationPanel connectionId={connectionId} initialSection={domainSection} />
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
