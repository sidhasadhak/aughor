"use client";

import dynamic from "next/dynamic";
import { Workspace, type WorkspaceLayer } from "@/components/Workspace";

// ── Lazy panels ──────────────────────────────────────────────────────────────
// Each layer is a heavy data view — load on first open, then keep mounted (the
// Workspace's keep-alive), mirroring Intelligence/Operations workspaces.
const loading = () => (
  <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg-0)" }}>
    <div style={{ width: 20, height: 20, border: "2px solid var(--bg-3)", borderTopColor: "var(--blue3)", borderRadius: "50%", animation: "aug-spin 0.7s linear infinite" }} />
  </div>
);

const AgentOverviewPanel = dynamic(() => import("@/components/AgentOverviewPanel").then(m => ({ default: m.AgentOverviewPanel })), { ssr: false, loading });
const AgentsAdminPanel   = dynamic(() => import("@/components/AgentsAdminPanel").then(m => ({ default: m.AgentsAdminPanel })),   { ssr: false, loading });
const MemoryPanel        = dynamic(() => import("@/components/MemoryPanel").then(m => ({ default: m.MemoryPanel })),             { ssr: false, loading });

const ICONS: Record<string, string> = {
  spark:  "M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6L12 2z",
  list:   "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  node:   "M5 3a2 2 0 100 4 2 2 0 000-4zM19 17a2 2 0 100 4 2 2 0 000-4zM19 3a2 2 0 100 4 2 2 0 000-4zM7 5h8a2 2 0 012 2v8M5 7v10a2 2 0 002 2h8",
  memory: "M12 3l9 5-9 5-9-5 9-5zM3 12l9 5 9-5M3 17l9 5 9-5",
};

function Icon({ name, size = 14, color = "currentColor" }: { name: string; size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
      <path d={ICONS[name]} />
    </svg>
  );
}

export type AgentLayer = "overview" | "memory" | "manage" | "fleet";

const LAYERS: WorkspaceLayer<AgentLayer>[] = [
  { id: "overview", icon: "spark",  label: "Overview", blurb: "Runs, quality & cost per agent" },
  { id: "memory",   icon: "memory", label: "Memory",   blurb: "What the closed loop has learned" },
  { id: "manage",   icon: "list",   label: "Manage",   blurb: "Create & configure agents" },
  { id: "fleet",    icon: "node",   label: "Fleet",    blurb: "Built-in agents · runs, status & spend" },
];

type Props = {
  /** Active layer — controlled by the shell so external nav can deep-link. */
  layer: AgentLayer;
  onLayerChange: (l: AgentLayer) => void;
  /** The built-in Fleet screen — rendered by the page (it owns FleetScreen's
   *  workspace props + nav handler) and folded in here as the Fleet layer. */
  fleetSlot?: React.ReactNode;
};

/**
 * The Agent workspace — folds the user-defined-agent surfaces AND the built-in
 * Fleet into one perspective-switched view (an instance of the generic
 * `<Workspace>` shell): a native **Overview** (per-agent runs / quality / MLflow
 * trace stats, all rendered from Aughor's own endpoint so MLflow stays
 * backend-only), the existing **Manage** builder, and **Fleet** as the
 * operations layer.
 */
export function AgentWorkspace({ layer, onLayerChange, fleetSlot }: Props) {
  return (
    <Workspace
      layers={LAYERS}
      layer={layer}
      onLayerChange={onLayerChange}
      ariaLabel="Agent views"
      renderIcon={(name, size, color) => <Icon name={name} size={size} color={color} />}
      renderLayer={id => {
        if (id === "manage") return <AgentsAdminPanel />;
        if (id === "fleet")  return <>{fleetSlot}</>;
        if (id === "memory") return <MemoryPanel />;
        return <AgentOverviewPanel onManage={() => onLayerChange("manage")} />; // "overview"
      }}
    />
  );
}
