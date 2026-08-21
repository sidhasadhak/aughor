"use client";

import { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";

import { Workspace, type WorkspaceLayer } from "@/components/Workspace";
import { getNeedsHuman } from "@/lib/api";
import { Icon as Glyph, type IconName } from "@/components/ui/icon";

// ── Lazy panels — load on first open, then keep mounted (Workspace keep-alive),
// so the activity tail, a selected trace and an agent detail survive switches.
const loading = () => (
  <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg-0)" }}>
    <div style={{ width: 20, height: 20, border: "2px solid var(--bg-3)", borderTopColor: "var(--blue3)", borderRadius: "50%", animation: "aug-spin 0.7s linear infinite" }} />
  </div>
);

const FleetOverviewPanel = dynamic(() => import("@/components/FleetOverviewPanel").then(m => ({ default: m.FleetOverviewPanel })), { ssr: false, loading });
const AgenticAgentsPanel = dynamic(() => import("@/components/AgenticAgentsPanel").then(m => ({ default: m.AgenticAgentsPanel })), { ssr: false, loading });
const NeedsHumanPanel    = dynamic(() => import("@/components/NeedsHumanPanel").then(m => ({ default: m.NeedsHumanPanel })),       { ssr: false, loading });
const AgenticActivityPanel = dynamic(() => import("@/components/AgenticActivityPanel").then(m => ({ default: m.AgenticActivityPanel })), { ssr: false, loading });
const RunGraphsPanel     = dynamic(() => import("@/components/RunGraphsPanel").then(m => ({ default: m.RunGraphsPanel })),         { ssr: false, loading });

/**
 * This screen's glyphs, by role. The drawings come from the platform icon set
 * (`components/ui/icon.tsx`); this map only says which role each local name means,
 * so the existing call sites and `LAYERS` entries keep working unchanged.
 */
const ROLE: Record<string, IconName> = {
  gauge: "gauge",
  spark: "spark",
  hand: "hand",
  activity: "activity",
  flow: "flow",
};

function Icon({ name, size = 14, color = "currentColor" }: { name: string; size?: number; color?: string }) {
  return (
    <span style={{ color, display: "inline-flex", flexShrink: 0 }}>
      <Glyph name={ROLE[name] ?? "info"} size={size} />
    </span>
  );
}

export type AgenticOpsLayer = "fleet" | "agents" | "attention" | "activity" | "runs";

const LAYERS: WorkspaceLayer<AgenticOpsLayer>[] = [
  { id: "fleet",     icon: "gauge",    label: "Overview",   blurb: "What is running & what it costs" },
  { id: "agents",    icon: "spark",    label: "Agents",     blurb: "Roster, governance & configuration" },
  { id: "attention", icon: "hand",     label: "Attention",  blurb: "What needs a human, and for how long" },
  { id: "activity",  icon: "activity", label: "Activity",   blurb: "Every event · one run reconstructed" },
  { id: "runs",      icon: "flow",     label: "Run graphs", blurb: "Conditions → effects · deep analysis phases" },
];

type Props = {
  layer: AgenticOpsLayer;
  onLayerChange: (l: AgenticOpsLayer) => void;
  workspaceId?: string;
  workspaceName?: string;
  onOpenInvestigation?: (invId: string) => void;
  onOpenAutomations?: () => void;
};

/**
 * Agentic Ops — ONE surface for the agent estate, merging the former Control
 * Room, Agents and Fleet tabs: what is running, what it did, what it cost,
 * what needs a human, and who the agents are — rendered from stores that
 * already exist and saying plainly what it cannot measure.
 */
export function AgenticOpsWorkspace({
  layer, onLayerChange, workspaceId, workspaceName,
  onOpenInvestigation, onOpenAutomations,
}: Props) {
  // Cross-layer focus: a trace opened from Fleet/Agents/Attention lands in the
  // Activity layer's runs mode; an agent opened from Fleet lands in Agents.
  const [traceFocus, setTraceFocus] = useState<{ traceId?: string; investigationId?: string } | null>(null);
  const [agentFocus, setAgentFocus] = useState<{ id: string; kind: "charter" | "persona" } | null>(null);
  const [attention, setAttention] = useState(0);

  // The Attention badge — polled at workspace level so the count is visible
  // from every layer, not only when the Attention panel is open.
  useEffect(() => {
    let alive = true;
    const poll = () => getNeedsHuman(1).then(d => { if (alive) setAttention(d.count); }).catch(() => {});
    poll();
    const iv = setInterval(poll, 20_000);
    return () => { alive = false; clearInterval(iv); };
  }, []);

  const openTraceForInvestigation = useCallback((invId: string) => {
    setTraceFocus({ investigationId: invId });
    onLayerChange("activity");
  }, [onLayerChange]);

  return (
    <Workspace
      layers={LAYERS}
      layer={layer}
      onLayerChange={onLayerChange}
      ariaLabel="Agents views"
      badges={{ attention }}
      renderIcon={(name, size, color) => <Icon name={name} size={size} color={color} />}
      renderLayer={id => {
        if (id === "agents") return (
          <AgenticAgentsPanel workspaceId={workspaceId} workspaceName={workspaceName}
            focusAgent={agentFocus} onOpenTrace={openTraceForInvestigation} />
        );
        if (id === "attention") return (
          <NeedsHumanPanel onOpenInvestigation={onOpenInvestigation}
            onOpenAutomations={onOpenAutomations} />
        );
        if (id === "activity") return (
          <AgenticActivityPanel
            focusInvestigationId={traceFocus?.investigationId}
            focusTraceId={traceFocus?.traceId} />
        );
        if (id === "runs") return <RunGraphsPanel onOpenInvestigation={onOpenInvestigation} />;
        return (
          <FleetOverviewPanel onOpenAgent={(id, kind) => {
            setAgentFocus({ id, kind });
            onLayerChange("agents");
          }} /> // "fleet"
        );
      }}
    />
  );
}
