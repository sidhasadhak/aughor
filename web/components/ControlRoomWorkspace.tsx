"use client";

import { useCallback, useState } from "react";
import dynamic from "next/dynamic";

import { Workspace, type WorkspaceLayer } from "@/components/Workspace";

// ── Lazy panels — load on first open, then keep mounted (Workspace keep-alive),
// so the activity tail and a selected trace survive layer switches.
const loading = () => (
  <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg-0)" }}>
    <div style={{ width: 20, height: 20, border: "2px solid var(--bg-3)", borderTopColor: "var(--blue3)", borderRadius: "50%", animation: "aug-spin 0.7s linear infinite" }} />
  </div>
);

const FleetOverviewPanel = dynamic(() => import("@/components/FleetOverviewPanel").then(m => ({ default: m.FleetOverviewPanel })), { ssr: false, loading });
const NeedsHumanPanel    = dynamic(() => import("@/components/NeedsHumanPanel").then(m => ({ default: m.NeedsHumanPanel })),       { ssr: false, loading });
const ActivityStreamPanel = dynamic(() => import("@/components/ActivityStreamPanel").then(m => ({ default: m.ActivityStreamPanel })), { ssr: false, loading });
const TraceExplorerPanel = dynamic(() => import("@/components/TraceExplorerPanel").then(m => ({ default: m.TraceExplorerPanel })), { ssr: false, loading });
const RunGraphsPanel     = dynamic(() => import("@/components/RunGraphsPanel").then(m => ({ default: m.RunGraphsPanel })),         { ssr: false, loading });

const ICONS: Record<string, string> = {
  gauge:    "M12 15a3 3 0 100-6 3 3 0 000 6zm0-13C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zM12 9l3.5-3.5",
  hand:     "M18 11V6a2 2 0 00-4 0v5m0-3.5V4a2 2 0 00-4 0v7m0-4.5V5a2 2 0 00-4 0v9a7 7 0 0014 0v-3a2 2 0 00-4 0",
  activity: "M22 12h-4l-3 9L9 3l-3 9H2",
  list:     "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  flow:     "M6 3v12a3 3 0 003 3h9m0 0l-3-3m3 3l-3 3M6 3a2 2 0 100 4 2 2 0 000-4z",
};

function Icon({ name, size = 14, color = "currentColor" }: { name: string; size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
      <path d={ICONS[name]} />
    </svg>
  );
}

export type ControlRoomLayer = "overview" | "attention" | "activity" | "traces" | "runs";

const LAYERS: WorkspaceLayer<ControlRoomLayer>[] = [
  { id: "overview",  icon: "gauge",    label: "Fleet",       blurb: "What is running & what it costs" },
  { id: "attention", icon: "hand",     label: "Attention",   blurb: "What needs a human, and for how long" },
  { id: "activity",  icon: "activity", label: "Activity",    blurb: "Every event as it happens" },
  { id: "traces",    icon: "list",     label: "Traces",      blurb: "One run, reconstructed" },
  { id: "runs",      icon: "flow",     label: "Run graphs",  blurb: "Conditions → effects · ADA phases" },
];

type Props = {
  layer: ControlRoomLayer;
  onLayerChange: (l: ControlRoomLayer) => void;
  /** Traces-layer focus (the H3 drill-in): show traces for one investigation. */
  focusInvestigationId?: string | null;
  onOpenInvestigation?: (invId: string) => void;
  onOpenAutomations?: () => void;
  onOpenAgent?: (agentId: string) => void;
};

/**
 * The Control Room (Wave CR) — one surface answering "what is running, what
 * did it do, what did it cost, what needs a human", rendered entirely from
 * stores that already exist and saying plainly what it cannot measure.
 */
export function ControlRoomWorkspace({
  layer, onLayerChange, focusInvestigationId,
  onOpenInvestigation, onOpenAutomations, onOpenAgent,
}: Props) {
  // A trace opened from the activity stream — internal focus, cleared by
  // picking another trace in the list.
  const [innerTrace, setInnerTrace] = useState<string | null>(null);

  const openTrace = useCallback((traceId: string) => {
    setInnerTrace(traceId);
    onLayerChange("traces");
  }, [onLayerChange]);

  return (
    <Workspace
      layers={LAYERS}
      layer={layer}
      onLayerChange={onLayerChange}
      ariaLabel="Control room views"
      renderIcon={(name, size, color) => <Icon name={name} size={size} color={color} />}
      renderLayer={id => {
        if (id === "attention") return (
          <NeedsHumanPanel onOpenInvestigation={onOpenInvestigation}
            onOpenAutomations={onOpenAutomations} />
        );
        if (id === "activity") return <ActivityStreamPanel onOpenTrace={openTrace} />;
        if (id === "traces") return (
          <TraceExplorerPanel focusInvestigationId={focusInvestigationId}
            focusTraceId={innerTrace} />
        );
        if (id === "runs") return <RunGraphsPanel onOpenInvestigation={onOpenInvestigation} />;
        return <FleetOverviewPanel onOpenAgent={onOpenAgent} />; // "overview"
      }}
    />
  );
}
