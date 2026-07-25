"use client";

import dynamic from "next/dynamic";
import { Workspace, type WorkspaceLayer } from "@/components/Workspace";

// ── Lazy panels ──────────────────────────────────────────────────────────────
// Each evals surface is a heavy data view — load on first open, then keep mounted
// (the Workspace's keep-alive), so a suite RUNNING in one layer survives a tab
// switch to the other. Mirrors OperationsWorkspace (Part 2 REC-U5).
const loading = () => (
  <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg-0)" }}>
    <div style={{ width: 20, height: 20, border: "2px solid var(--bg-3)", borderTopColor: "var(--blue3)", borderRadius: "50%", animation: "aug-spin 0.7s linear infinite" }} />
  </div>
);

const EvalSuitesPanel = dynamic(() => import("@/components/EvalSuitesPanel").then(m => ({ default: m.EvalSuitesPanel })), { ssr: false, loading });
const EvalRunPanel    = dynamic(() => import("@/components/EvalRunPanel").then(m => ({ default: m.EvalRunPanel })),       { ssr: false, loading });

// Icon paths mirror the sidebar's NavIcon set (check / activity).
const ICONS: Record<string, string> = {
  check:    "M20 6L9 17l-5-5",
  activity: "M22 12h-4l-3 9L9 3l-3 9H2",
};

function Icon({ name, size = 14, color = "currentColor" }: { name: string; size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
      <path d={ICONS[name]} />
    </svg>
  );
}

export type EvalsLayer = "suites" | "runs";

const LAYERS: WorkspaceLayer<EvalsLayer>[] = [
  { id: "suites", icon: "check",    label: "Suites", blurb: "Cases, targets & evaluators" },
  { id: "runs",   icon: "activity", label: "Runs",   blurb: "Results, replication & the noise floor" },
];

type Props = {
  connId?: string;
  workspaceId?: string;
  /** Active layer — controlled by the shell so external nav can deep-link. */
  layer: EvalsLayer;
  onLayerChange: (l: EvalsLayer) => void;
};

/**
 * The Evals workspace — the surface over Wave E's consolidated eval store (E3),
 * evaluator library (E2) and grid/fidelity harness (E4). An *instance* of the
 * generic `<Workspace>` shell: the shell owns the header + switcher + keep-alive;
 * the panels bring their own bodies. Suites author what to measure; Runs shows a
 * measurement as a band (replicates + noise floor), never a single-run point.
 */
export function EvalsWorkspace({ connId, workspaceId, layer, onLayerChange }: Props) {
  return (
    <Workspace
      layers={LAYERS}
      layer={layer}
      onLayerChange={onLayerChange}
      ariaLabel="Evals views"
      renderIcon={(name, size, color) => <Icon name={name} size={size} color={color} />}
      renderLayer={id => {
        if (id === "runs") return <EvalRunPanel connId={connId} workspaceId={workspaceId} />;
        return <EvalSuitesPanel connId={connId} workspaceId={workspaceId} onLayerChange={onLayerChange} />; // "suites"
      }}
    />
  );
}
