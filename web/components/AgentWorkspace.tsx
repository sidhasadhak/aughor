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

const ICONS: Record<string, string> = {
  spark: "M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6L12 2z",
  list:  "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
};

function Icon({ name, size = 14, color = "currentColor" }: { name: string; size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
      <path d={ICONS[name]} />
    </svg>
  );
}

export type AgentLayer = "overview" | "manage";

const LAYERS: WorkspaceLayer<AgentLayer>[] = [
  { id: "overview", icon: "spark", label: "Overview", blurb: "Runs, quality & cost per agent" },
  { id: "manage",   icon: "list",  label: "Manage",   blurb: "Create & configure agents" },
];

type Props = {
  /** Active layer — controlled by the shell so external nav can deep-link. */
  layer: AgentLayer;
  onLayerChange: (l: AgentLayer) => void;
};

/**
 * The Agent workspace — folds the user-defined-agent surfaces into one
 * perspective-switched view (an instance of the generic `<Workspace>` shell):
 * a native **Overview** (per-agent runs / quality / MLflow trace stats, all
 * rendered from Aughor's own endpoint so MLflow stays backend-only) over the
 * existing **Manage** builder. Fleet folds in as a later layer.
 */
export function AgentWorkspace({ layer, onLayerChange }: Props) {
  return (
    <Workspace
      layers={LAYERS}
      layer={layer}
      onLayerChange={onLayerChange}
      ariaLabel="Agent views"
      renderIcon={(name, size, color) => <Icon name={name} size={size} color={color} />}
      renderLayer={id => {
        if (id === "manage") return <AgentsAdminPanel />;
        return <AgentOverviewPanel onManage={() => onLayerChange("manage")} />; // "overview"
      }}
    />
  );
}
